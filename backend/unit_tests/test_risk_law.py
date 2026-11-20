"""위험요인·법령 검색 모듈 연결(catalog_rls_v1): DB·모델 없이 행 생성·조치 연결·위험도 계산을 검사한다."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from services import catalog_risk, risk_law  # noqa: E402
from services.auth import AuthError  # noqa: E402

CAT = json.loads((ROOT / 'contracts/catalog_risk/catalog.json').read_text(encoding='utf-8'))['scenarios']
FRY = next(s for s in CAT if s['id'] == 'FRY')
CRIT = [c['id'] for c in FRY['controls'] if c['critical']]


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


def test_rows_merge_same_scenario_and_keep_unmatched():
    items, unmatched = risk_law.rows(RESULT, CAT)
    assert len(items) == 1 and items[0]['catalog']['id'] == 'FRY'
    ref = items[0]['risk_law']
    assert ref['card']['card_id'] == 'A' and [c['card_id'] for c in ref['other_cards']] == ['B']
    assert items[0]['curr'] == ['물기 제거', '천천히 투입', '지침 작성'] and len(items[0]['plans']) == 3
    assert {u['card_id'] for u in unmatched} == {'C', 'D', 'E'}
    assert ref['law']['status'].startswith('자동 검색 후보')


def test_links_use_only_mapped_controls():
    items, _ = risk_law.rows(RESULT, CAT)
    assert risk_law.links(items[0]['risk_law']) == {('C', 0): CRIT[0], ('P', 0): CRIT[2]}


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


def test_initial_grade_equals_projection_and_links_follow_map():
    items, _ = risk_law.rows(RESULT, CAT)
    actions = [dict(action_no=10 + i, action_type='C') for i in range(3)] + [dict(action_no=20 + i, action_type='P') for i in range(3)]
    db = FakeDB(actions)
    catalog_risk.initialize(db, 7, FRY, None, items[0]['risk_law'])
    state = json.loads(db.calls[-1][1]['s'])
    assert state['links'] == {'10': CRIT[0], '20': CRIT[2]}
    assert state['action_controls']['12']['control_id'] is None and state['action_controls']['12']['status'] == 'auto_pending'
    item = dict(curr=[dict(id=10), dict(id=99)], plans=[])
    catalog_risk.enrich(item, json.dumps(state))
    assert item['curr'][0]['control']['control_id'] == CRIT[0] and item['curr'][1]['control']['control_id'] is None
    assert state['current_result']['grade'] == state['projected_result']['grade'] == '상'  # FRY S2, 핵심 없음
    grade = next(p for s, p in db.calls if 'curr_risk_grade' in s)
    assert grade['g'] == grade['a'] == 'R' and grade['j'] == 'Y'


class Act:
    def __init__(self, id, checked, text='x'):
        self.id, self.checked, self.text = id, checked, text


class Edit:
    def __init__(self, curr, plans):
        self.curr, self.plans, self.controls_reviewed, self.none, self.keep = curr, plans, False, False, None


def recalc(state, curr, plans):
    db = FakeDB([])
    item = dict(id=7, catalog=copy.deepcopy(state))
    catalog_risk.recalculate(db, item, Edit(curr, plans), 'tester@test.invalid', 2, 1)
    return json.loads(next(p['s'] for s, p in db.calls if 'catalog_state' in s))


def test_save_recalculates_with_mapped_checks_only():
    links = {str(100 + i): cid for i, cid in enumerate(CRIT)}
    state = dict(scenario=FRY, links=links, risk_law={}, current_result=None, projected_result=None)
    # 직접 추가(id 없음)·연결 없는 체크는 계산에 쓰지 않는다.
    out = recalc(state, [Act(None, True, '직접 추가'), Act(999, True)], [])
    assert out['current_result']['grade'] == out['projected_result']['grade'] == '상'
    # 핵심 조치 모두 계획 → 예상만 내려간다. 현재는 그대로.
    out = recalc(state, [], [Act(100 + i, True) for i in range(len(CRIT))])
    assert out['current_result']['grade'] == '상' and out['projected_result']['grade'] == '중'
    # 핵심 조치 모두 현재 실시 → 현재도 중.
    out = recalc(state, [Act(100 + i, True) for i in range(len(CRIT))], [])
    assert out['current_result']['grade'] == out['projected_result']['grade'] == '중'


def test_other_catalog_sources_unchanged():
    db = FakeDB([dict(action_no=1, action_type='C')])
    catalog_risk.initialize(db, 7, FRY)
    state = json.loads(db.calls[-1][1]['s'])
    assert 'risk_law' not in state and state['current_result']['signal'] == 'N'
