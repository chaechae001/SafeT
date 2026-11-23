"""UX-017: 03 기기 직접 추가(이번 평가에만)와 내 평가표 목록의 위험 항목 수.

- add_custom_machines·add_machine_codes 는 위험요인 검색(risk_law.analyze)에 등록 기기와 함께 들어가고 eval_machine 에 저장된다.
- 사업장 등록 기기(workplace_machine)는 바뀌지 않는다. 등록 기기와 같은 이름은 중복으로 넣지 않는다.
- 목록 GET /evals 의 item_count = 평가표의 위험 항목(eval_dtl) 수.
검색 서버는 부르지 않고 고정 응답을 쓴다(test_risk_law_flow.RESULT). DB 안전장치는 conftest.py.
"""
import uuid

from sqlalchemy import text

from conftest import engine
from services import catalog_risk, risk_law
from test_assessment import flow  # noqa: F401
from test_risk_law_flow import RESULT


def _setup(monkeypatch, seen):
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE', 'catalog_rls_v1')

    def analyze(t, v, m=()):
        seen.append([x['machine_nm'] for x in m])
        return RESULT
    monkeypatch.setattr(risk_law, 'analyze', analyze)
    with engine.begin() as c:
        catalog_risk.seed(c)


def test_added_machines_feed_search_and_are_saved(client, flow, monkeypatch, biz_code):  # noqa: F811
    seen = []
    _setup(monkeypatch, seen)
    h, p = flow
    code = 'X' + uuid.uuid4().hex[:6]
    with engine.begin() as c:
        c.execute(text("INSERT INTO machine_category (machine_code, biz_code, machine_nm, use_yn) VALUES (:c,:b,'반죽기','Y')"),
                  {'c': code, 'b': biz_code})
    try:
        body = dict(p, add_machine_codes=[code], add_custom_machines=['  제빙기 ', '제빙기', '튀김기'])
        r = client.post('/evals', headers=h, json=body)
        assert r.status_code == 201, r.text
        doc = r.json()
        # 등록 기기(튀김기) + 업종 기기(반죽기) + 직접 입력(제빙기). 등록 기기와 같은 이름·중복은 한 번만
        assert seen == [['튀김기', '반죽기', '제빙기']]
        assert [m['machine_nm'] for m in doc['machines']] == ['튀김기', '반죽기', '제빙기']
        assert [m['machine_code'] for m in doc['machines']][1] == code
        # 사업장 등록 기기는 그대로
        w = client.get(f"/workplaces/{p['work_no']}", headers=h).json()
        assert [m['machine_nm'] for m in w['machines']] == ['튀김기']
    finally:
        with engine.begin() as c:
            c.execute(text('DELETE FROM risk_event WHERE eval_no IN (SELECT eval_no FROM eval_mst WHERE request_key=:k)'), {'k': p['request_key']})
            c.execute(text('DELETE FROM eval_machine WHERE machine_code=:c'), {'c': code})
            c.execute(text('DELETE FROM machine_category WHERE machine_code=:c'), {'c': code})


def test_unknown_machine_code_is_rejected(client, flow, monkeypatch):  # noqa: F811
    _setup(monkeypatch, [])
    h, p = flow
    r = client.post('/evals', headers=h, json=dict(p, add_machine_codes=['NOPE999']))
    assert r.status_code == 400 and r.json()['detail']['code'] == 'INVALID_MACHINE', r.text


def test_old_payload_without_machine_fields_still_works(client, flow, monkeypatch):  # noqa: F811
    seen = []
    _setup(monkeypatch, seen)
    h, p = flow
    r = client.post('/evals', headers=h, json=p)
    assert r.status_code == 201, r.text
    assert seen == [['튀김기']]
    with engine.begin() as c:
        c.execute(text('DELETE FROM risk_event WHERE eval_no IN (SELECT eval_no FROM eval_mst WHERE request_key=:k)'), {'k': p['request_key']})


def test_list_has_item_count(client, flow):  # noqa: F811
    h, p = flow           # demo 모드(test_assessment.flow) — 합성 항목
    r = client.post('/evals', headers=h, json=p)
    assert r.status_code == 201, r.text
    doc = r.json()
    card = next(x for x in client.get('/evals?tab=W', headers=h).json()['items'] if x['eval_no'] == doc['eval_no'])
    assert card['item_count'] == len(doc['items']) > 0


def test_save_added_machines_to_workplace(client, flow, monkeypatch):  # noqa: F811
    """UX-018: save_machines_to_workplace=true 면 추가한 기기가 사업장 보유 기기에도 남는다."""
    seen = []
    _setup(monkeypatch, seen)
    h, p = flow
    r = client.post('/evals', headers=h, json=dict(p, add_custom_machines=['제빙기'], detected_machine_names=['사진 기기'], save_machines_to_workplace=True))
    assert r.status_code == 201, r.text
    assert set(seen[0]) == {'튀김기', '제빙기', '사진 기기'}
    w = client.get(f"/workplaces/{p['work_no']}", headers=h).json()
    assert [m['machine_nm'] for m in w['machines']] == ['튀김기', '제빙기']
    with engine.begin() as c:
        c.execute(text('DELETE FROM risk_event WHERE eval_no IN (SELECT eval_no FROM eval_mst WHERE request_key=:k)'), {'k': p['request_key']})
