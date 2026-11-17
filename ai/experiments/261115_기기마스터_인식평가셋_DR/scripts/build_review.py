"""검수 필요 목록 생성. 실행(작업 폴더 루트에서): python 261115_기기마스터_인식평가셋_DR/scripts/build_review.py
출력: 261115_검수필요목록_v1_DR.csv
"""
import collections
import csv
import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
m = json.load(open(os.path.join(OUT, '261115_기기마스터_v1_DR.json'), encoding='utf-8'))
ev = json.load(open(os.path.join(OUT, '261115_기기인식_평가셋_v1_DR.json'), encoding='utf-8'))
rows = []


def add(cat, target, issue, reviewer, prio):
    rows.append([f'RV{len(rows) + 1:03d}', cat, target, issue, reviewer, prio])


# 1. 권한·식별 정보
for i in ev['images']:
    r = i['rights']
    src = i['source']
    where = src.get('page_url') or src['origin_type']
    add('사진 권한', i['image_id'],
        f"공유·학습 권한 미확인. 출처: {where} ({src['url_status']}). 인물: {r['person_visibility']}. 상호·브랜드 노출: {'예' if r['store_or_brand_identifiable'] else '아니요'}",
        'DR·팀(공유 전)', '높음')
# 2. 근거 없는 기기 항목
for e in m['equipment']:
    if e['evidence_status'] == '제안':
        add('마스터 제안 항목', e['equipment_id'], f"{e['standard_name']}: 안전 자료 근거 없음. {e['note']}", '팀·멘토', '중간')
    elif e['hazard_evidence_status'] == '제안' or any(h['evidence'] == '제안' for h in e['related_hazards']):
        hz = ', '.join(h['name'] for h in e['related_hazards'] if h['evidence'] == '제안')
        add('위험요인 제안', e['equipment_id'], f"{e['standard_name']}: 근거 없는 위험요인 {hz}", '안전 전문가', '중간')
# 3. 업종 목록
for k, v in m['industry_lists'].items():
    c = collections.Counter(x['basis_type'] for x in v['items'])
    add('업종 목록', k, f"{v['industry_name']} {len(v['items'])}개(업종근거 {c['업종근거']}, 공통근거 {c['공통근거']}, 제안 {c['제안']}). 목록 길이와 제안 항목 포함 여부 결정",
        '팀·멘토', '높음' if k in ('bunsik', 'other') else '중간')
add('업종 목록', 'bunsik', '분식 업종을 다룬 근거 자료가 없음. 분식 매장 기기 조사 또는 고객사 데이터 필요', '팀·고객사', '높음')
add('업종 목록', 'cafe', 'D8 커피 절만 근거. 베이커리 카페 기기(오븐·쇄빙기·전자레인지)는 제과제빵 절 참고 제안', '팀', '중간')
# 4. OCR 근거
d5 = sorted({(e['equipment_id'], r['page']) for e in m['equipment'] for r in e['sources'] + [x for h in e['related_hazards'] for x in h['refs']] if r['src'] == 'D5'})
add('근거 원문 대조', 'D5 인용', 'D5(서비스업 재해사례 안내서)는 OCR 텍스트. 원문 쪽 대조 필요: ' + ', '.join(f'{a} p{b}' for a, b in d5), 'DR', '중간')
add('근거 원문 대조', 'D8 쪽 번호', 'D8 쪽은 PDF 쪽. 인쇄 쪽 = PDF 쪽 - 24. 보고서 인용 시 표기 방식 통일 필요', 'DR', '낮음')
# 5. 분류 판단
for t, s in [('EQ_STERILIZER', '살균기 자외선 노출을 chemical 코드로 임시 분류. 위험유형 체계에 맞는 코드 없음'),
             ('EQ_GAS_CYLINDER', 'LPG 용기와 부탄캔을 한 항목으로 묶음. 위험 수준이 달라 분리 여부 판단'),
             ('EQ_VEG_CUTTER', '동력 채소절단기와 수동 채칼을 한 항목으로 묶음. 분리 여부 판단'),
             ('EQ_ELECTRIC_PANEL', '기기보다 설비. B02 목록 포함 여부 결정'),
             ('EQ_KNIFE_BOARD', '화면설계서 예시를 따라 칼·도마를 한 항목으로 묶음. 카페의 칼은 D8에서 사무용 칼'),
             ('EQ_MOTORCYCLE', '주방·홀 사진 인식 대상이 아님. 인식 대상 여부 표시 필드 필요'),
             ('excluded_candidates', '소화기·경보기(대책), 작업대, 세제·청소기, 중화웍 등 제외. 제외 판단 확인')]:
    add('분류 판단', t, s, '팀·안전 전문가', '중간')
# 6. 라벨 검수
for i in ev['images']:
    for l in i['labels']:
        if l['visibility'] == 'partial' or l['label_confidence'] != 'high':
            add('라벨 검수', l['label_id'], f"{l['equipment_id']} ({l['visibility']}, {l['label_confidence']}) {l['note']}", '사람 라벨러', '중간')
    for c in i['uncertain_candidates']:
        add('라벨 판독 불가', i['image_id'], f"후보 {c['candidate_equipment_id'] or '없음'} @ {' '.join(c['region_grid'])}: {c['reason']}", '사람 라벨러', '중간')
    for x in i['not_in_master']:
        add('마스터 누락 후보', i['image_id'], f"{x['name']} @ {' '.join(x['region_grid'])}: {x['note']}", '팀', '낮음')
add('라벨 검수', '평가셋 전체', '전 라벨이 AI 보조 라벨. 사람이 34장 모두 확인해야 공식 평가에 쓸 수 있음. 영역은 3x3 격자 근사', '사람 라벨러', '높음')
add('평가셋 구성', '평가셋 전체', '튀김기 라벨 20/77로 편중. 치킨 매장 외 업종 사진 없음. 마스터 42개 중 22개는 라벨 0개', '팀', '높음')
add('평가셋 구성', 'scene_group', '같은 영상·매장 사진이 여러 장. 독립 표본이 아님. PotPlayer64_QgHfifs4YE와 P11·P12의 같은 영상 여부 미확인', 'DR', '중간')
add('출처 확인', 'zT1kAueZC7k_0019.zip', '실제사진 폴더 전체(35개 항목) 백업으로 보임. 평가셋에서 제외. 보관 목적 확인', 'DR', '낮음')
# 7. 설계 결정
for q in ['Q1 임계값 T', 'Q2 업종 밖 기기 표시', 'Q3 모호한 직접 추가 이름 처리', 'Q4 인식 대상 표시 필드', 'Q5 신뢰도 보정',
          '늦게 온 결과의 새 기기 추가 동작(설계서에 없음)']:
    add('설계 결정', '261115_기기인식_출력형식_제외규칙_v1_DR.md', q, '팀', '중간')

with open(os.path.join(OUT, '261115_검수필요목록_v1_DR.csv'), 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f)
    w.writerow(['review_id', 'category', 'target', 'issue', 'reviewer', 'priority'])
    w.writerows(rows)
print(len(rows), collections.Counter(r[1] for r in rows))
