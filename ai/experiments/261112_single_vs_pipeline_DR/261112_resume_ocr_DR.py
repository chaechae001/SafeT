"""Retain dependency validation while using matching headless OpenCV in the isolated OCR environment."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ocr_worker():
    import cv2
    import numpy as np
    import importlib.metadata as metadata
    headless_version = metadata.version('opencv-contrib-python-headless')
    assert headless_version == '4.10.0.84' and cv2.__version__ == '4.10.0'
    assert cv2.cvtColor(np.zeros((8, 8, 3), dtype=np.uint8), cv2.COLOR_BGR2GRAY).shape == (8, 8)
    original = metadata.version

    # shortcut: PaddleX 3.3 checks the GUI package name; remove when it accepts headless OpenCV directly.
    def version(name):
        return original('opencv-contrib-python-headless' if name == 'opencv-contrib-python' else name)

    metadata.version = version
    from paddlex.utils import deps
    from paddlex.inference.common.reader import image_reader
    assert hasattr(image_reader, 'cv2')
    assert deps.is_extra_available('ocr-core'), 'Do not skip other OCR dependency checks.'
    (ROOT / 'ocr_runtime_compatibility.json').write_text(json.dumps(dict(
        reason='PaddleX checks the GUI distribution name; the same-version headless distribution supplies cv2.',
        aliased_package='opencv-contrib-python', installed_package='opencv-contrib-python-headless',
        version=headless_version, cv2=cv2.__version__, ocr_core_dependency_check=True,
        native_color_conversion_check=True, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), indent=2))
    spec = importlib.util.spec_from_file_location('benchmark', ROOT / '261112_benchmark_DR.py')
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    benchmark.run_ocr()


def resume():
    assert ROOT == Path('/home/elicer/safet/experiments/261112_single_vs_pipeline_DR')
    output = ROOT / 'results/ocr'
    preserved = ROOT / 'results/ocr_failed_attempt4'
    assert output.resolve().parent == (ROOT / 'results').resolve()
    if output.exists():
        assert not preserved.exists() and not (output / 'predictions.jsonl').exists()
        output.rename(preserved)
    else:
        assert preserved.is_dir()
    os.environ.update(TOKENIZERS_PARALLELISM='false', HF_HUB_DISABLE_PROGRESS_BARS='1',
                      PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    for stage in ('ocr', 'pipeline_ocr', 'minimal_image_probe', 'analyze'):
        if stage == 'ocr':
            arguments = ['/home/elicer/safet-ocr-venv/bin/python', '-u', str(Path(__file__)), '--ocr-worker']
        elif stage == 'minimal_image_probe':
            arguments = [sys.executable, '-u', str(ROOT / '261112_minimal_image_probe_DR.py')]
        else:
            arguments = [sys.executable, '-u', str(ROOT / '261112_benchmark_DR.py'), '--stage', stage]
        if stage == 'analyze':
            initial = ROOT / '261112_verified_summary_initial_DR.json'
            if not initial.exists():
                shutil.copyfile(ROOT / '261112_verified_summary_DR.json', initial)
        started = time.perf_counter()
        with (ROOT / (stage+'_attempt5.log')).open('x') as handle:
            result = subprocess.run(arguments, stdout=handle, stderr=subprocess.STDOUT)
        event = dict(stage=stage, attempt=5, exit_code=result.returncode, seconds=time.perf_counter()-started,
                     utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        with (ROOT / 'execution.jsonl').open('a') as handle:
            handle.write(json.dumps(event)+'\n')
        print('RESUMED_STAGE', json.dumps(event), flush=True)
        assert result.returncode == 0, stage
        if stage == 'ocr':
            warmup = json.loads((ROOT / 'results/ocr/warmup.json').read_text())
            assert not warmup.get('error') and warmup['text'].strip(), 'OCR integration must read the text-card warmup.'
    print('OCR_PIPELINE_RECOVERY_COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ocr-worker', action='store_true')
    if parser.parse_args().ocr_worker:
        ocr_worker()
    else:
        resume()
