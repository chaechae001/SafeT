"""위험도(현재·예상 신호) 정답셋 평가.

정답(expected)은 팀 확정 문서에서 만든다. 계산(actual)은 서비스 함수로 한다.
- 등급표: docs/implementation/risk-development-agreement.md (FOOD-3LEVEL-1.2, CATALOG-MVP-1.1)
- 조치 구간·input_based 규칙: contracts/assessment_authoring/v1/INTERFACES.md
- input_based 정답 예시: contracts/assessment_authoring/v1/examples/*/expected.json
- 11/22 실모델 결과: 산업분야_음식점/261122_Cloud_main41302e7_3시나리오검증_DR (로그 재생, 모델 재실행 없음)

사용법(저장소 루트, Python 3.11, backend/requirements.txt 설치 환경):
  python ai/experiments/261122_위험도정확도평가_DR/eval_risk_levels.py --build-gold   # 정답셋 다시 만들기
  python ai/experiments/261122_위험도정확도평가_DR/eval_risk_levels.py                # 평가·결과 저장

이 스크립트는 위험성 판단 기준을 새로 만들지 않는다. 문서 표를 그대로 옮겨 정답으로 쓴다.
"""
import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]

from services import catalog_risk, risk_law  # noqa: E402
from domain.risk_policy import evaluate  # noqa: E402
from ai.assessment_authoring.assessment_composer import compose_assessment  # noqa: E402
from ai.assessment_authoring.contracts import read as read_contract, load_catalog  # noqa: E402

GOLD = HERE / 'gold' / 'gold_rules.jsonl'
REPLAY = HERE / 'gold' / 'replay_261122.jsonl'
PUBLIC = HERE / 'gold' / 'public_cases_8.jsonl'
OUT = HERE / 'results'
SIG = {'상': 'R', '중': 'Y', '하': 'G', None: 'N'}
LABELS = ['R', 'Y', 'G', 'N']

# 문서 표 그대로(키: 피해 수준 S → 조치 구간 C). C1 기준 조치 전체 충족, C2 핵심 전부·보완 일부 미충족, C3 핵심 일부 또는 전부 미충족.
DOC_TABLE = {
    # 합의 문서 '신규 평가표 정책 — FOOD-3LEVEL-1.2' 표
    'FOOD-3LEVEL-1.2': {1: {3: '중', 2: '하', 1: '하'}, 2: {3: '중', 2: '중', 1: '하'}, 3: {3: '상', 2: '중', 1: '중'}},
    # 합의 문서 '기존 공통 등급표 — CATALOG-MVP-1.1' 표(열 순서: 모두 유효 / 핵심 유효·보완 미흡 / 핵심 결여·무효)
    'CATALOG-MVP-1.1': {1: {1: '하', 2: '중', 3: '중'}, 2: {1: '중', 2: '중', 3: '상'}, 3: {1: '상', 2: '상', 3: '상'}},
}
SRC_AGREEMENT = 'docs/implementation/risk-development-agreement.md'
SRC_INTERFACES = 'contracts/assessment_authoring/v1/INTERFACES.md'


def catalogs():
    c12 = json.loads((ROOT / 'contracts/catalog_risk/catalog-food-3level-1.2.json').read_text(encoding='utf-8'))
    c11 = json.loads((ROOT / 'contracts/catalog_risk/catalog.json').read_text(encoding='utf-8'))
    return {'FOOD-3LEVEL-1.2': {s['id']: s for s in c12['scenarios']},
            'CATALOG-MVP-1.1': {s['id']: s for s in c11['scenarios']}}


def band(scenario, credited):
    """INTERFACES.md: 핵심 중 하나라도 미충족이면 C3, 핵심 전부·보완 부족이면 C2, 전체면 C1."""
    ids = {c['id'] for c in scenario['controls']}
    crit = {c['id'] for c in scenario['controls'] if c['critical']}
    credited = set(credited) & ids
    return 3 if not crit <= credited else (1 if ids <= credited else 2)


def doc_signal(policy, scenario, credited):
    return SIG[DOC_TABLE[policy][scenario['severity']][band(scenario, credited)]]


def ids(scenario, which):
    return [c['id'] for c in scenario['controls'] if which == 'all' or c['critical'] == (which == 'critical')]


# ---------------------------------------------------------------- 정답셋 생성

def build_gold():
    cats = catalogs()
    gold = []

    def add(**case):
        case['id'] = f"G{len(gold) + 1:03d}"
        gold.append(case)

    # 1) 등급표 9칸 × 2정책: 실제 시나리오로 각 칸을 만든다(evaluate 직접 호출 경로).
    reps = {1: 'KNIFE_STORAGE', 2: 'FRY', 3: 'FIRE'}
    for policy in DOC_TABLE:
        for sev, sid in reps.items():
            s = cats[policy][sid]
            for b, chosen in ((3, []), (2, ids(s, 'critical')), (1, ids(s, 'all'))):
                add(path='evaluate', policy=policy, scenario_id=sid, current_ids=chosen, plan_ids=[], answered=True,
                    expected=dict(current=SIG[DOC_TABLE[policy][sev][b]]),
                    source=f'{SRC_AGREEMENT} {policy} 표 S{sev}·C{b}', basis='문서 표')

    # 2) 일반 평가표 생성 시점(체크 0개 계산, 2026-11-21 결정): 1.2 카탈로그 26개 시나리오 전부.
    for sid, s in cats['FOOD-3LEVEL-1.2'].items():
        g = doc_signal('FOOD-3LEVEL-1.2', s, [])
        add(path='rls_create', policy='FOOD-3LEVEL-1.2', scenario_id=sid, current_ids=[], plan_ids=[],
            expected=dict(current=g, projected=g),
            source=f'{SRC_AGREEMENT} 계산 시점(일반 평가표: 생성 시 체크 0개로 계산)', basis='문서 표 + 카탈로그 S')

    # 3) 문서에 적힌 팀 예시(값을 문서 문장에서 그대로 옮김).
    fry, fire = cats['FOOD-3LEVEL-1.2']['FRY'], cats['FOOD-3LEVEL-1.2']['FIRE']
    add(path='rls_save', policy='FOOD-3LEVEL-1.2', scenario_id='FRY', current_ids=[], plan_ids=ids(fry, 'critical'),
        expected=dict(current='Y', projected='Y'), source=f'{SRC_AGREEMENT} 팀 연결 예시 "FRY 핵심 3개 → 현재 중 / 예상 중"', basis='팀 예시')
    add(path='rls_save', policy='FOOD-3LEVEL-1.2', scenario_id='FRY', current_ids=[], plan_ids=ids(fry, 'all'),
        expected=dict(current='Y', projected='G'), source=f'{SRC_AGREEMENT} 팀 연결 예시 "보완(FRY-C7)까지 → 예상 하"', basis='팀 예시')
    add(path='rls_save', policy='FOOD-3LEVEL-1.2', scenario_id='FIRE', current_ids=[], plan_ids=ids(fire, 'critical'),
        expected=dict(current='R', projected='Y'), source=f'{SRC_AGREEMENT} 팀 연결 예시 "FIRE 핵심 전부 → 현재 상 / 예상 중"', basis='팀 예시')
    add(path='rls_save', policy='FOOD-3LEVEL-1.2', scenario_id='FIRE', current_ids=[], plan_ids=ids(fire, 'all'),
        expected=dict(current='R', projected='Y'), source=f'{SRC_AGREEMENT} 팀 연결 예시 "보완까지 선택해도 중"', basis='팀 예시')

    # 4) 일반 평가표 저장: 현재 조치 일부 + 계획 조치, 같은 ID 중복, 직접 입력(기준 ID 없음) 제외.
    for sid in ('ENV', 'LADDER', 'KNIFE_STORAGE', 'GAS', 'FRY'):
        s = cats['FOOD-3LEVEL-1.2'][sid]
        crit, allc = ids(s, 'critical'), ids(s, 'all')
        sup = ids(s, 'support')
        for cur, plan, note in ((crit[:1], [], '핵심 일부만 현재 시행'),
                                (crit, [], '핵심 전부 현재 시행'),
                                (crit, sup, '핵심 현재 + 보완 계획'),
                                (crit[:1], crit, '같은 ID를 현재·계획 양쪽에 선택(한 번만 셈)'),
                                (allc, [], '기준 조치 전체 현재 시행')):
            add(path='rls_save', policy='FOOD-3LEVEL-1.2', scenario_id=sid, current_ids=cur, plan_ids=plan,
                expected=dict(current=doc_signal('FOOD-3LEVEL-1.2', s, cur), projected=doc_signal('FOOD-3LEVEL-1.2', s, set(cur) | set(plan))),
                source=f'{SRC_AGREEMENT} 계산 대상·현재·예상 위험도 / {SRC_INTERFACES} 일반 평가표 계약', basis='문서 규칙', note=note)
    add(path='rls_save', policy='FOOD-3LEVEL-1.2', scenario_id='FRY', current_ids=[], plan_ids=[], manual_plans=1,
        expected=dict(current='Y', projected='Y'), basis='문서 규칙', note='직접 입력 대책만 체크(기준 ID 없음) → 하향하지 않음',
        source=f'{SRC_AGREEMENT} 계산 대상(직접 입력은 계산 제외)')

    # 5) DB 기준(catalog_v1) 경로: 목록 확인 전 N, 확인 후 계산, 계획 선택 시에만 예상.
    for policy in DOC_TABLE:
        for sid in ('FRY', 'FIRE', 'KNIFE_STORAGE', 'ENV'):
            s = cats[policy][sid]
            crit, allc = ids(s, 'critical'), ids(s, 'all')
            add(path='catalog_save', policy=policy, scenario_id=sid, current_ids=crit, plan_ids=[], reviewed=False,
                expected=dict(current='N', projected='N'), basis='문서 규칙', note='현재 조치 목록 전체 확인 전',
                source=f'{SRC_AGREEMENT} 1.1 절 "정보 부족 = 확인 필요(N)" / 1.2 표 계산 시점(catalog_v1은 기존대로)')
            add(path='catalog_save', policy=policy, scenario_id=sid, current_ids=[], plan_ids=[], reviewed=True, none=True,
                expected=dict(current=doc_signal(policy, s, []), projected='N'), basis='문서 규칙', note="'현재 조치 없음' 확인, 계획 미선택",
                source=f'{SRC_AGREEMENT} 이번 구현 범위(미선택=확인 후 미실시)')
            add(path='catalog_save', policy=policy, scenario_id=sid, current_ids=crit[:1], plan_ids=allc, reviewed=True,
                expected=dict(current=doc_signal(policy, s, crit[:1]), projected=doc_signal(policy, s, allc)), basis='문서 규칙',
                note='핵심 일부 현재 + 기준 대책 전체 계획', source=f'{SRC_AGREEMENT} 예상 위험도(현재 ∪ 계획, 이행 가정)')
    s11 = cats['CATALOG-MVP-1.1']
    add(path='catalog_save', policy='CATALOG-MVP-1.1', scenario_id='ENV', current_ids=[], plan_ids=ids(s11['ENV'], 'all'), reviewed=True, none=True,
        expected=dict(current='R', projected='Y'), basis='팀 예시',
        source=f'{SRC_AGREEMENT} 팀 연결 예시(1.1) "치료·회복 수준, 핵심 없음 → 현재 상 / 모두 선택 → 예상 중"')
    add(path='catalog_save', policy='CATALOG-MVP-1.1', scenario_id='FIRE', current_ids=ids(s11['FIRE'], 'all'), plan_ids=[], reviewed=True, keep='Y',
        expected=dict(current='R', projected='R'), basis='팀 예시',
        source=f'{SRC_AGREEMENT} 팀 연결 예시(1.1) "사망·영구장해 경로가 남으면 모두 선택해도 상 유지"')

    # 6) input_based(CATALOG-MVP-1.1-AUTO-1.0): 계약 정답 예시 3건 + 누락 조치(unknown) 변형.
    for name in ('unknown', 'critical_supported', 'all_supported'):
        e = read_contract(f'examples/{name}/expected.json')
        add(path='input_based', policy='CATALOG-MVP-1.1', scenario_id=e['scenario_id'], example=name, drop_controls=[],
            expected=dict(current=SIG[e['grade']]), basis='계약 정답 예시',
            source=f'contracts/assessment_authoring/v1/examples/{name}/expected.json')
    fry11 = s11['FRY']
    for drop, note in ((['FRY-C1'], '핵심 1개가 입력에 없음(unknown)'), (['FRY-C8'], '보완 1개가 입력에 없음'),
                       (ids(fry11, 'critical'), '핵심 전부가 입력에 없음')):
        keep = set(ids(fry11, 'all')) - set(drop)
        add(path='input_based', policy='CATALOG-MVP-1.1', scenario_id='FRY', example='all_supported', drop_controls=drop,
            expected=dict(current=doc_signal('CATALOG-MVP-1.1', fry11, keep)), basis='계약 규칙', note=note,
            source=f'{SRC_INTERFACES} 계산·처리 상태(누락 조치는 unknown, unknown은 계산상 미충족)')
    return gold


# ---------------------------------------------------------------- 서비스 경로 실행

class FakeDB:
    def __init__(self, actions=()):
        self.actions, self.calls = list(actions), []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        return self

    def mappings(self):
        return self

    def all(self):
        return self.actions


class Act:
    def __init__(self, id, checked, text='x'):
        self.id, self.checked, self.text = id, checked, text


class Edit:
    def __init__(self, curr, plans, reviewed=False, none=False, keep=None):
        self.curr, self.plans, self.controls_reviewed, self.none, self.keep = curr, plans, reviewed, none, keep


def _state(db):
    return json.loads(next(p['s'] for q, p in reversed(db.calls) if 'catalog_state' in q))


def _row(db):
    return next(p for q, p in reversed(db.calls) if 'curr_risk_grade' in q)


def run_rls(case, cats):
    s = cats[case['policy']][case['scenario_id']]
    rk = dict(card_id='EVAL', title='평가', text='평가', risk_type='평가', low_confidence=False,
              scenario=dict(status='auto', scenario_id=s['id'], message='평가'), law=None, law_basis='',
              current_options=[], improvement_options=[])
    items, _ = risk_law.rows(dict(units=[dict(text='작업', source_label='작업 설명', risks=[rk])]), list(cats[case['policy']].values()))
    it = items[0]
    acts = ([dict(action_no=100 + i, action_type='C') for i in range(len(it['curr']))]
            + [dict(action_no=200 + i, action_type='P') for i in range(len(it['plans']))])
    db = FakeDB(acts)
    catalog_risk.initialize(db, 7, it['catalog'], None, it['risk_law'])
    state, row = _state(db), _row(db)
    if case['path'] == 'rls_create':
        return dict(current=row['g'], projected=row['a'])
    by = {}
    for a, c in state['links'].items():
        by.setdefault((int(a) // 100, c), int(a))
    curr = [Act(by[(1, c)], True) for c in case['current_ids']]
    plans = [Act(by[(2, c)], True) for c in case['plan_ids']] + [Act(None, True, '직접 입력')] * case.get('manual_plans', 0)
    db = FakeDB()
    catalog_risk.recalculate(db, dict(id=7, catalog=copy.deepcopy(state)), Edit(curr, plans, False, not curr), 'eval@test.invalid', 2, 1)
    row = _row(db)
    return dict(current=row['g'], projected=row['a'])


def run_catalog(case, cats):
    s = cats[case['policy']][case['scenario_id']]
    acts = ([dict(action_no=100 + i, action_type='C') for i in range(len(s['controls']))]
            + [dict(action_no=200 + i, action_type='P') for i in range(len(s['controls']))])
    db = FakeDB(acts)
    catalog_risk.initialize(db, 7, s)
    state = _state(db)
    by = {(int(a) // 100, c): int(a) for a, c in state['links'].items()}
    curr = [Act(by[(1, c)], True) for c in case['current_ids']]
    plans = [Act(by[(2, c)], True) for c in case['plan_ids']]
    db = FakeDB()
    catalog_risk.recalculate(db, dict(id=7, catalog=copy.deepcopy(state)),
                             Edit(curr, plans, case.get('reviewed', False), case.get('none', False), case.get('keep')),
                             'eval@test.invalid', 2, 1)
    row = _row(db)
    return dict(current=row['g'], projected=row['a'])


def run_input_based(case, _cats):
    base = f"examples/{case['example']}/"
    i, r, a = read_contract(base + 'input.json'), read_contract(base + 'retrieval.json'), read_contract(base + 'analysis.json')
    for cand in a['candidates']:  # 응답에서 빠진 조치는 계약상 unknown으로 정규화된다.
        cand['control_evidence'] = [e for e in cand['control_evidence'] if e['control_id'] not in case['drop_controls']]
    core = compose_assessment(i, r, a, load_catalog())
    row = next(x for x in core['items'] if x['scenario_id'] == case['scenario_id'])
    return dict(current=SIG[row['grade']])


def run_evaluate(case, cats):
    s = cats[case['policy']][case['scenario_id']]
    res = evaluate(s, case['current_ids'] + case['plan_ids'], answered=case['answered'])
    return dict(current=res['signal'])


RUNNERS = dict(evaluate=run_evaluate, rls_create=run_rls, rls_save=run_rls, catalog_save=run_catalog, input_based=run_input_based)


# ---------------------------------------------------------------- 지표

def confusion(pairs):
    m = {e: {a: 0 for a in LABELS} for e in LABELS}
    for e, a in pairs:
        m[e][a] += 1
    return m


def summarize(rows, field):
    pairs = [(r['expected'][field], r['actual'].get(field)) for r in rows if field in r['expected']]
    hit = sum(e == a for e, a in pairs)
    return dict(n=len(pairs), match=hit, rate=round(hit / len(pairs), 4) if pairs else None, confusion=confusion(pairs))


def run_gold(gold):
    cats = catalogs()
    out = []
    for case in gold:
        try:
            actual = RUNNERS[case['path']](case, cats)
            err = None
        except Exception as e:  # 실패도 결과에 남긴다
            actual, err = {}, f'{type(e).__name__}: {e}'
        ok = all(actual.get(k) == v for k, v in case['expected'].items())
        out.append(dict(case, actual=actual, ok=ok, error=err))
    return out


def replay_1122():
    """11/22 Cloud 실모델 결과(input_based)의 관찰 신호를 계약 v1 규칙의 기대값과 비교한다. 모델은 다시 돌리지 않는다."""
    rows = [json.loads(line) for line in REPLAY.read_text(encoding='utf-8').splitlines() if line.strip()]
    cats = catalogs()
    for r in rows:
        s11, s12 = cats['CATALOG-MVP-1.1'][r['scenario_id']], cats['FOOD-3LEVEL-1.2'][r['scenario_id']]
        r['expected_v1'] = doc_signal('CATALOG-MVP-1.1', s11, r['supported_ids'])
        r['whatif_1_2'] = doc_signal('FOOD-3LEVEL-1.2', s12, r['supported_ids'])  # 미적용 대안. 참고용
        r['ok'] = r['observed'] == r['expected_v1']
    return rows


def whatif_draft_distribution():
    """조치 근거가 전혀 없을 때(input_based unknown 전부·일반 평가표 생성 시) 26개 시나리오의 초안 신호 분포."""
    cats = catalogs()
    return {p: dict(Counter(doc_signal(p, s, []) for s in cats[p].values())) for p in DOC_TABLE}


def public_cases():
    rows = [json.loads(line) for line in PUBLIC.read_text(encoding='utf-8').splitlines() if line.strip()]
    cats = catalogs()['FOOD-3LEVEL-1.2']
    for r in rows:
        sid = r.get('candidate_scenario_id')
        if sid and r.get('candidate_control_ids') is not None:
            s = cats[sid]
            r['reference_only'] = dict(safe_t_current=doc_signal('FOOD-3LEVEL-1.2', s, []),
                                       safe_t_projected=doc_signal('FOOD-3LEVEL-1.2', s, r['candidate_control_ids']),
                                       case_score_decreased=(r['after_score'] is not None and r['before_score'] is not None
                                                             and r['after_score'] < r['before_score']))
            r['reference_only']['safe_t_decreased'] = r['reference_only']['safe_t_projected'] != r['reference_only']['safe_t_current']
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build-gold', action='store_true')
    args = ap.parse_args()
    if args.build_gold:
        GOLD.parent.mkdir(exist_ok=True)
        gold = build_gold()
        GOLD.write_text(''.join(json.dumps(g, ensure_ascii=False) + '\n' for g in gold), encoding='utf-8')
        print(f'정답셋 {len(gold)}건 저장: {GOLD.relative_to(ROOT)}')
        return
    gold = [json.loads(line) for line in GOLD.read_text(encoding='utf-8').splitlines() if line.strip()]
    rows = run_gold(gold)
    by_path = {}
    for r in rows:
        by_path.setdefault(r['path'], []).append(r)
    replay = replay_1122()
    pub = public_cases()
    result = dict(
        gold=dict(n=len(rows), all_fields_match=sum(r['ok'] for r in rows), current=summarize(rows, 'current'),
                  projected=summarize(rows, 'projected'),
                  by_path={p: dict(n=len(v), all_fields_match=sum(x['ok'] for x in v)) for p, v in by_path.items()},
                  mismatches=[{k: r[k] for k in ('id', 'path', 'policy', 'scenario_id', 'expected', 'actual', 'error', 'note') if k in r}
                              for r in rows if not r['ok']]),
        replay_261122=dict(n=len(replay), match_contract_v1=sum(r['ok'] for r in replay),
                           observed=dict(Counter(r['observed'] for r in replay)),
                           whatif_1_2=dict(Counter(r['whatif_1_2'] for r in replay)), rows=replay),
        draft_distribution_26=whatif_draft_distribution(),
        public_cases=dict(n=len(pub), usable_for_grade_accuracy=sum(1 for r in pub if r.get('grade_comparable')),
                          rows=pub),
    )
    OUT.mkdir(exist_ok=True)
    (OUT / 'eval_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    g = result['gold']
    print(f"정답셋 {g['n']}건 · 전체 필드 일치 {g['all_fields_match']}건")
    print(f"현재 신호 일치 {g['current']['match']}/{g['current']['n']} · 예상 신호 일치 {g['projected']['match']}/{g['projected']['n']}")
    for p, v in g['by_path'].items():
        print(f'  {p}: {v["all_fields_match"]}/{v["n"]}')
    print('현재 신호 혼동행렬(행=정답, 열=계산):')
    for e in LABELS:
        print('  ', e, [g['current']['confusion'][e][a] for a in LABELS])
    print('예상 신호 혼동행렬(행=정답, 열=계산):')
    for e in LABELS:
        print('  ', e, [g['projected']['confusion'][e][a] for a in LABELS])
    rp = result['replay_261122']
    print(f"11/22 재생 {rp['n']}행 · 계약 v1 기대와 일치 {rp['match_contract_v1']} · 관찰 {rp['observed']} · 1.2 가정 {rp['whatif_1_2']}")
    print('조치 근거 0개 초안 분포(26개 시나리오):', result['draft_distribution_26'])
    print(f"공개 사례 {result['public_cases']['n']}건 · 등급 비교 가능 {result['public_cases']['usable_for_grade_accuracy']}건")
    if g['mismatches']:
        print('불일치:', json.dumps(g['mismatches'], ensure_ascii=False)[:2000])
    return 0 if not g['mismatches'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
