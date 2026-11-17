"""산출물 검증. 실행(작업 폴더 루트에서): python 261115_기기마스터_인식평가셋_DR/scripts/validate.py
출력: 261115_검증결과_v1_DR.json
"""
import collections
import hashlib
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
OUT = os.path.join(ROOT, '261115_기기마스터_인식평가셋_DR')
checks, problems = [], []


def check(name, ok, detail=None):
    checks.append({'check': name, 'pass': bool(ok), 'detail': detail})
    if not ok:
        problems.append(name)


def norm(s):
    return re.sub(r'\s+', ' ', s.strip()).lower()


m = json.load(open(os.path.join(OUT, '261115_기기마스터_v1_DR.json'), encoding='utf-8'))
ids = [e['equipment_id'] for e in m['equipment']]
check('master: equipment_id 중복 없음', len(ids) == len(set(ids)), len(ids))
check('master: ID 형식 ^EQ_[A-Z0-9_]+$', all(re.fullmatch(r'EQ_[A-Z0-9_]+', i) for i in ids))
srcs = set(m['sources'])
bad_src = [(e['equipment_id'], r['src']) for e in m['equipment'] for r in e['sources'] + [x for h in e['related_hazards'] for x in h['refs']] if r['src'] not in srcs]
check('master: 출처 키가 sources 표에 있음', not bad_src, bad_src)
bad_hz = [(e['equipment_id'], h['code']) for e in m['equipment'] for h in e['related_hazards'] if h['code'] not in m['hazard_codes']]
check('master: 위험요인 코드가 정의됨', not bad_hz, bad_hz)
bad_basis = []
for e in m['equipment']:
    for ind in e['industries']:
        if ind['basis_type'] == '업종근거' and not any(r['src'] == 'D8' for r in e['sources']):
            bad_basis.append((e['equipment_id'], ind['industry']))
        if ind['basis_type'] == '공통근거' and e['evidence_status'] == '제안':
            bad_basis.append((e['equipment_id'], ind['industry'], '공통근거인데 문서 출처 없음'))
check('master: 업종근거는 D8 출처, 공통근거는 문서 출처 보유', not bad_basis, bad_basis)
listed = {x['equipment_id'] for v in m['industry_lists'].values() for x in v['items']}
check('master: 업종 목록 항목이 모두 마스터에 있음', listed <= set(ids), sorted(listed - set(ids)))
check('master: 모든 항목이 1개 이상 업종 목록에 있음', set(ids) <= listed, sorted(set(ids) - listed))
check('master: 업종 5개(치킨·분식·카페·한식·기타)', set(m['industry_lists']) == {'chicken', 'bunsik', 'cafe', 'korean', 'other'})
# 이름 충돌: R6 직접 추가 이름 대조에 영향
names = collections.defaultdict(set)
for e in m['equipment']:
    for n in [e['standard_name']] + e['standard_name'].split('·') + e['synonyms']:
        names[norm(n)].add(e['equipment_id'])
collisions = {k: sorted(v) for k, v in names.items() if len(v) > 1}
check('master: 이름·동의어가 여러 항목에 겹치지 않음(R6 대조용)', not collisions, collisions)

ev = json.load(open(os.path.join(OUT, '261115_기기인식_평가셋_v1_DR.json'), encoding='utf-8'))
photo_dir = os.path.join(ROOT, '실제사진')
files = sorted(f for f in os.listdir(photo_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg')))
stems = {os.path.splitext(f)[0] for f in files}
img_ids = [i['image_id'] for i in ev['images']]
check('evalset: image_id 중복 없음', len(img_ids) == len(set(img_ids)), len(img_ids))
check('evalset: image_id 집합 = 실제사진 이미지 파일명 집합', set(img_ids) == stems, sorted(set(img_ids) ^ stems))
check('evalset: image_id = file 파일명(확장자 제외)', all(os.path.splitext(os.path.basename(i['file']))[0] == i['image_id'] for i in ev['images']))
hash_bad = []
for i in ev['images']:
    p = os.path.join(ROOT, i['file'])
    if not os.path.exists(p) or hashlib.sha256(open(p, 'rb').read()).hexdigest() != i['sha256']:
        hash_bad.append(i['image_id'])
check('evalset: 파일 존재·sha256 일치', not hash_bad, hash_bad)
lab_ids = [l['label_id'] for i in ev['images'] for l in i['labels']]
check('evalset: label_id 중복 없음', len(lab_ids) == len(set(lab_ids)), len(lab_ids))
check('evalset: label_id 접두어 = image_id', all(l['label_id'].split('#')[0] == i['image_id'] for i in ev['images'] for l in i['labels']))
bad_eq = [(i['image_id'], l['equipment_id']) for i in ev['images'] for l in i['labels'] if l['equipment_id'] not in ids]
bad_eq += [(i['image_id'], c['candidate_equipment_id']) for i in ev['images'] for c in i['uncertain_candidates'] if c['candidate_equipment_id'] and c['candidate_equipment_id'] not in ids]
check('evalset: 라벨·후보 equipment_id가 마스터에 있음', not bad_eq, bad_eq)
grid_ok = all(re.fullmatch(r'[1-3][ABC]', g) for i in ev['images'] for l in i['labels'] for g in l['region_grid'])
check('evalset: 격자 칸 형식 [1-3][ABC]', grid_ok)
dup_eq = [(i['image_id'], k) for i in ev['images'] for k, c in collections.Counter(l['equipment_id'] for l in i['labels']).items() if c > 1]
check('evalset: 한 이미지에 같은 기기 라벨 중복 없음', not dup_eq, dup_eq)
check('evalset: 모든 이미지 label_status = AI 보조 라벨, 사람 검수 전', all(i['label_status'] == 'AI 보조 라벨, 사람 검수 전' for i in ev['images']))
check('evalset: 모든 이미지에 공유 권한 확인 필요 표시', all(i['rights']['sharing_status'] == '공유 권한 미확인' for i in ev['images']))
# 원본 사진 보존: 기존 이동파일목록 sha256과 비교
mv = json.load(open(os.path.join(photo_dir, '261113_공개주방_이동파일목록_DR.json'), encoding='utf-8'))
mv_hash = {os.path.splitext(os.path.basename(x['file'].replace('\\', '/')))[0]: x['sha256'] for x in mv}
ev_hash = {i['image_id']: i['sha256'] for i in ev['images']}
mism = [k for k, v in mv_hash.items() if ev_hash.get(k) != v]
check('원본 보존: 261113 이동파일목록 16장의 sha256 변화 없음', not mism, {'compared': len(mv_hash), 'mismatch': mism})

# 예시 응답 스키마 검증
try:
    import jsonschema
    sch = json.load(open(os.path.join(OUT, 'schemas', '261115_기기인식_출력.schema.json'), encoding='utf-8'))
    exm = json.load(open(os.path.join(OUT, 'schemas', '261115_기기인식_출력.example.json'), encoding='utf-8'))
    errs = [e.message for e in jsonschema.Draft202012Validator(sch).iter_errors(exm['model_output'])]
    check('schema: 예시 model_output이 스키마를 통과', not errs, errs)
    neg = dict(exm['model_output'], status='weird')
    check('schema: 잘못된 status 거부', any(True for _ in jsonschema.Draft202012Validator(sch).iter_errors(neg)))
    ex_ids = [d['equipment_id'] for d in exm['model_output']['detections'] if d['equipment_id']]
    check('schema: 예시 equipment_id가 마스터에 있음', set(ex_ids) <= set(ids), ex_ids)
except ImportError:
    check('schema: jsonschema 미설치로 검증 못함', False)

cnt = collections.Counter(l['equipment_id'] for i in ev['images'] for l in i['labels'])
clear_cnt = collections.Counter(l['equipment_id'] for i in ev['images'] for l in i['labels'] if l['visibility'] == 'clear')
summary = {
    'master_equipment': len(ids),
    'industry_list_sizes': {k: len(v['items']) for k, v in m['industry_lists'].items()},
    'industry_basis_counts': {k: dict(collections.Counter(x['basis_type'] for x in v['items'])) for k, v in m['industry_lists'].items()},
    'evidence_status_counts': dict(collections.Counter(e['evidence_status'] for e in m['equipment'])),
    'images': len(ev['images']), 'labels': len(lab_ids), 'negative_images': sum(i['is_negative'] for i in ev['images']),
    'uncertain_candidates': sum(len(i['uncertain_candidates']) for i in ev['images']),
    'label_count_by_equipment': dict(cnt.most_common()), 'clear_label_count_by_equipment': dict(clear_cnt.most_common()),
    'equipment_without_any_label': sorted(set(ids) - set(cnt)),
    'scene_groups': len({i['scene_group'] for i in ev['images']}),
}
res = {'validated_date_kst': '2026-11-16', 'all_pass': not problems, 'problems': problems, 'checks': checks, 'summary': summary}
with open(os.path.join(OUT, '261115_검증결과_v1_DR.json'), 'w', encoding='utf-8') as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
print('all_pass', not problems, problems)
print(json.dumps(summary, ensure_ascii=False)[:1500])
