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

@pytest.mark.parametrize('severity,band,grade',[(1,1,'하'),(1,2,'중'),(1,3,'중'),(2,1,'중'),(2,2,'중'),(2,3,'상'),(3,1,'중'),(3,2,'상'),(3,3,'상')])
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
