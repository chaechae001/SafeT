"""탐지 전환용 로컬 산출물 생성. 패키지 설치·가중치 다운로드·모델 실행 없음.

실행(작업 폴더 루트에서): python 261116_기기탐지_YOLO전환_DR/scripts/build_detection_assets.py
입력(읽기만): 261115_기기마스터_인식평가셋_DR/261115_기기마스터_v1_DR.json, 261115_기기인식_평가셋_v1_DR.json
출력:
  261116_사전학습클래스_대응표_v1_DR.csv / .json
  preannotations/261116_박스초안_coco_v1_DR.json   (COCO 형식, 격자 근사 박스)
  preannotations/yolo_labels/<image_id>.txt, classes.txt (YOLO 형식, 같은 근사 박스)
"""
import collections
import csv
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SRC = os.path.join(ROOT, '261115_기기마스터_인식평가셋_DR')
OUT = os.path.join(ROOT, '261116_기기탐지_YOLO전환_DR')
PRE = os.path.join(OUT, 'preannotations')

# COCO 2017 80개 클래스 중 기기 마스터와 관련 있는 것만 적는다(이름은 COCO 표기).
# match: direct(같은 대상) / partial(일부만 겹침·혼동 가능) / none
# target: 탐지 대상 여부. yes / hold(보류) / no
# prompt: 오픈 어휘 탐지용 영문 프롬프트 초안(검증 전)
MAP = {
    'EQ_FRYER': (None, 'none', 'yes', 'commercial deep fryer', '라벨 20개로 가장 많음. 사전학습 클래스 없음'),
    'EQ_GAS_RANGE': ('oven', 'partial', 'yes', 'gas stove burner', 'COCO oven 주석에 레인지·쿡탑이 섞여 있다고 알려져 있으나 확인 필요. oven과 구분 불가'),
    'EQ_OVEN': ('oven', 'direct', 'yes', 'commercial oven', ''),
    'EQ_GRILL': ('oven', 'partial', 'yes', 'salamander broiler', '오븐과 혼동 가능'),
    'EQ_MICROWAVE': ('microwave', 'direct', 'yes', 'microwave oven', ''),
    'EQ_RICE_COOKER': (None, 'none', 'yes', 'rice cooker', ''),
    'EQ_SOUP_KETTLE': (None, 'none', 'yes', 'large stock pot kettle', ''),
    'EQ_GRIDDLE': (None, 'none', 'yes', 'flat top griddle', ''),
    'EQ_STEAMER': (None, 'none', 'yes', 'food steamer', ''),
    'EQ_ODEN_WARMER': (None, 'none', 'hold', 'fish cake warmer pot', '제안 항목'),
    'EQ_PORTABLE_BURNER': (None, 'none', 'yes', 'portable gas stove', ''),
    'EQ_COOKING_ROBOT': (None, 'none', 'yes', 'robotic arm', ''),
    'EQ_KNIFE_BOARD': ('knife', 'partial', 'yes', 'kitchen knife; cutting board', 'COCO는 칼만 있음. 도마 없음'),
    'EQ_SCISSORS': ('scissors', 'direct', 'yes', 'scissors', '작은 물체. 벽에 걸린 가위는 검출 어려울 수 있음'),
    'EQ_VEG_CUTTER': (None, 'none', 'yes', 'vegetable cutter machine; mandoline slicer', ''),
    'EQ_MEAT_SLICER': (None, 'none', 'yes', 'meat slicer', ''),
    'EQ_MIXER': (None, 'none', 'yes', 'blender; food mixer', ''),
    'EQ_DOUGH_MIXER': (None, 'none', 'yes', 'dough mixer', ''),
    'EQ_NOODLE_MACHINE': (None, 'none', 'yes', 'noodle making machine', ''),
    'EQ_RICE_WASHER': (None, 'none', 'hold', 'rice washing machine', '모양 정보 부족'),
    'EQ_MARINATOR': (None, 'none', 'hold', 'vacuum tumbler marinator', '화면 예시에서만 나온 제안 항목'),
    'EQ_COFFEE_MACHINE': (None, 'none', 'yes', 'espresso machine', ''),
    'EQ_COFFEE_GRINDER': (None, 'none', 'yes', 'coffee grinder', ''),
    'EQ_ICE_MAKER': (None, 'none', 'yes', 'ice machine', ''),
    'EQ_ICE_CRUSHER': (None, 'none', 'yes', 'ice shaver machine', ''),
    'EQ_WATER_HEATER': (None, 'none', 'yes', 'hot water dispenser', ''),
    'EQ_BEER_DISPENSER': (None, 'none', 'yes', 'beer tap dispenser', ''),
    'EQ_DISHWASHER': (None, 'none', 'yes', 'commercial dishwasher', ''),
    'EQ_STERILIZER': (None, 'none', 'yes', 'dish sterilizer cabinet', ''),
    'EQ_SINK': ('sink', 'direct', 'yes', 'kitchen sink', '업소용 스테인리스 세척대와 가정용 싱크 차이 확인 필요'),
    'EQ_EXHAUST_HOOD': (None, 'none', 'yes', 'kitchen exhaust hood', ''),
    'EQ_WASTE_OIL_CONTAINER': (None, 'none', 'hold', 'oil drain container', '튀김기 하부에 가려짐'),
    'EQ_REFRIGERATOR': ('refrigerator', 'direct', 'yes', 'commercial refrigerator; chest freezer', '뚜껑형 냉장고는 COCO 예시와 모양이 다름'),
    'EQ_WALKIN_COOLER': (None, 'none', 'hold', 'walk-in cooler door', '문만 보여 일반 냉장고와 구분 어려움'),
    'EQ_DISPLAY_COOLER': ('refrigerator', 'partial', 'yes', 'beverage display cooler', 'COCO에서는 냉장고와 같은 클래스. 구분하려면 추가 학습 필요'),
    'EQ_CART': (None, 'none', 'yes', 'utility cart trolley', ''),
    'EQ_SHELF': (None, 'none', 'yes', 'metal shelf', '범위가 넓어 박스 기준 정의 필요'),
    'EQ_LADDER': (None, 'none', 'yes', 'step ladder', ''),
    'EQ_DUMBWAITER': (None, 'none', 'hold', 'dumbwaiter', ''),
    'EQ_MOTORCYCLE': ('motorcycle', 'direct', 'no', 'motorcycle', '주방·홀 사진 인식 대상 아님'),
    'EQ_GAS_CYLINDER': (None, 'none', 'yes', 'LPG gas cylinder; butane gas can', 'COCO bottle과 오탐 가능'),
    'EQ_ELECTRIC_PANEL': (None, 'none', 'hold', 'power strip; electrical panel', '작은 물체. 박스 기준 정의 필요'),
}


def route(coco, match, target):
    if target == 'no':
        return '탐지 대상 아님'
    if match == 'direct':
        return 'A: 사전학습+매핑으로 먼저 시험'
    if match == 'partial':
        return 'B/C: 사전학습은 혼동. 오픈 어휘 시험 후 필요 시 파인튜닝'
    return 'B→C: 오픈 어휘 시험, 부족하면 파인튜닝(박스 라벨 필요)'


def main():
    m = json.load(open(os.path.join(SRC, '261115_기기마스터_v1_DR.json'), encoding='utf-8'))
    ev = json.load(open(os.path.join(SRC, '261115_기기인식_평가셋_v1_DR.json'), encoding='utf-8'))
    ids = [e['equipment_id'] for e in m['equipment']]
    assert set(ids) == set(MAP), set(ids) ^ set(MAP)
    names = {e['equipment_id']: e['standard_name'] for e in m['equipment']}
    lab = collections.Counter(l['equipment_id'] for i in ev['images'] for l in i['labels'])
    clear = collections.Counter(l['equipment_id'] for i in ev['images'] for l in i['labels'] if l['visibility'] == 'clear')
    rows = []
    for eid in ids:
        coco, match, target, prompt, note = MAP[eid]
        rows.append({'equipment_id': eid, 'standard_name': names[eid], 'coco_class': coco, 'coco_match': match,
                     'detection_target': target, 'route': route(coco, match, target), 'open_vocab_prompt_draft': prompt,
                     'evalset_labels': lab.get(eid, 0), 'evalset_clear_labels': clear.get(eid, 0), 'note': note})
    with open(os.path.join(OUT, '261116_사전학습클래스_대응표_v1_DR.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {
        'coco_match': dict(collections.Counter(r['coco_match'] for r in rows)),
        'detection_target': dict(collections.Counter(r['detection_target'] for r in rows)),
        'evalset_labels_coverable_by_coco_direct': sum(r['evalset_labels'] for r in rows if r['coco_match'] == 'direct'),
        'evalset_labels_coco_partial': sum(r['evalset_labels'] for r in rows if r['coco_match'] == 'partial'),
        'evalset_labels_total': sum(lab.values()),
    }
    json.dump({'version': 'v1-draft', 'created_date_kst': '2026-11-16', 'master_version': m['version'],
               'coco_reference': 'COCO 2017 detection 80 classes(기억에 근거한 클래스명. 실행 전 사용할 가중치의 names로 재확인)',
               'status': '초안. 모델 실행으로 확인하지 않음', 'summary': summary, 'rows': rows},
              open(os.path.join(OUT, '261116_사전학습클래스_대응표_v1_DR.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    # 박스 초안: 탐지 대상(yes)만, 격자 근사 박스
    det_ids = [r['equipment_id'] for r in rows if r['detection_target'] == 'yes']
    cat_id = {eid: i for i, eid in enumerate(det_ids)}
    os.makedirs(os.path.join(PRE, 'yolo_labels'), exist_ok=True)
    coco = {'info': {'description': 'Safe-T 기기 박스 초안(격자 근사). 학습·mAP 평가에 쓰지 말 것. 라벨 도구에서 사람이 고칠 사전 주석.',
                     'version': 'v1-draft', 'date_created': '2026-11-16', 'label_status': 'AI 보조 라벨, 사람 검수 전'},
            'images': [], 'annotations': [],
            'categories': [{'id': i, 'name': eid, 'supercategory': 'equipment'} for eid, i in cat_id.items()]}
    ann_id, skipped = 1, collections.Counter()
    for n, img in enumerate(ev['images'], 1):
        W, H = img['display_width'], img['display_height']
        coco['images'].append({'id': n, 'file_name': img['file'], 'width': W, 'height': H, 'image_id_str': img['image_id']})
        lines = []
        for l in img['labels']:
            if l['equipment_id'] not in cat_id:
                skipped[l['equipment_id']] += 1
                continue
            x0, y0, x1, y1 = l['bbox_norm_from_grid']
            coco['annotations'].append({'id': ann_id, 'image_id': n, 'category_id': cat_id[l['equipment_id']],
                                        'bbox': [round(x0 * W, 1), round(y0 * H, 1), round((x1 - x0) * W, 1), round((y1 - y0) * H, 1)],
                                        'area': round((x1 - x0) * W * (y1 - y0) * H, 1), 'iscrowd': 0,
                                        'label_id': l['label_id'], 'visibility': l['visibility'], 'box_quality': 'grid_approx'})
            ann_id += 1
            lines.append(f"{cat_id[l['equipment_id']]} {(x0 + x1) / 2:.4f} {(y0 + y1) / 2:.4f} {x1 - x0:.4f} {y1 - y0:.4f}")
        with open(os.path.join(PRE, 'yolo_labels', img['image_id'] + '.txt'), 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(lines) + ('\n' if lines else ''))
    with open(os.path.join(PRE, 'yolo_labels', 'classes.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(det_ids) + '\n')
    json.dump(coco, open(os.path.join(PRE, '261116_박스초안_coco_v1_DR.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False))
    print('det classes', len(det_ids), 'annotations', ann_id - 1, 'skipped', dict(skipped))


if __name__ == '__main__':
    main()
