"""현재·예상 위험도 공통 계산 검사."""
import json
import sys
from copy import deepcopy
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from domain.risk_policy import evaluate
SCENARIOS={s['id']:s for s in json.loads((ROOT/'contracts/catalog_risk/catalog.json').read_text(encoding='utf-8'))['scenarios']}

@pytest.mark.parametrize('severity,band,grade',[(1,1,'하'),(1,2,'중'),(1,3,'중'),(2,1,'중'),(2,2,'중'),(2,3,'상'),(3,1,'상'),(3,2,'상'),(3,3,'상')])
def test_matrix(severity,band,grade):
    s=deepcopy(SCENARIOS['KNIFE_STORAGE']);s['severity']=severity
    ids=[c['id'] for c in s['controls'] if band==1 or (band==2 and c['critical'])]
    assert evaluate(s,ids,answered=True)['grade']==grade

def test_unknown_and_invalid_controls():
    s=SCENARIOS['KNIFE_STORAGE']
    assert evaluate(s,[])['signal']=='N'
    with pytest.raises(ValueError):evaluate(s,['unknown'],answered=True)
    with pytest.raises(ValueError):evaluate({**s,'policy_version':'old'},[])

def test_catalog_provenance_and_effect():
    assert len(SCENARIOS)==26
    for s in SCENARIOS.values():
        assert s['source_refs'] and s['case_kind'] in ('document_derived_scenario','service_example')
        low=evaluate(s,[c['id'] for c in s['controls']],answered=True)
        high=evaluate(s,[],answered=True)
        assert low['control_band']==1 and high['control_band']==3
    s=SCENARIOS['FRY']
    support=[c['id'] for c in s['controls'] if not c['critical']]
    assert evaluate(s,support,answered=True)['grade']=='상'


# ---------- FOOD-3LEVEL-1.2 (신규 평가표) ----------
FOOD = json.loads((ROOT/'contracts/catalog_risk/catalog-food-3level-1.2.json').read_text(encoding='utf-8'))
FOOD_SC = {s['id']: s for s in FOOD['scenarios']}


@pytest.mark.parametrize('severity,band,grade', [(1,3,'중'),(1,2,'하'),(1,1,'하'),
                                                 (2,3,'중'),(2,2,'중'),(2,1,'하'),
                                                 (3,3,'상'),(3,2,'중'),(3,1,'중')])
def test_food_matrix_nine_conditions(severity, band, grade):
    s = deepcopy(FOOD_SC['KNIFE_STORAGE']); s['severity'] = severity
    ids = [c['id'] for c in s['controls'] if band == 1 or (band == 2 and c['critical'])]
    r = evaluate(s, ids, answered=True)
    assert (r['grade'], r['control_band'], r['policy_version']) == (grade, band, 'FOOD-3LEVEL-1.2')


def test_food_catalog_is_derived_from_1_1_only_by_documented_changes():
    from domain.risk_policy import ACTIVE_POLICY, MATRIX
    assert ACTIVE_POLICY == FOOD['policy_version'] == 'FOOD-3LEVEL-1.2'
    assert MATRIX == {1:{1:'하',2:'중',3:'중'},2:{1:'중',2:'중',3:'상'},3:{1:'상',2:'상',3:'상'}}  # 1.1 표는 그대로
    assert set(FOOD_SC) == set(SCENARIOS)
    for sid, s in FOOD_SC.items():
        old = dict(SCENARIOS[sid], policy_version='FOOD-3LEVEL-1.2')
        if sid == 'FRY':
            old['controls'] = [c for c in old['controls'] if c['id'] in {'FRY-C1','FRY-C2','FRY-C3','FRY-C7'}]
        assert s == old, sid
    assert FOOD_SC['FIRE']['severity'] == 3 and FOOD_SC['FRY']['severity'] == 2  # 기름 튐과 화재는 별도 시나리오


def test_food_catalog_control_ids_are_valid_for_every_scenario():
    for sid, s in FOOD_SC.items():
        ids = [c['id'] for c in s['controls']]
        assert len(ids) == len(set(ids)) and any(c['critical'] for c in s['controls']), sid
        assert all(c['current_text'] and c['plan_text'] for c in s['controls']), sid
        assert evaluate(s, [], answered=True)['control_band'] == 3
        assert evaluate(s, ids, answered=True)['control_band'] == 1
        with pytest.raises(ValueError):
            evaluate(s, ['OTHER-C1'], answered=True)


def test_seed_loads_both_versions_and_keeps_existing_1_1():
    from services import catalog_risk

    class Result:
        def __init__(self, v): self.v = v
        def scalar(self): return self.v

    class DB:
        def __init__(self): self.rows = {}
        def execute(self, stmt, p):
            if str(stmt).startswith('SELECT'):
                return Result(self.rows.get((p['id'], p['v'])))
            self.rows[(p['id'], p['v'])] = p['p']
    db = DB()
    for s in SCENARIOS.values():  # 기존 DB: 1.1만 적재된 상태
        db.rows[(s['id'], 'CATALOG-MVP-1.1')] = json.dumps(s, ensure_ascii=False, sort_keys=True)
    assert catalog_risk.seed(db) == 26
    assert sum(1 for _, v in db.rows if v == 'FOOD-3LEVEL-1.2') == 26
    assert sum(1 for _, v in db.rows if v == 'CATALOG-MVP-1.1') == 26
    assert catalog_risk.seed(db) == 26  # 다시 실행해도 같다
