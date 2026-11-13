"""Repair only the separate OCR environment after the original GPU run ends."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def latest(events):
    return {event['stage']: event for event in events}


def recover():
    assert ROOT == Path('/home/elicer/safet/experiments/261112_single_vs_pipeline_DR')
    marker = ROOT / 'recovery_started.json'
    assert not marker.exists(), 'Do not launch a duplicate recovery.'
    marker.write_text(json.dumps(dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))))
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        journal = ROOT / 'execution.jsonl'
        events = [json.loads(x) for x in journal.read_text().splitlines()] if journal.exists() else []
        if events and events[-1]['stage'] == 'analyze':
            break
        time.sleep(5)
    else:
        raise TimeoutError('Original sequential run did not reach analysis within 30 minutes.')
    assert latest(events)['pipeline_noocr']['exit_code'] == 0
    assert latest(events)['ocr']['exit_code'] != 0
    assert not (ROOT / 'results/ocr').exists(), 'Preserve any unexpected partial OCR outputs.'
    ocr_python = '/home/elicer/safet-ocr-venv/bin/python'
    with (ROOT / 'headless_opencv_repair.log').open('x') as log:
        subprocess.run([ocr_python, '-m', 'pip', 'uninstall', '-y', 'opencv-contrib-python'], stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run([ocr_python, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps',
                        'opencv-contrib-python-headless==4.10.0.84'], stdout=log, stderr=subprocess.STDOUT, check=True)
    os.environ.update(TOKENIZERS_PARALLELISM='false', HF_HUB_DISABLE_PROGRESS_BARS='1',
                      PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    for stage in ('ocr', 'pipeline_ocr', 'analyze'):
        if stage == 'analyze':
            shutil.copyfile(ROOT / '261112_verified_summary_DR.json', ROOT / '261112_verified_summary_initial_DR.json')
        python = ocr_python if stage == 'ocr' else sys.executable
        started = time.perf_counter()
        with (ROOT / (stage+'_recovery.log')).open('x') as log:
            result = subprocess.run([python, '-u', str(ROOT / '261112_benchmark_DR.py'), '--stage', stage], stdout=log, stderr=subprocess.STDOUT)
        event = dict(stage=stage, attempt=2, exit_code=result.returncode, seconds=time.perf_counter()-started,
                     utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        with journal.open('a') as handle:
            handle.write(json.dumps(event)+'\n')
        print('RECOVERY_STAGE', json.dumps(event), flush=True)
        assert result.returncode == 0, stage
    print('RECOVERY_COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        assert latest([dict(stage='ocr', exit_code=1), dict(stage='ocr', exit_code=0)])['ocr']['exit_code'] == 0
        print('RECOVERY_SELF_TEST_PASS')
    else:
        recover()
