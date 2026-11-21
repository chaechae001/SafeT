import itertools
from types import SimpleNamespace
from ai.risk_law_search.scenario_map import load_catalog
from ai.risk_law_search.grading import grade_selection
catalog=load_catalog()
linker=SimpleNamespace(by_id={s['id']:s for s in catalog['scenarios']}, map={'card':{}})
n=0
for s in catalog['scenarios']:
    controls=[c['id'] for c in s['controls']]
    critical={c['id'] for c in s['controls'] if c['critical']}
    for bits in itertools.product((False,True),repeat=len(controls)):
        current={k for k,on in zip(controls,bits) if on}
        body=dict(card_id='card',scenario_id=s['id'],current_ids=list(current),plan_ids=list(set(controls)-current),reviewed=True,maintain=True)
        r=grade_selection(linker,body)
        col=2 if critical-current else int(set(controls)!=current)
        expected=[['하','하','중'],['하','중','중'],['중','중','상']][s['severity']-1]
        assert 'current_risk' not in r and r['expected_risk']==expected[0]
        assert grade_selection(linker,{**body,'plan_ids':[]})['expected_risk']==expected[col]
        n+=1
    assert grade_selection(linker,body,draft=True)['current_risk']==expected[2]
    assert 'expected_risk' not in grade_selection(linker,body,draft=True)
    assert grade_selection(linker,{**body,'plan_ids':[],'maintain':False})['expected_risk']==expected[0]
    try: grade_selection(linker,{**body,'plan_ids':['foreign']})
    except ValueError: pass
    else: raise AssertionError('foreign control')
print(n,'current/projected combinations OK')
