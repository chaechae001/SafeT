"""입력 기반 행도 FOOD-3LEVEL-1.2로 현재·예상 위험도를 계산한다(2026-11-25 사용자 지시)."""
import sys
from pathlib import Path
from types import SimpleNamespace as A

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import authoring_rag  # noqa: E402

FRY = authoring_rag.FOOD['FRY']
CRIT = [c['id'] for c in FRY['controls'] if c['critical']]


def row(sid='FRY', supported=()):
    cands = [dict(control_id=c['id'], text=c['id'] + ' 계획') for c in authoring_rag.FOOD[sid]['controls'] if c['id'] not in supported]
    return dict(scenario_id=sid, grade='상', control_band=3, severity=2, current_controls=[dict(control_id=i) for i in supported],
                improvement_candidates=cands + [dict(control_id='FRY-C4', text='1.1 전용 조치')],
                rationale='… 기존 기준을 적용한 결과는 ‘상’입니다. 미확인은 …')


def test_regrade_uses_food_matrix_and_rewrites_reason():
    r = authoring_rag.regrade(row())
    assert (r['grade'], r['policy_version']) == ('중', 'FOOD-3LEVEL-1.2') and '‘중’입니다(FOOD-3LEVEL-1.2)' in r['rationale']
    assert authoring_rag.regrade(row(supported=CRIT))['grade'] == '중'
    assert authoring_rag.regrade(row('FIRE'))['grade'] == '상'


def test_projected_signal_lowers_with_checked_plans():
    item = dict(authoring=dict(row=row()))
    plans = lambda ids: [A(text=i + ' 계획', checked=True) for i in ids]
    assert authoring_rag.projected_signal(item, [], None) == 'N'
    assert authoring_rag.projected_signal(item, plans(CRIT), None) == 'Y'
    assert authoring_rag.projected_signal(item, plans([c['id'] for c in FRY['controls']]), None) == 'G'
    assert authoring_rag.projected_signal(item, [A(text='1.1 전용 조치', checked=True)], None) == 'Y'  # 1.2에 없는 ID는 제외
    fire = dict(authoring=dict(row=row('FIRE')))
    assert authoring_rag.projected_signal(fire, plans([c['id'] for c in authoring_rag.FOOD['FIRE']['controls']]), None) == 'Y'
