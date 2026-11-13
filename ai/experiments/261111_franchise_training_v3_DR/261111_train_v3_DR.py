"""Matched-NF4 baseline/RAG/QLoRA experiment with provisional references."""
import argparse
import collections
import contextlib
import hashlib
import json
import math
import random
import re
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
STATES={'candidate','insufficient_information','out_of_scope'}
TOPICS={
 'slip':r'�ٴ�|���|����|����|�̲�|��ֹ�',
 'cut':r'Į|�����̼�|����|����|ȥ�ձ�',
 'burn':r'�߰�|Ƣ����|����|����|�ܿ�|�⸧�µ�|Ƣ���.*û��',
 'fire':r'�Ҳ�|ȭ��|����|�⸧���|�⸧��|�ĵ�����|�ⱸ',
 'gas':r'����|ȣ��|���|�����',
 'electric':r'����|�÷���|��Ƽ��|�Ǻ�',
 'chemical':r'��ô��|��ô��|����|ȭ��',
 'ergonomic':r'����|������|�㸮|�ո�|�ݺ�|����|�ڽ�',
 'falling':r'����|��|����|����|����|���.*��',
 'respiratory':r'�ĵ�|ȯ��|����|��|��ħ|����|������',
}

def read_rows(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]

def save(name,value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def retrieve(query,docs,limit=3):
    query=re.sub(r'\s+','',query)
    topics={k for k,v in TOPICS.items() if re.search(v,query)}
    eligible=[d for d in docs if topics.intersection(d['hazard_labels']) and any(t in query for t in d['applicable_terms'])]
    def grams(text):
        text=re.sub(r'\s+','',text)
        return collections.Counter(text[i:i+2] for i in range(len(text)-1))
    vectors=[grams(d['text']) for d in docs]
    df=collections.Counter(t for v in vectors for t in v)
    idf={t:math.log(1+(len(docs)-n+0.5)/(n+0.5)) for t,n in df.items()}
    q=grams(query)
    ranked=[]
    for d in eligible:
        v=grams(d['text'])
        numerator=sum(n*v[t]*idf.get(t,0)**2 for t,n in q.items())
        norm=math.sqrt(sum((n*idf.get(t,0))**2 for t,n in q.items())*sum((n*idf.get(t,0))**2 for t,n in v.items()))
        ranked.append((numerator/max(norm,1e-12),d))
    return [dict(d,retrieval_score=s) for s,d in sorted(ranked,key=lambda x:(-x[0],x[1]['id']))[:limit]]

def parse(raw,labels):
    match=re.search(r'\{.*\}',raw,re.S)
    try:
        value=json.loads(match.group()) if match else None
    except json.JSONDecodeError:
        return None
    if not isinstance(value,dict) or set(value)!={'hazard_labels','assessment_state'} or not isinstance(value.get('hazard_labels'),list): return None
    if not all(isinstance(x,str) and x in labels for x in value['hazard_labels']): return None
    state=value.get('assessment_state')
    if not isinstance(state,str) or state not in STATES: return None
    if (state=='candidate') != bool(value['hazard_labels']): return None
    return dict(hazard_labels=sorted(set(value['hazard_labels'])),assessment_state=state)

def metrics(rows,references,labels):
    refs={r['id']:r for r in references}
    assert len(rows)==len(refs) and {r['id'] for r in rows}==set(refs)
    assert all(r['review_status']=='ai_source_checked' and not r['human_approved'] for r in references)
    per_label={}; omitted=positive=0
    for label in labels:
        tp=fp=fn=0
        for row in rows:
            gold=label in refs[row['id']]['labels']
            guess=row['parsed'] is not None and label in row['parsed']['hazard_labels']
            tp+=int(gold and guess);fp+=int(not gold and guess);fn+=int(gold and not guess)
        per_label[label]=dict(tp=tp,fp=fp,fn=fn,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
        omitted+=fn;positive+=tp+fn
    return dict(provisional_macro_f1=sum(v['f1'] for v in per_label.values())/len(labels),
        provisional_hazard_omission_rate=omitted/positive if positive else None,
        provisional_state_accuracy=sum(bool(r['parsed']) and r['parsed']['assessment_state']==refs[r['id']]['assessment_state'] for r in rows)/len(rows),
        valid_schema=sum(r['parsed'] is not None for r in rows),n=len(rows),per_label=per_label,
        reference_status='AI-assisted provisional references; not independent safety validation')

def prompt(situation,taxonomy,evidence=()):
    return [dict(role='system',content='ġŲ �������� ���� �Ű��� �з��Ѵ�. JSON ��ü �ϳ��� ����Ѵ�. �ʼ� Ű�� hazard_labels�� assessment_state��. hazard_labels�� ���� ID�� �迭�̴�. ���� ��Ŀ���� �ĺ��� ������ assessment_state�� candidate��. ������ �����ϸ� insufficient_information�̸� ���� �� �迭�̴�. ������ ��ȸ�� ���� ���� ��û�̸� out_of_scope�̸� ���� �� �迭�̴�. �̴� ���� ���� ������ �ƴϴ�. ���� ������ ��� �����Ѵ�. �߰ſ� ����� ȭ�� �����̸� ���ᰡ�� ����� �ٸ���. ���� ���ϴ� �̲������� �ٸ���. ������� ȯ��� respiratory��. �ٰŴ� �ǰ��ڷ��̸� �� �ؼ��� ���� �µ��� ���� �󵵸� Ȯ������ �ʴ´�.'),
        dict(role='user',content=json.dumps(dict(situation=situation,allowed_labels=taxonomy,
            evidence=[dict(id=d['id'],text=d['text']) for d in evidence]),ensure_ascii=False))]

def self_test():
    docs=[dict(id='electric',hazard_labels=['electric'],text='���� ��� ������ �÷���',applicable_terms=['����'],controls=[]),
          dict(id='machine',hazard_labels=['cut'],text='��� ���� ȥ�ձ�',applicable_terms=['ȥ�ձ�'],controls=[])]
    assert [x['id'] for x in retrieve('���� ��⿡�� Ÿ�� ����',docs)]==['electric']
    assert retrieve('�۾� ���� ����',docs)==[]
    assert parse('{"hazard_labels":[],"assessment_state":"safe"}',['electric']) is None
    assert parse('{"hazard_labels":[],"assessment_state":"candidate"}',['electric']) is None
    assert parse('{"hazard_labels":[],"assessment_state":"out_of_scope","extra":1}',['electric']) is None
    parsed=dict(hazard_labels=['electric'],assessment_state='candidate')
    ref=[dict(id='a',labels=['electric'],assessment_state='candidate',review_status='ai_source_checked',human_approved=False)]
    assert metrics([dict(id='a',parsed=parsed)],ref,['electric'])['provisional_macro_f1']==1
    assert metrics([dict(id='a',parsed=None)],ref,['electric'])['provisional_hazard_omission_rate']==1
    print('V3_SELF_TEST_PASS',flush=True)

def run():
    import torch
    import peft
    import bitsandbytes
    from transformers import AutoTokenizer,BitsAndBytesConfig,Qwen2_5_VLForConditionalGeneration
    from peft import LoraConfig,get_peft_model,prepare_model_for_kbit_training
    protocol=json.loads((ROOT/'261111_protocol_DR.json').read_text(encoding='utf-8'))
    taxonomy=json.loads((ROOT/'261111_taxonomy_DR.json').read_text(encoding='utf-8'))
    docs=read_rows(ROOT/'261111_evidence_DR.jsonl')
    train=read_rows(ROOT/'references/train.jsonl');dev=read_rows(ROOT/'references/development.jsonl')
    # Final test references are read only after training and checkpoint selection.
    out=ROOT/'results'
    out.mkdir(exist_ok=True)
    if (out/'261111_training_history_DR.json').exists(): raise FileExistsError('Preserve prior training run.')
    random.seed(42);torch.manual_seed(42);torch.cuda.manual_seed_all(42)
    tokenizer=AutoTokenizer.from_pretrained(protocol['model'],revision=protocol['revision'],local_files_only=True)
    if tokenizer.pad_token_id is None: tokenizer.pad_token=tokenizer.eos_token
    quant=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16)
    model=Qwen2_5_VLForConditionalGeneration.from_pretrained(protocol['model'],revision=protocol['revision'],
        local_files_only=True,quantization_config=quant,device_map={'':0},torch_dtype=torch.bfloat16,attn_implementation='sdpa')
    model=prepare_model_for_kbit_training(model,use_gradient_checkpointing=True)
    model=get_peft_model(model,LoraConfig(r=8,lora_alpha=16,lora_dropout=0.05,target_modules=['q_proj','v_proj'],bias='none',task_type='CAUSAL_LM'))
    params=[(n,p) for n,p in model.named_parameters() if p.requires_grad]
    assert params and all('lora_' in n and 'visual' not in n for n,p in params)
    config=dict(**protocol,peft=peft.__version__,bitsandbytes=bitsandbytes.__version__,torch=torch.__version__,
        r=8,alpha=16,learning_rate=0.0002,epochs=3,gradient_accumulation=4,max_sequence_length=768,
        trainable_parameters=sum(p.numel() for n,p in params),quantization='NF4 double quantization, bf16 compute',
        comparison='Same NF4 base with adapter disabled for baseline/RAG; selected adapter enabled for QLoRA',
        generation=dict(do_sample=False,max_new_tokens=96),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    save('results/261111_config_DR.json',config)
    def encode(row):
        messages=prompt(row['situation'],taxonomy)
        prefix=tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True)
        answer=json.dumps(dict(hazard_labels=row['labels'],assessment_state=row['assessment_state']),ensure_ascii=False)
        full=tokenizer.apply_chat_template(messages+[dict(role='assistant',content=answer)],tokenize=True,add_generation_prompt=False)
        assert full[:len(prefix)]==prefix and len(full)<=768
        labels=[-100]*len(prefix)+full[len(prefix):]
        assert any(x!=-100 for x in labels)
        return {k:torch.tensor([v],device='cuda') for k,v in dict(input_ids=full,attention_mask=[1]*len(full),labels=labels).items()}
    train_batches=[encode(r) for r in train];dev_batches=[encode(r) for r in dev]
    optimizer=torch.optim.AdamW([p for n,p in params],lr=0.0002)
    model.config.use_cache=False
    history=[];best=float('inf');started=time.time();steps=0
    for epoch in range(3):
        model.train();optimizer.zero_grad(set_to_none=True)
        order=list(range(len(train_batches)));random.Random(42+epoch).shuffle(order)
        total=0
        for i,index in enumerate(order):
            loss=model(**train_batches[index]).loss
            assert torch.isfinite(loss).item()
            total+=loss.item();(loss/4).backward()
            if (i+1)%4==0 or i+1==len(order):
                torch.nn.utils.clip_grad_norm_([p for n,p in params],1.0);optimizer.step();optimizer.zero_grad(set_to_none=True);steps+=1
            if (i+1)%12==0: print('TRAIN',epoch+1,i+1,len(order),'loss',loss.item(),flush=True)
        model.eval()
        with torch.no_grad(): validation=sum(model(**b).loss.item() for b in dev_batches)/len(dev_batches)
        row=dict(epoch=epoch+1,train_loss=total/len(order),development_loss=validation,optimizer_steps=steps,elapsed_seconds=time.time()-started)
        history.append(row);save('results/261111_training_history_DR.json',history);print(row,flush=True)
        if validation<best:
            best=validation;model.save_pretrained(ROOT/'adapter');tokenizer.save_pretrained(ROOT/'adapter')
    del train_batches,dev_batches,optimizer
    torch.cuda.empty_cache();model.gradient_checkpointing_disable();model.config.use_cache=True
    model.load_adapter(str(ROOT/'adapter'),adapter_name='selected');model.set_adapter('selected');model.eval()
    tests=read_rows(ROOT/'references/test.jsonl')
    summaries={}
    for arm in ('baseline_nf4','rag_nf4','qlora_nf4'):
        rows=[]
        for row in tests:
            evidence=retrieve(row['situation'],docs) if arm=='rag_nf4' else []
            messages=prompt(row['situation'],taxonomy,evidence)
            text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
            batch=tokenizer(text,return_tensors='pt').to('cuda')
            manager=model.disable_adapter() if arm!='qlora_nf4' else contextlib.nullcontext()
            with manager,torch.inference_mode(): generated=model.generate(**batch,do_sample=False,max_new_tokens=96)
            raw=tokenizer.decode(generated[0,batch.input_ids.shape[1]:],skip_special_tokens=True)
            parsed=parse(raw,taxonomy)
            # Return source text only; ungrounded free-form controls are not released.
            controls=[dict(text=c,source_id=d['id']) for d in evidence for c in d['controls']
                if parsed and set(parsed['hazard_labels']).intersection(d['hazard_labels'])][:2]
            result=dict(id=row['id'],arm=arm,raw=raw,parsed=parsed,retrieved_ids=[d['id'] for d in evidence],
                candidate_controls=controls,review_required=True,final_risk_level='����')
            rows.append(result)
            with (out/'261111_predictions_DR.jsonl').open('a',encoding='utf-8') as h: h.write(json.dumps(result,ensure_ascii=False)+'\n')
            print('TEST',arm,row['id'],parsed,flush=True)
        summaries[arm]=metrics(rows,tests,list(taxonomy))
    save('results/261111_summary_DR.json',dict(complete=True,experiments=summaries,best_development_loss=best,
        train_seconds=history[-1]['elapsed_seconds'],peak_gpu_allocated_bytes=torch.cuda.max_memory_allocated(),
        reference_status=protocol['reference_status'],independent_validation=False,
        automatic_safety_approval=False,service_integration='on hold by user'))
    print('V3_EXPERIMENT_COMPLETE',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    self_test()
    if not args.self_test: run()
