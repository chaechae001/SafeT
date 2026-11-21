"""실제 위험요인 검색 서버로 일반 평가표 생성 → 체크 → 저장 → 재조회를 확인한다(FOOD-3LEVEL-1.2). 명시 실행 전용.

  python -m ai.risk_law_search.server --mode keyword --law a --port 8020      # 저장소 루트에서
  $env:SAFET_RISK_LAW_URL="http://127.0.0.1:8020"; $env:DB_NAME="safet_test"
  backend\\.venv\\Scripts\\python -m pytest backend/tests/live_risk_law_smoke.py -q -s

모의 응답 대신 검색 서버의 /api/analyze를 호출한다. 결과 표(저장 전후 등급·반영 조치 ID)를 출력한다.
"""
import json
import os
import urllib.request

import pytest

from services import catalog_risk
from conftest import engine
from test_assessment import create, edits, flow  # noqa: F401
from test_risk_law_flow import check, put, row

URL = os.getenv('SAFET_RISK_LAW_URL', '')


def reachable():
    try:
        return URL and urllib.request.urlopen(URL.rstrip('/') + '/api/health', timeout=3).status == 200
    except OSError:
        return False


@pytest.mark.skipif(not reachable(), reason='SAFET_RISK_LAW_URL 검색 서버가 없습니다')
def test_live_fry_fire(client, flow, monkeypatch):  # noqa: F811
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE', 'catalog_rls_v1')
    with engine.begin() as c:
        catalog_risk.seed(c)
    h, p = flow
    p['text'] = '튀김기에서 기름이 튀어요. 식용유에 불이 붙어 주방 화재가 날 수 있어요.'
    d = create(client, (h, p))
    got = {it['catalog']['scenario']['id']: it for it in d['items']}
    print('\n생성 행:', {k: (v['policy_version'], v['signal'], v['after']) for k, v in got.items()})
    assert all(it['policy_version'] == 'FOOD-3LEVEL-1.2' for it in d['items'])
    lines = []
    for sid in [s for s in ('FRY', 'FIRE') if s in got]:
        sc = got[sid]['catalog']['scenario']
        before = (got[sid]['signal'], got[sid]['after'])
        crit = [c['id'] for c in sc['controls'] if c['critical']]
        d = put(client, h, d, check(edits(d), d, sid, 'plans', crit))
        mid = row(d, sid)
        d = put(client, h, d, check(edits(d), d, sid, 'plans', [c['id'] for c in sc['controls']]))
        again = row(client.get(f"/evals/{d['eval_no']}", headers=h).json(), sid)
        lines.append(dict(scenario=sid, before=before, critical_plans=(mid['signal'], mid['after']),
                          applied_critical=mid['catalog']['projected_result']['applied_control_ids'],
                          all_plans=(again['signal'], again['after']),
                          applied_all=again['catalog']['projected_result']['applied_control_ids'],
                          reason=again['catalog']['projected_result']['reason']))
    print(json.dumps(lines, ensure_ascii=False, indent=1))
    assert lines, '검색 결과에 FRY·FIRE 행이 없습니다(카드→시나리오 연결 확인)'
