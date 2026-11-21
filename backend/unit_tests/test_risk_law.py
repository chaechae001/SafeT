"""일반 평가표(catalog_rls_v1): DB·모델 없이 행 생성·기준 조치 연결·FOOD-3LEVEL-1.2 위험도 계산을 검사한다.

추천은 시나리오 1.2 카탈로그의 기준 조치로 구성되고(control_id 보유), 저장 시 action_id → control_id 연결로 계산한다.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from services import catalog_risk, risk_law  # noqa: E402
from services.auth import AuthError  # noqa: E402

CAT = json.loads((ROOT / 'contracts/catalog_risk/catalog-food-3level-1.2.json').read_text(encoding='utf-8'))['scenarios']
CAT11 = json.loads((ROOT / 'contracts/catalog_risk/catalog.json').read_text(encoding='utf-8'))['scenarios']
SC = {s['id']: s for s in CAT}
FRY, FIRE = SC['FRY'], SC['FIRE']
CRIT = [c['id'] for c in FRY['controls'] if c['critical']]          # FRY-C1·C2·C3
SUPPORT = [c['id'] for c in FRY['controls'] if not c['critical']]  # FRY-C7


def option(text, cid=None, status='confirmed'):
    return dict(text=text, original=text, origin='이 카드 직접 대책', origin_card='OPS-19-C1',
                control=dict(control_id=cid if status in ('confirmed', 'auto') else None, candidate_id=cid, status=status, message='시험'))


def risk(card, sid='FRY', status='auto', low=False, current=None, plans=None):
    return dict(card_id=card, title=f'{card} 기름 튐', text='뜨거운 기름이 튐', risk_type='화상', low_confidence=low,
                scenario=dict(status=status, scenario_id=sid, message='자동 후보 · 검토 전'),
                law=dict(id='L1', law_name='산업안전보건기준에 관한 규칙', locator='제1조', article_title='시험', quote='원문'),
                law_basis='자동 연결 · 적용 미확인',
                current_options=current if current is not None else [option('물기 제거', CRIT[0]), option('천천히 투입'), option('지침 작성', CRIT[1], 'auto_pending')],
                improvement_options=plans if plans is not None else [option('보호구', CRIT[2]), option('교육'), option('표지')])


RESULT = dict(units=[dict(text='튀김기에서 기름이 튀어요', source_label='작업 설명', risks=[
    risk('A'), risk('B'), risk('C', status='auto_weak'), risk('D', low=True), risk('E', sid='NOPE')])])


class FakeDB:
    def __init__(self, actions):
        self.actions, self.calls = actions, []

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
    def __init__(self, curr, plans, reviewed=False, none=False):
        self.curr, self.plans, self.controls_reviewed, self.none, self.keep = curr, plans, reviewed, none, None


def build(sid='FRY', catalog=CAT, recs=None):
    """모듈 응답 → 행 → initialize(FakeDB). 반환: (state, 행, 첫 저장 결과 파라미터)."""
    r = risk('A', sid=sid) if recs is None else risk('A', sid=sid, current=recs[0], plans=recs[1])
    items, _ = risk_law.rows(dict(units=[dict(text='작업', source_label='작업 설명', risks=[r])]), catalog)
    it = items[0]
    actions = ([dict(action_no=100 + i, action_type='C') for i in range(len(it['curr']))]
               + [dict(action_no=200 + i, action_type='P') for i in range(len(it['plans']))])
    db = FakeDB(actions)
    catalog_risk.initialize(db, 7, it['catalog'], None, it['risk_law'])
    state = json.loads(db.calls[-1][1]['s'])
    grade = next(p for q, p in db.calls if 'curr_risk_grade' in q)
    return state, it, grade


def aid(state, kind, cid):
    """기준 조치 ID → 이 행의 action_id(C: 100번대, P: 200번대)."""
    base = 100 if kind == 'C' else 200
    return next(int(a) for a, c in state['links'].items() if c == cid and base <= int(a) < base + 100)


def recalc(state, curr, plans, reviewed=False, none=False):
    db = FakeDB([])
    catalog_risk.recalculate(db, dict(id=7, catalog=copy.deepcopy(state)), Edit(curr, plans, reviewed, none),
                             'tester@test.invalid', 2, 1)
    out = json.loads(next(p['s'] for q, p in db.calls if 'catalog_state' in q))
    row = next(p for q, p in db.calls if 'curr_risk_grade' in q)
    return out, row


def grades(out):
    return out['current_result']['grade'], out['projected_result']['grade']


def test_rows_use_catalog_controls_and_keep_unmatched():
    items, unmatched = risk_law.rows(RESULT, CAT)
    assert len(items) == 1 and items[0]['catalog']['id'] == 'FRY' and items[0]['catalog']['policy_version'] == 'FOOD-3LEVEL-1.2'
    ref = items[0]['risk_law']
    assert ref['card']['card_id'] == 'A' and [c['card_id'] for c in ref['other_cards']] == ['B']
    # 기준 조치 4개(검토 완료 추천 C1 먼저 → 핵심 → 보완) + 계산 제외 추천 2개
    assert [o['control']['control_id'] for o in ref['current']] == ['FRY-C1', 'FRY-C2', 'FRY-C3', 'FRY-C7', None, None]
    assert ref['current'][0]['control']['recommended'] and ref['current'][0]['text'] == FRY['controls'][0]['current_text']
    assert [o['control']['status'] for o in ref['current'][4:]] == ['unmapped', 'auto_pending']
    assert [o['control']['control_id'] for o in ref['plans']][:4] == ['FRY-C3', 'FRY-C1', 'FRY-C2', 'FRY-C7']
    assert {u['card_id'] for u in unmatched} == {'C', 'D', 'E'}
    assert ref['law']['status'].startswith('자동 검색 후보')


def test_links_follow_action_positions():
    items, _ = risk_law.rows(RESULT, CAT)
    links = risk_law.links(items[0]['risk_law'])
    assert [links[('C', i)] for i in range(4)] == ['FRY-C1', 'FRY-C2', 'FRY-C3', 'FRY-C7'] and ('C', 4) not in links


def test_generate_snapshot_calls_module(monkeypatch):
    seen = {}

    def fake(text, voice, machines=()):
        seen.update(text=text, voice=voice, machines=machines)
        return RESULT
    monkeypatch.setattr(risk_law, 'analyze', fake)
    source, items = catalog_risk.generate_snapshot(CAT, dict(text='튀김기', voice_text='', machines=[{'machine_nm': '튀김기'}]),
                                                   source=catalog_risk.RLS_SOURCE)
    assert source == 'catalog_rls_v1' and seen == dict(text='튀김기', voice='', machines=[{'machine_nm': '튀김기'}])
    assert {u['card_id'] for u in items[0]['risk_law']['unmatched']} == {'C', 'D', 'E'}
    with pytest.raises(AuthError):
        catalog_risk.generate_snapshot(CAT, dict(text=' ', voice_text=''), source=catalog_risk.RLS_SOURCE)
    monkeypatch.setattr(risk_law, 'analyze', lambda t, v, m=(): dict(units=[]))
    with pytest.raises(AuthError) as e:
        catalog_risk.generate_snapshot(CAT, dict(text='회의'), source=catalog_risk.RLS_SOURCE)
    assert e.value.status == 422


def test_machine_rows_are_marked_for_work_check():
    result = dict(units=[dict(text='튀김기', source='MACHINE', source_label='등록 기기', risks=[risk('A')])])
    items, _ = risk_law.rows(result, CAT)
    assert items[0]['risk_law']['card']['from_machine'] and '등록 기기' in items[0]['reason']
    assert '작성자 확인' in items[0]['risk_law']['notice']


def test_unconfigured_module_is_service_error(monkeypatch):
    monkeypatch.delenv('SAFET_RISK_LAW_URL', raising=False)
    with pytest.raises(AuthError) as e:
        risk_law.analyze('튀김', '')
    assert e.value.status == 503


def test_initial_grade_from_zero_controls():
    state, _, row = build('FRY')
    assert state['current_result']['policy_version'] == 'FOOD-3LEVEL-1.2'
    assert grades(state) == ('중', '중') and row['g'] == row['a'] == 'Y' and row['j'] == 'Y'  # S2 · 0개 → 중
    assert '0개' in state['current_result']['reason']
    state, _, _ = build('FIRE')
    assert grades(state) == ('상', '상')  # S3 · 0개 → 상


def test_fry_critical_plans_then_supplementary():
    state, _, _ = build('FRY')
    plans = [Act(aid(state, 'P', c), True) for c in CRIT]
    out, _ = recalc(state, [], plans)
    assert grades(out) == ('중', '중')
    pr = out['projected_result']
    assert pr['applied_control_ids'] == CRIT and pr['missing_supplementary_ids'] == SUPPORT and pr['missing_critical_ids'] == []
    assert '남은 보완 조치: FRY-C7' in pr['reason'] and '충족하면 하' in pr['reason']
    out, _ = recalc(state, [], plans + [Act(aid(state, 'P', SUPPORT[0]), True)])
    assert grades(out) == ('중', '하')


def test_fire_keeps_middle_even_when_all_controls_planned():
    state, _, _ = build('FIRE')
    crit = [c['id'] for c in FIRE['controls'] if c['critical']]
    out, _ = recalc(state, [], [Act(aid(state, 'P', c), True) for c in crit])
    assert grades(out) == ('상', '중')
    assert '판정표상 중가 유지' in out['projected_result']['reason']
    out, _ = recalc(state, [], [Act(aid(state, 'P', c['id']), True) for c in FIRE['controls']])
    assert grades(out) == ('상', '중') and '최저 등급은 중' in out['projected_result']['reason']


def test_same_control_counted_once_and_uncheck_recalculates():
    state, _, _ = build('FRY')
    curr = [Act(aid(state, 'C', c), True) for c in CRIT]
    plans = [Act(aid(state, 'P', c), True) for c in CRIT]  # 같은 조치를 양쪽에 체크
    out, _ = recalc(state, curr, plans)
    assert grades(out) == ('중', '중') and out['projected_result']['applied_control_ids'] == CRIT
    out, _ = recalc(state, curr[:2], plans[:2])  # 하나 해제
    assert grades(out) == ('중', '중') and out['projected_result']['missing_critical_ids'] == [CRIT[2]]
    out, _ = recalc(state, curr, plans + [Act(aid(state, 'P', SUPPORT[0]), True)])
    assert grades(out) == ('하', '하') or grades(out) == ('중', '하')  # 현재 핵심 3개 → 중, 예상 전체 → 하
    assert out['current_result']['grade'] == '중'


def test_invalid_selections_are_excluded():
    state, it, _ = build('FRY')
    unconfirmed = 100 + 5  # '지침 작성'(auto_pending): 저장되지만 계산 제외
    tampered = copy.deepcopy(state)
    tampered['links']['999'] = 'FIRE-C1'  # 다른 시나리오 ID
    out, _ = recalc(tampered, [Act(unconfirmed, True), Act(None, True, '직접 입력'), Act(999, True), Act(12345, True)], [])
    assert grades(out) == ('중', '중') and out['current_result']['applied_control_ids'] == []
    item = dict(curr=[dict(id=100), dict(id=unconfirmed), dict(id=555)], plans=[])
    catalog_risk.enrich(item, json.dumps(state))
    c0, c1, c2 = (a['control'] for a in item['curr'])
    assert c0['control_id'] == 'FRY-C1' and '핵심 기준 조치' in c0['message']
    assert c1['control_id'] is None and c1['status'] == 'auto_pending'
    assert c2['control_id'] is None and '직접 입력' in c2['message']
    assert item['policy_version'] == 'FOOD-3LEVEL-1.2'


def test_saved_legacy_rows_keep_their_policy():
    """기존 1.1 평가표: 저장 당시 정책으로 계속 계산한다(1.2로 바꾸지 않음)."""
    fry11 = next(s for s in CAT11 if s['id'] == 'FRY')
    state, _, _ = build('FRY', catalog=CAT11)
    assert state['current_result']['policy_version'] == 'CATALOG-MVP-1.1' and grades(state) == ('상', '상')
    crit11 = [c['id'] for c in fry11['controls'] if c['critical']]
    out, _ = recalc(state, [], [Act(aid(state, 'P', c), True) for c in crit11])
    assert grades(out) == ('상', '중') and out['projected_result']['policy_version'] == 'CATALOG-MVP-1.1'
    old = copy.deepcopy(state)
    old['scenario']['policy_version'] = 'OLD-0.9'
    with pytest.raises(AuthError):
        recalc(old, [], [])


def test_document_policy():
    item = lambda v: dict(catalog=dict(scenario=dict(policy_version=v)))  # noqa: E731
    assert catalog_risk.document_policy([]) == 'FOOD-3LEVEL-1.2'
    assert catalog_risk.document_policy([item('CATALOG-MVP-1.1')]) == 'CATALOG-MVP-1.1'
    with pytest.raises(AuthError):
        catalog_risk.document_policy([item('CATALOG-MVP-1.1'), item('FOOD-3LEVEL-1.2')])


def test_confirmed_mapping_is_recommended_and_auto_is_excluded(tmp_path):
    """모듈 연결표의 검토 완료 추천은 해당 기준 조치로 앞에 두고, 검토 전 자동 연결은 계산에서 제외한다."""
    sys.path.insert(0, str(ROOT))
    from ai.risk_law_search.control_map import ControlMapper, key
    links = {key('FRY', '검토 완료 대책'): dict(control_id='FRY-C2', score=0.9, candidate='FRY-C2', confirmed='FRY-C2', note=''),
             key('FRY', '검토 전 대책'): dict(control_id='FRY-C3', score=0.9, candidate='FRY-C3', confirmed=None, note=''),
             key('FRY', '1.2에 없는 조치'): dict(control_id='FRY-C4', score=0.9, candidate='FRY-C4', confirmed='FRY-C4', note='')}
    path = tmp_path / 'map.json'
    path.write_text(json.dumps(dict(links=links), ensure_ascii=False), encoding='utf-8')
    mapper = ControlMapper(map_path=path)

    def opt(t):
        return dict(text=t, original=t, origin='이 카드 직접 대책', origin_card='OPS-19-C1', control=mapper.link('FRY', t))
    recs = [opt('검토 완료 대책'), opt('검토 전 대책'), opt('1.2에 없는 조치')]
    assert [o['control']['status'] for o in recs] == ['confirmed', 'auto_pending', 'weak']
    state, it, _ = build('FRY', recs=(recs, []))
    ref = it['risk_law']['current']
    assert ref[0]['control']['control_id'] == 'FRY-C2' and ref[0]['control']['recommended']
    assert [o['text'] for o in ref[4:]] == ['검토 전 대책', '1.2에 없는 조치'] and all(o['control']['control_id'] is None for o in ref[4:])
    out, _ = recalc(state, [Act(104, True), Act(105, True)], [])
    assert out['current_result']['applied_control_ids'] == []


def test_machine_only_rows_go_to_pending():
    result = dict(units=[dict(text='튀김기에서 기름이 튀어요', source_label='작업 설명', risks=[risk('A')]),
                         dict(text='튀김기', source='MACHINE', source_label='등록 기기', risks=[risk('B'), risk('M', sid='KNIFE')])])
    items, _ = risk_law.rows(result, CAT)
    rows, pending = risk_law.split_pending(items)
    assert [r['catalog']['id'] for r in rows] == ['FRY']  # 입력 글과 같은 시나리오는 행에 합쳐진다
    assert [p['catalog']['id'] for p in pending] == ['KNIFE']
    view = risk_law.pending_view(pending[0])
    assert view['scenario_id'] == 'KNIFE' and view['machine'] == '튀김기' and '확인' in view['notice']


def test_review_pending_adds_or_dismisses(monkeypatch):
    from services import assessment
    from schemas.assessment import PendingReview
    machine = dict(units=[dict(text='칼', source='MACHINE', source_label='등록 기기', risks=[risk('M', sid='KNIFE')])])
    _, pending = risk_law.split_pending(risk_law.rows(machine, CAT)[0])
    snap = json.dumps(dict(rls_pending=pending), ensure_ascii=False)
    mst = dict(eval_status='W', revision=3, generation_source='catalog_rls_v1', authoring_snapshot=snap)
    inserted, writes = [], []

    class DB:
        def commit(self): pass
        def rollback(self): pass
    monkeypatch.setattr(assessment, 'owned', lambda db, e, n, lock=False: mst)
    monkeypatch.setattr(assessment, 'detail', lambda db, e, n: dict(items=[]))
    monkeypatch.setattr(assessment, 'insert_items', lambda db, n, items, e, offset=0: inserted.extend(items))
    monkeypatch.setattr(assessment, 'execute', lambda db, sql, **p: writes.append(p))
    body = PendingReview(revision=3, scenario_id='KNIFE', decision='add')
    assessment.review_pending(DB(), 'tester@test.invalid', 1, body)
    assert [i['catalog']['id'] for i in inserted] == ['KNIFE'] and inserted[0]['risk_law']['work_confirmed']
    saved = json.loads(writes[-1]['s'])
    assert saved['rls_pending'] == [] and saved['rls_pending_log'][0]['decision'] == 'add'
    # 제외: 행을 만들지 않고 기록만 남긴다
    inserted.clear()
    assessment.review_pending(DB(), 'tester@test.invalid', 1, PendingReview(revision=3, scenario_id='KNIFE', decision='dismiss'))
    assert not inserted and json.loads(writes[-1]['s'])['rls_pending_log'][0]['decision'] == 'dismiss'
    with pytest.raises(AuthError) as e:
        assessment.review_pending(DB(), 'tester@test.invalid', 1, PendingReview(revision=3, scenario_id='FRY', decision='add'))
    assert e.value.status == 404
    with pytest.raises(AuthError) as e:
        assessment.review_pending(DB(), 'tester@test.invalid', 1, PendingReview(revision=2, scenario_id='KNIFE', decision='add'))
    assert e.value.status == 409  # 오래된 revision


def test_confirm_blocked_while_pending(monkeypatch):
    from services import assessment
    from schemas.assessment import SaveAssessment

    class DB:
        def commit(self): pass
        def rollback(self): pass
    monkeypatch.setattr(assessment, 'owned', lambda db, e, n, lock=False: dict(eval_status='W', revision=1, generation_source='catalog_rls_v1'))
    monkeypatch.setattr(assessment, 'detail', lambda db, e, n: dict(items=[], pending_rows=[dict(scenario_id='KNIFE')]))
    with pytest.raises(AuthError) as e:
        assessment.save(DB(), 'tester@test.invalid', 1, SaveAssessment(revision=1, items=[]), confirm=True)
    assert e.value.code == 'PENDING_ROWS_REVIEW_REQUIRED'
