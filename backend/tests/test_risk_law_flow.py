"""일반 평가표(catalog_rls_v1): 생성 → 체크 → 저장(재계산) → 재조회를 DB로 검사한다. 신규 평가표 정책 FOOD-3LEVEL-1.2.

검색 서버는 부르지 않고 모듈 응답 형식의 고정값을 쓴다. DB 안전장치는 conftest.py를 따른다(_test DB 또는 ALLOW_DB_TESTS=1).
"""
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from conftest import engine
from services import catalog_risk, risk_law
from test_assessment import create, edits, flow  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
NEW = {s['id']: s for s in json.loads((ROOT / 'contracts/catalog_risk/catalog-food-3level-1.2.json').read_text(encoding='utf-8'))['scenarios']}
OLD = {s['id']: s for s in json.loads((ROOT / 'contracts/catalog_risk/catalog.json').read_text(encoding='utf-8'))['scenarios']}


def crit(s, flag=True):
    return [c['id'] for c in s['controls'] if c['critical'] is flag]


def option(text, cid=None, status=None):
    return dict(text=text, original=text, origin='이 카드 직접 대책', origin_card='OPS-19-C1',
                control=dict(control_id=cid, status=status or ('confirmed' if cid else 'unmapped'), message='시험'))


def risk(card, sid, title):
    return dict(card_id=card, title=title, text=title, risk_type='화상', low_confidence=False,
                scenario=dict(status='auto', scenario_id=sid, message='자동 후보 · 검토 전'),
                law=None, law_basis='주제가 맞는 후보가 없습니다 · 담당자 확인 필요',
                current_options=[option('물기 제거', 'FRY-C1' if sid == 'FRY' else None), option('천천히 투입'),
                                 option('지침 작성', None, 'auto_pending')],
                improvement_options=[option('교육')])


RESULT = dict(units=[dict(text='튀김기 앞 바닥에 물기가 있어요.', source_label='작업 설명', risks=[
    risk('OPS-19-C1', 'FRY', '튀김 중 기름 튐'), risk('OPS-20-H1', 'FIRE', '주방 화재')])])


@pytest.fixture
def rls_flow(flow, monkeypatch):  # noqa: F811
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE', 'catalog_rls_v1')
    monkeypatch.setattr(risk_law, 'analyze', lambda t, v, m=(): RESULT)
    with engine.begin() as c:
        catalog_risk.seed(c)
    h, p = flow
    yield h, p
    with engine.begin() as c:
        c.execute(text('DELETE FROM risk_event WHERE eval_no IN (SELECT eval_no FROM eval_mst WHERE request_key=:k)'),
                  {'k': p['request_key']})


def row(doc, sid):
    return next(it for it in doc['items'] if it['catalog']['scenario']['id'] == sid)


def check(payload, doc, sid, kind, cids, on=True):
    """기준 조치 ID로 화면 체크를 흉내 낸다(저장 요청은 action_id만 보낸다)."""
    it = row(doc, sid)
    ids = {a['id'] for a in it[kind] if (a.get('control') or {}).get('control_id') in cids}
    edit = next(e for e in payload['items'] if e['id'] == it['id'])
    for a in edit[kind]:
        if a['id'] in ids:
            a['checked'] = on
    return payload


def put(client, h, doc, payload):
    r = client.put(f"/evals/{doc['eval_no']}", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def view(it):
    return (it['signal'], it['after'], it['catalog']['current_result']['applied_control_ids'],
            it['catalog']['projected_result']['applied_control_ids'])


def test_catalog_seed_adds_1_2_next_to_existing_1_1(rls_flow):
    with engine.begin() as c:
        counts = dict(c.execute(text('SELECT version, COUNT(*) FROM risk_catalog GROUP BY version')).all())
    assert counts['FOOD-3LEVEL-1.2'] == 26 and counts.get('CATALOG-MVP-1.1') == 26


def test_new_assessment_uses_1_2_generate_check_save_reload(client, rls_flow):
    h, _ = rls_flow
    d = create(client, rls_flow)
    fry, fire = row(d, 'FRY'), row(d, 'FIRE')
    assert d['generation_source'] == 'catalog_rls_v1'
    assert fry['policy_version'] == fire['policy_version'] == 'FOOD-3LEVEL-1.2'
    # 생성: 체크 0개 기준 계산. FRY S2 → 중/중, FIRE S3 → 상/상
    assert (fry['signal'], fry['after'], fire['signal'], fire['after']) == ('Y', 'Y', 'R', 'R')
    assert [a['control']['control_id'] for a in fry['curr']][:4] == ['FRY-C1', 'FRY-C2', 'FRY-C3', 'FRY-C7']
    assert [a['control']['control_id'] for a in fry['curr']][4:] == [None, None]  # 미확정 추천: 저장·계산 제외

    # 사례 1: FRY 현재 비움 + 개선대책 핵심 3개 / FIRE 핵심 전부 개선대책
    p = check(edits(d), d, 'FRY', 'plans', crit(NEW['FRY']))
    p = check(p, d, 'FIRE', 'plans', crit(NEW['FIRE']))
    d = put(client, h, d, p)
    assert view(row(d, 'FRY')) == ('Y', 'Y', [], crit(NEW['FRY']))
    assert row(d, 'FRY')['catalog']['projected_result']['missing_supplementary_ids'] == ['FRY-C7']
    assert view(row(d, 'FIRE')) == ('R', 'Y', [], crit(NEW['FIRE']))
    assert '판정표상 중가 유지' in row(d, 'FIRE')['catalog']['projected_result']['reason']

    # 사례 2: 보완 조치까지 → FRY 예상 하. 재조회해도 체크·등급·근거가 같다
    p = check(edits(d), d, 'FRY', 'plans', crit(NEW['FRY'], False))
    p = check(p, d, 'FIRE', 'plans', crit(NEW['FIRE'], False))
    d = put(client, h, d, p)
    again = client.get(f"/evals/{d['eval_no']}", headers=h).json()
    for sid in ('FRY', 'FIRE'):
        a, b = row(d, sid), row(again, sid)
        assert view(a) == view(b) and a['reason'] == b['reason']
        assert [x['checked'] for x in a['plans']] == [x['checked'] for x in b['plans']]
    assert view(row(again, 'FRY'))[:2] == ('Y', 'G')
    assert view(row(again, 'FIRE'))[:2] == ('R', 'Y') and '최저 등급은 중' in row(again, 'FIRE')['catalog']['projected_result']['reason']

    # 서버 판정 입력 기록(risk_event)과 대조
    with engine.begin() as c:
        last = json.loads(c.execute(text("SELECT payload FROM risk_event WHERE item_id=:i AND kind='calculation' ORDER BY event_id DESC LIMIT 1"),
                                    {'i': row(d, 'FRY')['id']}).scalar())
    assert last['projected']['applied_control_ids'] == ['FRY-C1', 'FRY-C2', 'FRY-C3', 'FRY-C7']
    assert last['projected']['policy_version'] == 'FOOD-3LEVEL-1.2'

    # 사례 3: 같은 조치를 현재·개선 양쪽 체크 → 한 번만. 하나 해제 → 남은 조치로 갱신
    p = check(edits(d), d, 'FRY', 'curr', crit(NEW['FRY']))
    d = put(client, h, d, p)
    assert view(row(d, 'FRY')) == ('Y', 'G', crit(NEW['FRY']), ['FRY-C1', 'FRY-C2', 'FRY-C3', 'FRY-C7'])
    p = check(edits(d), d, 'FRY', 'curr', ['FRY-C3'], on=False)
    p = check(p, d, 'FRY', 'plans', ['FRY-C3', 'FRY-C7'], on=False)
    d = put(client, h, d, p)
    fry = row(d, 'FRY')
    assert view(fry) == ('Y', 'Y', ['FRY-C1', 'FRY-C2'], ['FRY-C1', 'FRY-C2'])
    assert fry['catalog']['projected_result']['missing_critical_ids'] == ['FRY-C3']

    # 사례 4: 미확정 추천·직접 입력 체크는 저장하되 계산 제외
    p = edits(d)
    e = next(x for x in p['items'] if x['id'] == fry['id'])
    for a in e['curr']:
        if a['text'] in ('지침 작성', '천천히 투입'):
            a['checked'] = True
    e['curr'].append({'text': '직접 입력 조치', 'checked': True})
    d = put(client, h, d, p)
    fry = row(d, 'FRY')
    assert view(fry)[2] == ['FRY-C1', 'FRY-C2']
    manual = next(a for a in fry['curr'] if a['text'] == '직접 입력 조치')
    assert manual['checked'] and manual['control']['control_id'] is None and '계산 제외' in manual['control']['message']

    # 내부 검토 화면과 같은 판정: 같은 1.2 입력 → 같은 등급·근거
    sys.path.insert(0, str(ROOT))
    from ai.risk_law_search.grading import assess_selection
    from ai.risk_law_search.scenario_map import ScenarioLinker
    _, audit = assess_selection(ScenarioLinker(), dict(card_id='OPS-19-C1', scenario_id='FRY',
                                                       current_ids=['FRY-C1', 'FRY-C2'], plan_ids=[]))
    pr = fry['catalog']['projected_result']
    assert audit['expected_risk'] == pr['grade'] and pr['reason'].endswith(audit['reason'])


def test_legacy_1_1_assessment_keeps_policy(client, rls_flow, monkeypatch):
    h, _ = rls_flow
    real = catalog_risk.list_catalog
    monkeypatch.setattr(catalog_risk, 'list_catalog', lambda db, version=None: real(db, 'CATALOG-MVP-1.1'))
    d = create(client, rls_flow)  # 변경 전에 만든 평가표를 재현
    monkeypatch.setattr(catalog_risk, 'list_catalog', real)
    d = client.get(f"/evals/{d['eval_no']}", headers=h).json()
    fry = row(d, 'FRY')
    assert fry['policy_version'] == 'CATALOG-MVP-1.1' and (fry['signal'], fry['after']) == ('R', 'R')
    d = put(client, h, d, check(edits(d), d, 'FRY', 'plans', crit(OLD['FRY'])))
    fry = row(d, 'FRY')
    assert (fry['signal'], fry['after']) == ('R', 'Y') and fry['catalog']['projected_result']['policy_version'] == 'CATALOG-MVP-1.1'


MACHINE = dict(units=RESULT['units'][:1] + [dict(text='칼', source='MACHINE', source_label='등록 기기', risks=[
    risk('OPS-01-H1', 'KNIFE', '칼에 베임')])])


def test_rls_machine_only_risk_waits_for_work_check(client, rls_flow, monkeypatch):
    h, _ = rls_flow
    monkeypatch.setattr(risk_law, 'analyze', lambda t, v, m=(): MACHINE)
    d = create(client, rls_flow)
    url = f"/evals/{d['eval_no']}"
    assert sorted(it['catalog']['scenario']['id'] for it in d['items']) == ['FIRE', 'FRY']
    assert [p['scenario_id'] for p in d['pending_rows']] == ['KNIFE']
    r = client.post(url + '/confirm', headers=h, json=edits(d, True))
    assert r.status_code == 422 and r.json()['detail']['code'] == 'PENDING_ROWS_REVIEW_REQUIRED'
    r = client.post(url + '/pending-rows', headers=h, json=dict(revision=d['revision'], scenario_id='KNIFE', decision='add'))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d['pending_rows'] == [] and row(d, 'KNIFE')
    knife = row(d, 'KNIFE')
    assert knife['policy_version'] == 'FOOD-3LEVEL-1.2' and knife['signal'] == 'Y'  # S2 · 0개 → 중
    assert knife['catalog']['risk_law']['work_confirmed']


def confirm_body(doc, none=False):
    """목록 전체 확인(controls_reviewed) 없이 확정 요청을 만든다. 현재 조치는 비워 둔다."""
    p = edits(doc)
    for e in p['items']:
        e.update(controls_reviewed=False, none=none, owner={'type': 'R', 'name': '근로자'}, due='2026-12-01')
        e['plans'][0]['checked'] = True
    return p


def test_rls_confirm_without_list_review(client, rls_flow):
    h, p = rls_flow
    # 1) 현재 조치 1개 이상 선택 → 목록 확인 체크 없이 확정
    d = create(client, rls_flow)
    body = confirm_body(d)
    for e in body['items']:
        e['curr'][0]['checked'] = True
    r = client.post(f"/evals/{d['eval_no']}/confirm", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()['eval_status'] == 'C' and not any(it['controls_reviewed'] for it in r.json()['items'])
    # 2) '현재 조치 없음' 선택 → 목록 확인 체크 없이 확정
    import uuid
    p['request_key'] = str(uuid.uuid4())
    d = create(client, (h, p))
    r = client.post(f"/evals/{d['eval_no']}/confirm", headers=h, json=confirm_body(d, none=True))
    assert r.status_code == 200, r.text
    # 3) 현재 조치·'현재 조치 없음' 둘 다 비움 → 차단
    p['request_key'] = str(uuid.uuid4())
    d = create(client, (h, p))
    r = client.post(f"/evals/{d['eval_no']}/confirm", headers=h, json=confirm_body(d))
    assert r.status_code == 422 and r.json()['detail']['code'] == 'EVAL_INCOMPLETE'
    assert {e['field'] for e in r.json()['detail']['errors']} == {'current'}
    assert client.get(f"/evals/{d['eval_no']}", headers=h).json()['eval_status'] == 'W'


def test_rls_confirm_blocked_by_pending_even_when_current_set(client, rls_flow, monkeypatch):
    h, _ = rls_flow
    monkeypatch.setattr(risk_law, 'analyze', lambda t, v, m=(): MACHINE)
    d = create(client, rls_flow)
    r = client.post(f"/evals/{d['eval_no']}/confirm", headers=h, json=confirm_body(d, none=True))
    assert r.status_code == 422 and r.json()['detail']['code'] == 'PENDING_ROWS_REVIEW_REQUIRED'
    r = client.post(f"/evals/{d['eval_no']}/pending-rows", headers=h,
                    json=dict(revision=d['revision'], scenario_id='KNIFE', decision='dismiss'))
    assert r.status_code == 200, r.text
    r = client.post(f"/evals/{d['eval_no']}/confirm", headers=h, json=confirm_body(r.json(), none=True))
    assert r.status_code == 200, r.text  # 확인 대기 처리 후에는 목록 확인 없이 확정
