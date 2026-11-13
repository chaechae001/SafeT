"""One model/precision per process. Frozen diagnostics, no training or service writes."""
import argparse
import collections
import hashlib
import json
import math
import re
import shutil
import statistics
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OBJECTS = {'oven', 'microwave', 'sink', 'refrigerator'}
DEVICES = {'gas_detector', 'smoke_detector', 'fire_extinguisher', 'thermostat', 'other_device', 'unknown'}
STATES = {'candidate', 'insufficient_information', 'out_of_scope'}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def parse(raw, task, labels):
    match = re.search(r'\{.*\}', raw, re.S)
    try:
        value = json.loads(match.group()) if match else None
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    keys = {'objects'} if task == 'objects' else {'text'} if task == 'ocr' else (
        {'objects', 'gas_leak_status'} if task == 'facility' else
        {'objects', 'text'} if task == 'empty_control' else {'hazard_labels', 'assessment_state'})
    if set(value) != keys:
        return None
    if 'text' in value and not isinstance(value['text'], str):
        return None
    if 'objects' in value:
        allowed = DEVICES if task == 'facility' else OBJECTS | DEVICES
        if task == 'objects':
            allowed = OBJECTS
        if not isinstance(value['objects'], list) or not all(isinstance(x, str) and x in allowed for x in value['objects']):
            return None
    if task == 'facility' and value['gas_leak_status'] not in ('detected', 'not_detected', 'not_determinable'):
        return None
    if task == 'text_regression':
        if not isinstance(value['hazard_labels'], list) or not all(isinstance(x, str) and x in labels for x in value['hazard_labels']):
            return None
        if not isinstance(value['assessment_state'], str) or value['assessment_state'] not in STATES:
            return None
        if (value['assessment_state'] == 'candidate') != bool(value['hazard_labels']):
            return None
    return value


def normalized(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', text))


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def score(rows, references, labels):
    refs = {r['id']: r for r in references}
    assert len(refs) == len(rows) and {r['id'] for r in rows} == set(refs)
    result = {}
    for task in sorted({r['task'] for r in rows}):
        group = [r for r in rows if r['task'] == task]
        valid = [r for r in group if r['parsed'] is not None]
        times = sorted(r['total_seconds'] for r in group)
        item = dict(n=len(group),strict_valid=len(valid),median_seconds=statistics.median(times),
                    p95_seconds=times[max(0, math.ceil(len(times) * .95) - 1)],
                    truncated=sum(r['hit_token_limit'] for r in group))
        if task == 'ocr':
            edits = chars = exact = 0
            for row in group:
                target = normalized(refs[row['id']]['text'])
                predicted = normalized(row['parsed']['text']) if row['parsed'] else ''
                edits += distance(target, predicted)
                chars += len(target)
                exact += int(row['parsed'] is not None and target == predicted)
            item.update(character_edits=edits,reference_characters=chars,cer=edits/chars,exact=exact,
                        scope='Synthetic rendered text, not field OCR')
        elif task == 'objects':
            tp = fp = fn = exact = 0
            for row in group:
                target = set(refs[row['id']]['objects'])
                predicted = set(row['parsed']['objects']) if row['parsed'] else set()
                tp += len(target & predicted); fp += len(predicted - target); fn += len(target - predicted)
                exact += int(row['parsed'] is not None and predicted == target)
            item.update(tp=tp,fp=fp,fn=fn,micro_f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,exact=exact)
        elif task == 'facility':
            item.update(positive_inclusion=sum(refs[r['id']]['required_object'] in r['parsed']['objects'] for r in valid),
                        uncertainty_contract=sum(r['parsed']['gas_leak_status']=='not_determinable' for r in valid),
                        unsupported_gas_claims=sum(r['parsed']['gas_leak_status']!='not_determinable' for r in valid),
                        scope='Positive images only; response-constraint check, not gas detection')
        elif task == 'empty_control':
            item.update(hallucinated=sum(bool(r['parsed']['objects'] or r['parsed']['text'].strip()) for r in valid),
                        scope='Uniform synthetic controls; invalid outputs reported separately')
        else:
            per_label = {}; omitted = positives = 0
            for label in labels:
                tp = fp = fn = 0
                for row in group:
                    target = label in refs[row['id']]['labels']
                    predicted = row['parsed'] is not None and label in row['parsed']['hazard_labels']
                    tp += int(target and predicted); fp += int(not target and predicted); fn += int(target and not predicted)
                per_label[label] = dict(tp=tp,fp=fp,fn=fn,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
                omitted += fn; positives += tp+fn
            item.update(provisional_macro_f1=sum(r['f1'] for r in per_label.values())/len(labels),
                        provisional_omission_rate=omitted/positives if positives else None,
                        per_label=per_label,scope='Previously used v4 AI references; regression, not independent validation')
        result[task] = item
    return result


def verify_inputs():
    data = ROOT/'frozen'
    for name, digest in load(data/'hashes.json').items():
        assert hashlib.sha256((data/name).read_bytes()).hexdigest() == digest, name
    inputs = load(data/'inputs.json')
    for row in inputs:
        if 'image' not in row:
            continue
        path = data/row['image']
        if not path.exists() and 'source_cloud_image' in row:
            source = Path(row['source_cloud_image'])
            assert hashlib.sha256(source.read_bytes()).hexdigest() == row['image_sha256']
            path.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['image_sha256'], row['id']
    return inputs


def run(args):
    import resource
    import platform
    import importlib.metadata
    import torch
    import transformers
    from PIL import Image
    from transformers import AutoProcessor, BitsAndBytesConfig

    inputs = verify_inputs()
    settings = load(ROOT/'261112_execution_settings_DR.json')
    candidate = next(r for r in load(ROOT/'261112_candidate_models_DR.json') if r['id'] == args.model)
    target = ROOT/('probes' if args.probe else 'results')/(args.model.split('/')[-1]+'_'+args.precision)
    target.mkdir(parents=True,exist_ok=False)
    config = dict(model=candidate,precision=args.precision,settings=settings,
                  environment=dict(python=platform.python_version(),torch=torch.__version__,cuda=torch.version.cuda,
                                   transformers=transformers.__version__,gpu=torch.cuda.get_device_name(0),
                                   gpu_total_bytes=torch.cuda.get_device_properties(0).total_memory,
                                   gpu_free_total_bytes=torch.cuda.mem_get_info()),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  settings_sha256=hashlib.sha256((ROOT/'261112_execution_settings_DR.json').read_bytes()).hexdigest())
    save(target/'config.json',config)
    try:
        torch.manual_seed(42)
        started=time.perf_counter()
        processor=AutoProcessor.from_pretrained(args.model,revision=candidate['revision'],
                  min_pixels=settings['min_pixels'],max_pixels=settings['max_pixels'],use_fast=False)
        cls=getattr(transformers,'Qwen2_5_VLForConditionalGeneration' if 'Qwen2.5' in args.model else 'Qwen3VLForConditionalGeneration')
        options=dict(revision=candidate['revision'],torch_dtype=torch.bfloat16,device_map={'':0},attn_implementation='sdpa')
        if args.precision=='nf4':
            options['quantization_config']=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16)
        model=cls.from_pretrained(args.model,**options).eval()
        torch.cuda.synchronize()
        config['load_seconds']=time.perf_counter()-started
        config['gpu_allocated_after_load']=torch.cuda.memory_allocated()
        config['gpu_reserved_after_load']=torch.cuda.memory_reserved()
        save(target/'config.json',config)
        labels=load(ROOT/'frozen/taxonomy.json')

        def generate(row):
            start=time.perf_counter()
            prompt=settings['prompts'][row['task']]
            content=[];image=None
            if 'image' in row:
                with Image.open(ROOT/'frozen'/row['image']) as opened:
                    image=opened.convert('RGB')
                content.append(dict(type='image',image=image))
            if row['task']=='text_regression':
                prompt+='\n'+json.dumps(dict(situation=row['situation'],allowed_labels=labels),ensure_ascii=False)
            content.append(dict(type='text',text=prompt))
            text=processor.apply_chat_template([dict(role='user',content=content)],tokenize=False,add_generation_prompt=True)
            batch=processor(text=[text],images=[image],return_tensors='pt') if image is not None else processor(text=[text],return_tensors='pt')
            batch=batch.to('cuda');torch.cuda.synchronize()
            generation_start=time.perf_counter()
            with torch.inference_mode():
                output=model.generate(**batch,do_sample=False,max_new_tokens=settings['max_new_tokens'])
            torch.cuda.synchronize();end=time.perf_counter()
            generated=output[:,batch.input_ids.shape[1]:]
            raw=processor.batch_decode(generated,skip_special_tokens=True)[0]
            return dict(id=row['id'],task=row['task'],raw=raw,parsed=parse(raw,row['task'],labels),
                        total_seconds=end-start,generation_seconds=end-generation_start,
                        input_tokens=int(batch.input_ids.shape[1]),output_tokens=int(generated.shape[1]),
                        hit_token_limit=bool(generated.shape[1]>=settings['max_new_tokens']),
                        image_grid_thw=batch['image_grid_thw'].cpu().tolist() if 'image_grid_thw' in batch else None)

        warmup=generate(inputs[0])
        save(target/'warmup.json',warmup)
        if args.probe:
            save(target/'probe.json',dict(status='probe_only',output=warmup,
                peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved()))
            print('PROBE_COMPLETE',target,flush=True)
            return
        torch.cuda.reset_peak_memory_stats()
        rows=[]
        with (target/'predictions.jsonl').open('x',encoding='utf-8') as handle:
            for index,row in enumerate(inputs,1):
                output=generate(row);rows.append(output)
                handle.write(json.dumps(output,ensure_ascii=False)+'\n');handle.flush()
                print('CASE',index,len(inputs),row['id'],'valid',output['parsed'] is not None,flush=True)
        references=load(ROOT/'frozen/references.json')
        save(target/'summary.json',dict(status='complete',scores=score(rows,references,list(labels)),
             peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved(),
             cpu_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             independent_field_validation=False))
        print('COMPARISON_COMPLETE',target,flush=True)
    except Exception as error:
        save(target/'failure.json',dict(type=type(error).__name__,message=str(error),
             peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved()))
        raise


def self_test():
    assert normalized('가스 냄새가 없습니다.') != normalized('가스 냄새가 있습니다.')
    assert distance('가나다','가나다')==0 and distance('가나다','가라다')==1
    assert distance('','가나다')==3 and distance('가나다','')==3
    assert parse('{"objects":[{"type":"gas_detector"}],"gas_leak_status":"not_determinable"}','facility',[]) is None
    assert parse('{"hazard_labels":[],"assessment_state":"safe"}','text_regression',['slip']) is None
    refs=[dict(id='a',objects=['sink','oven'])]
    rows=[dict(id='a',task='objects',parsed=dict(objects=['sink','microwave']),total_seconds=1,hit_token_limit=False)]
    result=score(rows,refs,[])['objects']
    assert (result['tp'],result['fp'],result['fn'],result['micro_f1'])==(1,1,1,.5)
    refs=[dict(id='a',text='가스 없음')]
    rows=[dict(id='a',task='ocr',parsed=None,total_seconds=1,hit_token_limit=False)]
    assert score(rows,refs,[])['ocr']['cer']==1
    print('COMPARISON_SELF_TEST_PASS')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--model')
    parser.add_argument('--precision',choices=['bf16','nf4'])
    parser.add_argument('--probe',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    self_test()
    if not args.self_test:
        if not args.model or not args.precision:
            parser.error('--model and --precision are required')
        run(args)
