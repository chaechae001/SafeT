"""위험요인·법령 검색 모듈 연결(catalog_rls_v1): 생성 → 저장(재계산) → 재조회를 DB로 검사한다.

검색 서버는 부르지 않고 모듈 응답 형식의 고정값을 쓴다. DB 안전장치는 conftest.py를 따른다.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from conftest import engine
from services import catalog_risk, risk_law
from test_assessment import create, edits, flow  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
FRY = next(s for s in json.loads((ROOT / 'contracts/catalog_risk/catalog.json').read_text(encoding='utf-8'))['scenarios']
           if s['id'] == 'FRY')
CRIT = [c['id'] for c in FRY['controls'] if c['critical']]


def option(text, cid=None):
    return dict(text=text, original=text, origin='이 카드 직접 대책', origin_card='OPS-19-C1',
                control=dict(control_id=cid, status='confirmed' if cid else 'unmapped', message='시험'))


RESULT = dict(units=[dict(text='튀김기 앞 바닥에 물기가 있어요.', source_label='작업 설명', risks=[dict(
    card_id='OPS-19-C1', title='튀김 중 기름 튐', text='뜨거운 기름이 튐', risk_type='화상', low_confidence=False,
    scenario=dict(status='auto', scenario_id='FRY', message='자동 후보 · 검토 전'),
    law=None, law_basis='주제가 맞는 후보가 없습니다 · 담당자 확인 필요',
    current_options=[option('물기 제거', CRIT[0]), option('천천히 투입'), option('지침 작성')],
    improvement_options=[option(f'개선 {i}', cid) for i, cid in enumerate(CRIT[1:3])] + [option('교육')])])])


@pytest.fixture
def rls_flow(flow, monkeypatch):  # noqa: F811
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE', 'catalog_rls_v1')
    monkeypatch.setattr(risk_law, 'analyze', lambda t, v, m=(): RESULT)
    with engine.begin() as c:
        catalog_risk.seed(c)
    h, p = flow
    yield h, p
    with engine.begin() as c:
        c.execute(text('DELETE FROM risk_event WHERE actor IN (SELECT email FROM eval_mst WHERE request_key=:k)'),
                  {'k': p['request_key']})


def test_rls_rows_grade_from_start_and_recalculate_on_save(client, rls_flow):
    h, _ = rls_flow
    d = create(client, rls_flow)
    url = f"/evals/{d['eval_no']}"
    it = d['items'][0]
    assert d['generation_source'] == 'catalog_rls_v1' and it['catalog']['risk_law']['card']['card_id'] == 'OPS-19-C1'
    assert it['signal'] == it['after'] == 'R' and it['judged']  # 체크 0개 → 현재 = 예상
    assert [a['text'] for a in it['curr']] == ['물기 제거', '천천히 투입', '지침 작성'] and all(a['ai'] for a in it['curr'])
    assert it['curr'][0]['control']['control_id'] == CRIT[0] and it['curr'][1]['control']['control_id'] is None
    p = edits(d)
    p['items'][0]['curr'][0]['checked'] = True
    p['items'][0]['curr'].append({'text': '직접 추가 조치', 'checked': True})
    for a in p['items'][0]['plans']:
        a['checked'] = True
    r = client.put(url, headers=h, json=p)
    assert r.status_code == 200, r.text
    it = r.json()['items'][0]
    # 핵심 조치 5개 중 3개만 연결·체크(현재 1 + 계획 2) → 현재·예상 모두 상. 직접 추가는 계산 제외.
    assert it['signal'] == 'R' and it['after'] == 'R'
    state = it['catalog']
    assert state['current_result']['control_band'] == 3 and state['projected_result']['kind'] == 'projected'
    assert any(not a['ai'] and a['control']['control_id'] is None for a in it['curr'])
    assert client.get(url, headers=h).json()['items'][0]['catalog']['risk_law']['law']['candidate'] is None
