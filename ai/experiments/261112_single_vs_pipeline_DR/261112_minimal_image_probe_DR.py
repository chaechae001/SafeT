"""Check whether the failed compound-prompt baseline can read two images with a minimal OCR prompt."""
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent


def run():
    source = ROOT.parent / '261112_model_selection_DR'
    spec = importlib.util.spec_from_file_location('original_model_diagnostic', source / '261112_compare_models_DR.py')
    diagnostic = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diagnostic)
    probe = ROOT / 'minimal_image_probe'
    (probe / 'frozen').mkdir(parents=True, exist_ok=False)
    inputs = {r['id']: r for r in json.loads((ROOT / 'frozen/inputs.json').read_text())}
    refs = {r['id']: r for r in json.loads((ROOT / 'frozen/references.json').read_text())}
    selected, references = [], []
    for key in ('rendered_report_C01', 'rendered_report_C30'):
        item = inputs[key]
        target = probe / 'frozen' / Path(item['image']).name
        shutil.copyfile(ROOT / 'frozen' / item['image'], target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == item['image_sha256']
        selected.append(dict(id=key, task='ocr', image=target.name, image_sha256=item['image_sha256']))
        references.append(dict(id=key, text=refs[key]['image_text']))
    diagnostic.save(probe / 'frozen/inputs.json', selected)
    diagnostic.save(probe / 'frozen/references.json', references)
    diagnostic.save(probe / 'frozen/taxonomy.json', {})
    diagnostic.save(probe / 'frozen/hashes.json', {str(p.relative_to(probe / 'frozen')): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (probe / 'frozen').iterdir() if p.is_file()})
    shutil.copyfile(source / '261112_candidate_models_DR.json', probe / '261112_candidate_models_DR.json')
    diagnostic.save(probe / '261112_execution_settings_DR.json', dict(min_pixels=3136, max_pixels=262144, max_new_tokens=256,
                    prompts=dict(ocr='이미지에 인쇄된 한국어 문장을 그대로 읽으세요. JSON 하나만 출력하세요. 형식: {"text":"인식한 원문"}')))
    assert len(selected) == 2 and {r['id'] for r in selected} == {r['id'] for r in references}
    diagnostic.ROOT = probe
    diagnostic.run(SimpleNamespace(model='Qwen/Qwen3-VL-4B-Instruct', precision='nf4', probe=False))


if __name__ == '__main__':
    run()
