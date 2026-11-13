"""Matched single-model / staged inference diagnostic. No training or safety approval."""
import argparse
import collections
import hashlib
import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / 'frozen'
OBJECTS = {'oven', 'microwave', 'sink', 'refrigerator', 'gas_detector'}
STATES = {'candidate', 'insufficient_information', 'out_of_scope'}
FINAL_KEYS = {'hazard_labels', 'assessment_state', 'objects', 'image_text', 'gas_leak_status'}
OBS_KEYS = {'objects', 'image_text', 'visible_facts', 'gas_leak_status'}
SPEC = importlib.util.spec_from_file_location('previous_diagnostic', ROOT.parent / '261112_model_selection_DR/261112_compare_models_DR.py')
UTIL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UTIL)

FINAL_PROMPT = '''치킨 전문점의 위험 신고를 분류한다. 최종 안전 승인을 하지 않는다.
JSON 객체 하나만 출력한다. 키는 hazard_labels, assessment_state, objects, image_text, gas_leak_status다.
hazard_labels는 allowed_labels의 ID 배열이다. 여러 위험 후보를 모두 선택한다.
assessment_state는 candidate, insufficient_information, out_of_scope 중 하나다.
위험 메커니즘이 기록되면 candidate다. 정보가 부족하면 insufficient_information과 빈 라벨 배열이다.
행정적 조회·계정·파일 관리 요청은 out_of_scope와 빈 라벨 배열이다.
부정문을 보존한다. 뜨거운 증기는 burn이다. 조리흄과 환기는 respiratory다.
설비가 보인다는 이유만으로 가열·누전·가스누출·위험을 가정하지 않는다. 근거 문서는 현장의 관찰 사실이 아니다.
objects에는 사진에서 확인한 oven,microwave,sink,refrigerator,gas_detector만 영어 문자열로 기록한다.
이미지나 관찰 결과가 없으면 objects는 빈 배열이다. objects의 다른 종류는 포함하지 않는다.
image_text에는 이미지에서 읽은 글자를 기록한다. 이미지가 없거나 글자가 없으면 빈 문자열이다.
관찰 결과와 OCR 결과는 오류가 있을 수 있다. OCR이 제공되면 글자 인식 근거로 활용하되 없는 내용을 보충하지 않는다.
정지 사진과 일반 신고문으로 가스 농도·누출 확정이 불가능하므로 gas_leak_status는 not_determinable이다.
권고 문서만으로 법 준수를 판정하지 않는다. 설명·마크다운·다른 키를 추가하지 않는다.'''

OBS_PROMPT = '''이미지에서 관찰한 사실만 JSON 하나로 기록한다. 위험 분류나 대책은 작성하지 않는다.
키는 objects, image_text, visible_facts, gas_leak_status다.
objects는 사진에서 확인한 oven,microwave,sink,refrigerator,gas_detector 중 영어 문자열 배열이다.
image_text는 이미지 속 글자를 원문 그대로 읽은 문자열이다. 부정문·수량을 보존한다. 글자가 없으면 빈 문자열이다.
visible_facts에는 보이는 배치를 짧게 한 문장으로 기록한다. 문서 사진이면 문서라고 기록한다.
정지 사진으로 실제 가스누출·온도·설비 고장을 가정하지 않는다. gas_leak_status는 not_determinable이다.
설명·마크다운·다른 키를 추가하지 않는다.'''


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=lambda item: item.tolist()), encoding='utf-8')


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def parse(raw, labels, observer=False):
    raw = raw.strip()
    for prefix in ('```json\n', '```\n'):
        if raw.startswith(prefix) and raw.endswith('\n```'):
            raw = raw[len(prefix):-4].strip()
            break
    try:
        # A Markdown wrapper is formatting; never repair fields or infer missing values.
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != (OBS_KEYS if observer else FINAL_KEYS):
        return None
    if not isinstance(value['objects'], list) or not all(isinstance(x, str) and x in OBJECTS for x in value['objects']):
        return None
    if not isinstance(value['image_text'], str) or value['gas_leak_status'] not in ('detected', 'not_detected', 'not_determinable'):
        return None
    if observer:
        return value if isinstance(value['visible_facts'], str) else None
    if not isinstance(value['hazard_labels'], list) or not all(isinstance(x, str) and x in labels for x in value['hazard_labels']):
        return None
    state = value['assessment_state']
    if not isinstance(state, str) or state not in STATES or (state == 'candidate') != bool(value['hazard_labels']):
        return None
    return value


def verify():
    for name, digest in read(FROZEN / 'hashes.json').items():
        assert hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() == digest, name
    inputs = read(FROZEN / 'inputs.json')
    for row in inputs:
        assert not set(row) & {'labels', 'assessment_state', 'objects', 'image_text'}
        if 'image' not in row:
            continue
        path = FROZEN / row['image']
        if not path.is_file():
            source = Path(row['source_cloud_image'])
            assert hashlib.sha256(source.read_bytes()).hexdigest() == row['image_sha256']
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(source.read_bytes())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['image_sha256'], row['id']
    return inputs


def latency(values):
    ordered = sorted(values)
    return dict(median_seconds=statistics.median(ordered), p95_seconds=ordered[math.ceil(len(ordered) * .95)-1])


def score(predictions, references, labels):
    refs = {r['id']: r for r in references}
    assert len(predictions) == len(refs) and {r['id'] for r in predictions} == set(refs)
    result = {}
    for group in sorted({r['group'] for r in predictions}):
        items = [r for r in predictions if r['group'] == group]
        valid = [r for r in items if r.get('parsed') is not None]
        item = dict(n=len(items), valid_schema=len(valid), **latency([r['total_seconds'] for r in items]),
                    raw_json_only=sum(r['parsed'] is not None and r.get('raw', '').strip().startswith('{') for r in items),
                    state_correct=sum(r['parsed'] is not None and r['parsed']['assessment_state'] == refs[r['id']]['assessment_state'] for r in items),
                    gas_uncertainty_correct=sum(r['parsed'] is not None and r['parsed']['gas_leak_status'] == 'not_determinable' for r in items),
                    truncated=sum(r.get('hit_token_limit', False) for r in items))
        per_label = {}
        for label in labels:
            tp = fp = fn = 0
            for row in items:
                gold = label in refs[row['id']]['labels']
                predicted = row['parsed'] is not None and label in row['parsed']['hazard_labels']
                tp += int(gold and predicted)
                fp += int(not gold and predicted)
                fn += int(gold and not predicted)
            per_label[label] = dict(tp=tp, fp=fp, fn=fn, f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
        positives = sum(v['tp'] + v['fn'] for v in per_label.values())
        item.update(provisional_macro_f1=sum(v['f1'] for v in per_label.values())/len(labels) if positives else None,
                    omission_rate=sum(v['fn'] for v in per_label.values())/positives if positives else None,
                    hazard_fp=sum(v['fp'] for v in per_label.values()), per_label=per_label)
        if group in ('objects', 'facility', 'empty_control'):
            tp = fp = fn = exact = 0
            for row in items:
                gold = set(refs[row['id']]['objects'])
                predicted = set(row['parsed']['objects']) if row['parsed'] else set()
                tp += len(gold & predicted)
                fp += len(predicted - gold)
                fn += len(gold - predicted)
                exact += int(row['parsed'] is not None and gold == predicted)
            item.update(object_tp=tp, object_fp=fp, object_fn=fn, object_exact=exact,
                        object_micro_f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)
        if group == 'rendered_report':
            chars = edits = exact = 0
            for row in items:
                target = UTIL.normalized(refs[row['id']]['image_text'])
                predicted = UTIL.normalized(row['parsed']['image_text']) if row['parsed'] else ''
                chars += len(target)
                edits += UTIL.distance(target, predicted)
                exact += int(row['parsed'] is not None and target == predicted)
            item.update(character_edits=edits, reference_characters=chars, cer=edits/chars, text_exact=exact)
        result[group] = item
    return result


def model_info(stage):
    candidates = read(ROOT.parent / '261112_model_selection_DR/261112_candidate_models_DR.json')
    if stage == 'single_qwen25':
        return next(x for x in candidates if 'Qwen2.5' in x['id']), 'bf16', True
    if stage in ('single_qwen3', 'observe'):
        return next(x for x in candidates if '4B' in x['id']), 'nf4', True
    return read(ROOT / 'text_model.json'), 'nf4', False


def run_model(stage):
    import resource
    import torch
    import transformers
    from PIL import Image
    from transformers import AutoTokenizer, AutoProcessor, AutoModelForCausalLM, BitsAndBytesConfig

    inputs = verify()
    labels = read(FROZEN / 'taxonomy.json')
    evidence = read(FROZEN / 'evidence.json')
    observer = stage == 'observe'
    pipeline = stage.startswith('pipeline_')
    observations = {r['id']: r for r in rows(ROOT / 'results/observe/predictions.jsonl')} if pipeline else {}
    ocr = {r['id']: r for r in rows(ROOT / 'results/ocr/predictions.jsonl')} if stage == 'pipeline_ocr' else {}
    out = ROOT / 'results' / stage
    out.mkdir(parents=True, exist_ok=False)
    info, precision, vision = model_info(stage)
    config = dict(stage=stage, model=info, precision=precision, torch=torch.__version__, transformers=transformers.__version__,
                  gpu=torch.cuda.get_device_name(0), gpu_free_total_bytes=torch.cuda.mem_get_info(), max_pixels=262144,
                  max_new_tokens=384 if observer else 256, batch_size=1, do_sample=False,
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  inputs_sha256=hashlib.sha256((FROZEN / 'inputs.json').read_bytes()).hexdigest(),
                  evidence_sha256=hashlib.sha256((FROZEN / 'evidence.json').read_bytes()).hexdigest(),
                  parser_policy='Strip only an exact outer json/plain Markdown fence, then strict field validation. Raw JSON-only compliance reported separately.',
                  final_prompt=FINAL_PROMPT, observation_prompt=OBS_PROMPT,
                  latency_scope='Warm batched diagnostic; summed serial stages. Load time separate; no per-request switching measured.')
    save(out / 'config.json', config)
    torch.manual_seed(42)
    options = dict(revision=info['revision'], torch_dtype=torch.bfloat16, device_map={'': 0}, attn_implementation='sdpa', local_files_only=True)
    if precision == 'nf4':
        options['quantization_config'] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
    start = time.perf_counter()
    if vision:
        processor = AutoProcessor.from_pretrained(info['id'], revision=info['revision'], local_files_only=True,
                                                 min_pixels=3136, max_pixels=262144, use_fast=False)
        cls = transformers.Qwen2_5_VLForConditionalGeneration if 'Qwen2.5' in info['id'] else transformers.Qwen3VLForConditionalGeneration
        model = cls.from_pretrained(info['id'], **options).eval()
    else:
        processor = AutoTokenizer.from_pretrained(info['id'], revision=info['revision'], local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(info['id'], **options).eval()
    torch.cuda.synchronize()
    config['load_seconds'] = time.perf_counter() - start
    save(out / 'config.json', config)

    def generate(row):
        started = time.perf_counter()
        prior = observations.get(row['id'])
        recognized = ocr.get(row['id'])
        payload = dict(situation=row['situation'])
        if not observer:
            payload.update(allowed_labels=labels, evidence=evidence)
        if pipeline:
            payload['observation'] = prior['parsed'] if prior and prior['parsed'] else None
            payload['observation_error'] = bool(prior and prior['parsed'] is None)
            if recognized:
                payload['ocr'] = dict(text=recognized['text'], records=recognized['records'], failed=recognized.get('error') is not None)
        image = None
        if vision:
            content = []
            if 'image' in row:
                with Image.open(FROZEN / row['image']) as source:
                    image = source.convert('RGB')
                content.append(dict(type='image', image=image))
            content.append(dict(type='text', text=json.dumps(payload, ensure_ascii=False)))
            messages = [dict(role='system', content=OBS_PROMPT if observer else FINAL_PROMPT), dict(role='user', content=content)]
            text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            batch = processor(text=[text], images=[image], return_tensors='pt') if image is not None else processor(text=[text], return_tensors='pt')
        else:
            text = processor.apply_chat_template([dict(role='system', content=FINAL_PROMPT), dict(role='user', content=json.dumps(payload, ensure_ascii=False))],
                                                 tokenize=False, add_generation_prompt=True, enable_thinking=False)
            batch = processor(text, return_tensors='pt')
        batch = batch.to('cuda')
        torch.cuda.synchronize()
        generated_at = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(**batch, do_sample=False, max_new_tokens=config['max_new_tokens'])
        torch.cuda.synchronize()
        ended = time.perf_counter()
        generated = output[:, batch.input_ids.shape[1]:]
        raw = processor.batch_decode(generated, skip_special_tokens=True)[0]
        model_seconds = ended - started
        observation_seconds = prior['total_seconds'] if prior else 0
        ocr_seconds = recognized['total_seconds'] if recognized else 0
        return dict(id=row['id'], group=row['group'], raw=raw, parsed=parse(raw, labels, observer),
                    model_seconds=model_seconds, observation_seconds=observation_seconds, ocr_seconds=ocr_seconds,
                    total_seconds=model_seconds+observation_seconds+ocr_seconds, generation_seconds=ended-generated_at,
                    input_tokens=int(batch.input_ids.shape[1]), output_tokens=int(generated.shape[1]),
                    hit_token_limit=int(generated.shape[1]) >= config['max_new_tokens'])

    selected = [r for r in inputs if 'image' in r] if observer else inputs
    save(out / 'warmup.json', generate(selected[0]))
    torch.cuda.reset_peak_memory_stats()
    all_rows = []
    with (out / 'predictions.jsonl').open('x', encoding='utf-8') as handle:
        for index, row in enumerate(selected, 1):
            prediction = generate(row)
            all_rows.append(prediction)
            handle.write(json.dumps(prediction, ensure_ascii=False)+'\n')
            handle.flush()
            print('CASE', stage, index, len(selected), row['id'], prediction['parsed'] is not None, flush=True)
    summary = dict(status='complete', n=len(all_rows), peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                   peak_reserved_bytes=torch.cuda.max_memory_reserved(), cpu_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if not observer:
        summary['scores'] = score(all_rows, read(FROZEN / 'references.json'), list(labels))
    save(out / 'summary.json', summary)
    print('STAGE_COMPLETE', stage, flush=True)


def run_ocr():
    from paddleocr import PaddleOCR
    import importlib.metadata
    selected = [r for r in verify() if 'image' in r]
    out = ROOT / 'results/ocr'
    out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    model = PaddleOCR(text_detection_model_name='PP-OCRv5_mobile_det', text_recognition_model_name='korean_PP-OCRv5_mobile_rec',
                      use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
                      device='cpu', enable_mkldnn=False, cpu_threads=2)
    save(out / 'config.json', dict(paddleocr=importlib.metadata.version('paddleocr'), paddlepaddle=importlib.metadata.version('paddlepaddle'),
         device='cpu', cpu_threads=2, enable_mkldnn=False, load_seconds=time.perf_counter()-start,
         detector='PP-OCRv5_mobile_det', recognizer='korean_PP-OCRv5_mobile_rec',
         script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))

    def generate(row):
        start = time.perf_counter()
        records, raw = [], []
        try:
            for result in model.predict(str(FROZEN / row['image'])):
                value = result.json
                value = value.get('res', value)
                raw.append(value)
                texts, scores = value.get('rec_texts', []), value.get('rec_scores', [])
                boxes = value.get('rec_boxes', [])
                for index, text in enumerate(texts):
                    records.append(dict(text=text, score=float(scores[index]), box=list(map(int, boxes[index])) if index < len(boxes) else None))
            return dict(id=row['id'], group=row['group'], text=' '.join(r['text'] for r in records), records=records,
                        raw=raw, total_seconds=time.perf_counter()-start)
        except Exception as error:
            return dict(id=row['id'], group=row['group'], text='', records=[], total_seconds=time.perf_counter()-start,
                        error=dict(type=type(error).__name__, message=str(error)))

    def encode(value):
        return value.tolist() if hasattr(value, 'tolist') else str(value)

    save(out / 'warmup.json', generate(selected[0]))
    count = failures = 0
    with (out / 'predictions.jsonl').open('x', encoding='utf-8') as handle:
        for row in selected:
            prediction = generate(row)
            count += 1
            failures += int('error' in prediction)
            handle.write(json.dumps(prediction, ensure_ascii=False, default=encode)+'\n')
            handle.flush()
            print('OCR_CASE', count, len(selected), row['id'], len(prediction['records']), 'error' in prediction, flush=True)
    save(out / 'summary.json', dict(status='complete', n=count, failures=failures, peak_gpu_allocated_bytes=0,
                                  scope='Separate CPU OCR; per-case failures retained as empty/error records.'))


def analyze():
    refs = read(FROZEN / 'references.json')
    labels = list(read(FROZEN / 'taxonomy.json'))
    summary = {}
    for stage in ('single_qwen25', 'single_qwen3', 'pipeline_noocr', 'pipeline_ocr'):
        path = ROOT / 'results' / stage
        if (path / 'summary.json').is_file():
            predictions = rows(path / 'predictions.jsonl')
            predictions = [dict(r, parsed=parse(r['raw'], labels)) for r in predictions]
            item = read(path / 'summary.json')
            item['scores'] = score(predictions, refs, labels)
            item['load_seconds'] = read(path / 'config.json')['load_seconds']
            if stage.startswith('pipeline_'):
                obs = read(ROOT / 'results/observe/summary.json')
                item['pipeline_peak_allocated_bytes'] = max(item['peak_allocated_bytes'], obs['peak_allocated_bytes'])
                item['pipeline_peak_reserved_bytes'] = max(item['peak_reserved_bytes'], obs['peak_reserved_bytes'])
                item['load_seconds'] += read(ROOT / 'results/observe/config.json')['load_seconds']
                if stage == 'pipeline_ocr':
                    item['load_seconds'] += read(ROOT / 'results/ocr/config.json')['load_seconds']
            summary[stage] = item
    save(ROOT / '261112_verified_summary_DR.json', dict(arms=summary, n=102, independent_field_validation=False,
         reference_status='AI-assisted v4 references and synthetic reports; conservative image-only contract, not safety truth.',
         same_evidence_for_all_arms=True, retrieval_model_effect_tested=False, additional_training=False))
    print('ANALYSIS_COMPLETE', list(summary), flush=True)


def self_test():
    valid = dict(hazard_labels=['burn'], assessment_state='candidate', objects=[], image_text='기름 온도 미확인', gas_leak_status='not_determinable')
    assert parse(json.dumps(valid), ['burn']) == valid
    assert parse(json.dumps(dict(valid, objects=[{'type': 'oven'}])), ['burn']) is None
    assert parse(json.dumps(dict(valid, hazard_labels=[])), ['burn']) is None
    assert parse(json.dumps(dict(valid, assessment_state='safe')), ['burn']) is None
    assert parse(json.dumps(dict(valid, extra='x')), ['burn']) is None
    assert parse('```json\n'+json.dumps(valid)+'\n```', ['burn']) == valid
    assert parse('explanation\n'+json.dumps(valid), ['burn']) is None
    assert UTIL.normalized('없습니다') != UTIL.normalized('있습니다')
    refs = [dict(id='a', labels=['burn'], assessment_state='candidate', image_text='기름 온도 미확인')]
    bad = [dict(id='a', group='rendered_report', parsed=None, total_seconds=1)]
    result = score(bad, refs, ['burn'])['rendered_report']
    assert result['omission_rate'] == result['cer'] == 1 and result['valid_schema'] == 0
    correct = [dict(id='a', group='rendered_report', parsed=valid, total_seconds=1)]
    result = score(correct, refs, ['burn'])['rendered_report']
    assert result['provisional_macro_f1'] == 1 and result['cer'] == result['omission_rate'] == 0
    refs = [dict(id='a', labels=[], assessment_state='insufficient_information', objects=['oven', 'sink'])]
    predicted = dict(valid, hazard_labels=[], assessment_state='insufficient_information', objects=['oven', 'refrigerator'])
    result = score([dict(id='a', group='objects', parsed=predicted, total_seconds=1)], refs, ['burn'])['objects']
    assert result['object_tp'] == result['object_fp'] == result['object_fn'] == 1
    assert result['object_micro_f1'] == .5
    print('BENCHMARK_SELF_TEST_PASS', flush=True)


def orchestrate():
    os.environ.update(TOKENIZERS_PARALLELISM='false', HF_HUB_DISABLE_PROGRESS_BARS='1',
                      PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    stages = ('single_qwen25', 'single_qwen3', 'observe', 'ocr', 'pipeline_noocr', 'pipeline_ocr', 'analyze')
    for stage in stages:
        python = '/home/elicer/safet-ocr-venv/bin/python' if stage == 'ocr' else sys.executable
        started = time.perf_counter()
        with (ROOT / (stage+'.log')).open('x', encoding='utf-8') as handle:
            result = subprocess.run([python, '-u', str(Path(__file__)), '--stage', stage], stdout=handle, stderr=subprocess.STDOUT)
        event = dict(stage=stage, exit_code=result.returncode, seconds=time.perf_counter()-started,
                     utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        with (ROOT / 'execution.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(event)+'\n')
        print('STAGE_RESULT', json.dumps(event), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.stage == 'ocr':
        run_ocr()
    elif args.stage == 'analyze':
        analyze()
    elif args.stage:
        try:
            run_model(args.stage)
        except Exception as error:
            save(ROOT / (args.stage+'_failure.json'), dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))
            raise
    else:
        self_test()
        orchestrate()
