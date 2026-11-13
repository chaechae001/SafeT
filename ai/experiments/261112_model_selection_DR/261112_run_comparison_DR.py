"""Download pinned candidates, then run isolated probes and comparisons sequentially."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def main(check_only=False):
    models=json.loads((ROOT/'261112_candidate_models_DR.json').read_text(encoding='utf-8'))
    assert len(models)==3 and len({m['id'] for m in models})==3
    assert models[0]['revision']=='66285546d2b821cf421d4f5eb2576359d3770cd3'
    settings=json.loads((ROOT/'261112_execution_settings_DR.json').read_text(encoding='utf-8'))
    assert set(settings['prompts'])=={'objects','facility','ocr','empty_control','text_regression'}
    inputs=json.loads((ROOT/'frozen/inputs.json').read_text(encoding='utf-8'))
    references=json.loads((ROOT/'frozen/references.json').read_text(encoding='utf-8'))
    assert len(inputs)==74 and {r['id'] for r in inputs}=={r['id'] for r in references}
    assert all(not {'labels','objects','text','assessment_state'} & r.keys() for r in inputs)
    subprocess.run([sys.executable,str(ROOT/'261112_compare_models_DR.py'),'--self-test'],check=True)
    if check_only:
        print('RUNNER_PREFLIGHT_PASS',flush=True)
        return
    from huggingface_hub import snapshot_download
    journal=ROOT/'execution_journal.jsonl'
    if journal.exists():
        raise FileExistsError('Preserve existing execution; use a new run directory.')
    os.environ['TOKENIZERS_PARALLELISM']='false'
    os.environ['HF_HUB_DISABLE_PROGRESS_BARS']='1'
    def event(**row):
        row['utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        with journal.open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps(row,ensure_ascii=False),flush=True)
    available=[]
    for model in models:
        start=time.perf_counter();event(stage='download_start',model=model['id'],revision=model['revision'])
        try:
            path=snapshot_download(model['id'],revision=model['revision'],max_workers=2,
                allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken','LICENSE','README.md'])
            available.append(model)
            event(stage='download_complete',model=model['id'],seconds=time.perf_counter()-start,
                  snapshot=path,unique_files=sum(1 for p in Path(path).iterdir() if p.is_file()))
        except Exception as error:
            event(stage='download_failed',model=model['id'],error_type=type(error).__name__,message=str(error))
    # Download activity ends before latency measurements begin.
    for model in available:
        for precision in settings['precision_conditions']:
            arguments=[sys.executable,str(ROOT/'261112_compare_models_DR.py'),'--model',model['id'],'--precision',precision]
            tag=model['id'].split('/')[-1]+'_'+precision
            for stage,extra in [('probe',['--probe']),('comparison',[])]:
                start=time.perf_counter();event(stage=stage+'_start',model=model['id'],precision=precision)
                with (ROOT/(tag+'_'+stage+'.log')).open('x',encoding='utf-8') as handle:
                    result=subprocess.run(arguments+extra,stdout=handle,stderr=subprocess.STDOUT)
                event(stage=stage+'_finish',model=model['id'],precision=precision,exit_code=result.returncode,
                      seconds=time.perf_counter()-start,log=tag+'_'+stage+'.log')
                if result.returncode:
                    break
    event(stage='all_finished',summary_files=[str(p.relative_to(ROOT)) for p in (ROOT/'results').glob('*/summary.json')])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    main(args.self_test)
