"""탐지 전환 산출물 검증. 실행(작업 폴더 루트에서): python 261116_기기탐지_YOLO전환_DR/scripts/validate.py
jsonschema가 없으면 스키마 검사는 실패로 기록된다.
"""
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SRC = os.path.join(ROOT, '261115_기기마스터_인식평가셋_DR')
OUT = os.path.join(ROOT, '261116_기기탐지_YOLO전환_DR')
checks = []


def check(name, ok, detail=None):
    checks.append({'check': name, 'pass': bool(ok), 'detail': detail})


m = json.load(open(os.path.join(SRC, '261115_기기마스터_v1_DR.json'), encoding='utf-8'))
ev = json.load(open(os.path.join(SRC, '261115_기기인식_평가셋_v1_DR.json'), encoding='utf-8'))
ids = {e['equipment_id'] for e in m['equipment']}
mp = json.load(open(os.path.join(OUT, '261116_사전학습클래스_대응표_v1_DR.json'), encoding='utf-8'))
rows = mp['rows']
check('대응표: 마스터 42개와 1:1', {r['equipment_id'] for r in rows} == ids and len(rows) == len(ids), len(rows))
COCO_USED = {'oven', 'microwave', 'knife', 'scissors', 'sink', 'refrigerator', 'motorcycle'}
check('대응표: COCO 클래스명이 사용 목록 안에 있음', all(r['coco_class'] in COCO_USED | {None} for r in rows))
check('대응표: direct/partial은 COCO 클래스 있음, none은 없음',
      all((r['coco_class'] is None) == (r['coco_match'] == 'none') for r in rows))

coco = json.load(open(os.path.join(OUT, 'preannotations', '261116_박스초안_coco_v1_DR.json'), encoding='utf-8'))
cats = {c['id']: c['name'] for c in coco['categories']}
yes = [r['equipment_id'] for r in rows if r['detection_target'] == 'yes']
check('COCO 초안: 카테고리 = 탐지 대상(yes) 클래스', list(cats.values()) == yes, len(cats))
img_by_id = {i['id']: i for i in coco['images']}
check('COCO 초안: 이미지 34장, image_id_str = 평가셋 image_id',
      sorted(i['image_id_str'] for i in coco['images']) == sorted(i['image_id'] for i in ev['images']))
check('COCO 초안: 파일 경로가 존재', all(os.path.exists(os.path.join(ROOT, i['file_name'])) for i in coco['images']))
inb = all(0 <= a['bbox'][0] and 0 <= a['bbox'][1] and a['bbox'][0] + a['bbox'][2] <= img_by_id[a['image_id']]['width'] + 0.5
          and a['bbox'][1] + a['bbox'][3] <= img_by_id[a['image_id']]['height'] + 0.5 for a in coco['annotations'])
check('COCO 초안: 박스가 이미지 안에 있음', inb)
check('COCO 초안: 모든 주석 box_quality=grid_approx', all(a['box_quality'] == 'grid_approx' for a in coco['annotations']))
lab_map = {l['label_id']: l['equipment_id'] for i in ev['images'] for l in i['labels']}
check('COCO 초안: label_id가 평가셋 라벨과 같은 기기', all(lab_map.get(a['label_id']) == cats[a['category_id']] for a in coco['annotations']))
expected = sum(1 for i in ev['images'] for l in i['labels'] if l['equipment_id'] in yes)
check('COCO 초안: 주석 수 = 탐지 대상 라벨 수', len(coco['annotations']) == expected, [len(coco['annotations']), expected])

yd = os.path.join(OUT, 'preannotations', 'yolo_labels')
classes = open(os.path.join(yd, 'classes.txt'), encoding='utf-8').read().split()
check('YOLO 초안: classes.txt = COCO 카테고리 순서', classes == yes)
txts = sorted(f[:-4] for f in os.listdir(yd) if f.endswith('.txt') and f != 'classes.txt')
check('YOLO 초안: txt 파일명 = 평가셋 image_id(34개)', txts == sorted(i['image_id'] for i in ev['images']), len(txts))
nlines, bad = 0, []
for t in txts:
    for ln in open(os.path.join(yd, t + '.txt'), encoding='utf-8').read().split('\n'):
        if not ln:
            continue
        nlines += 1
        p = ln.split()
        if len(p) != 5 or not (0 <= int(p[0]) < len(classes)) or not all(0 <= float(x) <= 1 for x in p[1:]):
            bad.append((t, ln))
check('YOLO 초안: 줄 형식(class cx cy w h, 0-1)', not bad, bad[:3])
check('YOLO 초안: 줄 수 = COCO 주석 수', nlines == len(coco['annotations']), nlines)

try:
    import jsonschema
    sch = json.load(open(os.path.join(OUT, 'schemas', '261116_기기탐지_출력.schema.json'), encoding='utf-8'))
    exm = json.load(open(os.path.join(OUT, 'schemas', '261116_기기탐지_출력.example.json'), encoding='utf-8'))
    v = jsonschema.Draft202012Validator(sch)
    errs = [e.message for e in v.iter_errors(exm['model_output'])]
    check('스키마 v2: 예시 통과', not errs, errs)
    bad_ex = json.loads(json.dumps(exm['model_output']))
    bad_ex['detections'][0]['bbox'] = None
    check('스키마 v2: bbox null 거부', any(True for _ in v.iter_errors(bad_ex)))
    bad_ex2 = json.loads(json.dumps(exm['model_output']))
    del bad_ex2['detector']['weights_sha256']
    check('스키마 v2: 가중치 해시 누락 거부', any(True for _ in v.iter_errors(bad_ex2)))
    ex_ids = {d['equipment_id'] for d in exm['model_output']['detections'] if d['equipment_id']}
    check('스키마 v2: 예시 equipment_id가 마스터에 있음', ex_ids <= ids, sorted(ex_ids))
except ImportError:
    check('스키마 v2: jsonschema 미설치로 검증 못함', False)

check('v1 출력형식 문서 보존(존재)', os.path.exists(os.path.join(SRC, '261115_기기인식_출력형식_제외규칙_v1_DR.md')))
res = {'validated_date_kst': '2026-11-16', 'all_pass': all(c['pass'] for c in checks), 'checks': checks, 'mapping_summary': mp['summary']}
json.dump(res, open(os.path.join(OUT, '261116_검증결과_v1_DR.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('all_pass', res['all_pass'], len(checks), [c['check'] for c in checks if not c['pass']])
