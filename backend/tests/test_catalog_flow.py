"""기존 화면 입력 형식으로 DB 기준 계산·저장·확정을 검사한다."""
import copy
import uuid
import pytest
from sqlalchemy import text
from test_assessment import flow, create, edits
from conftest import engine
from services import catalog_risk

@pytest.fixture
def catalog_flow(flow,monkeypatch):
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE','catalog_v1')
    with engine.begin() as c:
        assert catalog_risk.seed(c)==26
        assert catalog_risk.seed(c)==26
    h,p=flow;p['catalog_ids']=['FRY'];yield h,p
    with engine.begin() as c:c.execute(text('DELETE FROM risk_event WHERE actor IN (SELECT email FROM eval_mst WHERE request_key=:k)'),{'k':p['request_key']})

def test_current_and_projection_use_existing_input_contract(client,catalog_flow):
    h,_=catalog_flow;d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}"
    assert d['items'][0]['signal']=='N'
    p=edits(d);p['items'][0]['none']=True
    r=client.put(url,headers=h,json=p);assert r.status_code==200,r.text
    d=r.json();assert d['items'][0]['signal']=='R' and d['items'][0]['after']=='N'
    p=edits(d)
    for a in p['items'][0]['plans']:a['checked']=True
    r=client.put(url,headers=h,json=p);assert r.status_code==200,r.text
    d=r.json();assert d['items'][0]['signal']=='R' and d['items'][0]['after']=='Y'
    assert d['items'][0]['catalog']['projected_result']['grade']=='중'
    p=edits(d);p['items'][0]['none']=False
    for a in p['items'][0]['curr']:a['checked']=True
    p['items'][0]['owner']={'type':'R','name':'근로자'};p['items'][0]['due']='2026-12-01'
    r=client.post(url+'/confirm',headers=h,json=p);assert r.status_code==200,r.text
    assert r.json()['items'][0]['signal']=='Y'
    assert client.put(url,headers=h,json=p).status_code==409
    assert client.get(url,headers=h).json()['items'][0]['after']=='Y'

def test_unanswered_and_free_text_do_not_get_low_grade(client,catalog_flow):
    h,_=catalog_flow;d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}";p=edits(d)
    assert client.post(url+'/confirm',headers=h,json=p).status_code==422
    p['items'][0]['curr'].append({'text':'교육 반복','checked':True})
    r=client.put(url,headers=h,json=p);assert r.status_code==200,r.text
    assert r.json()['items'][0]['signal']=='R'
    p=edits(r.json());p['items'][0]['signal']='G'
    assert client.put(url,headers=h,json=p).status_code==422

def test_clear_selections_and_stale_revision(client,catalog_flow):
    h,_=catalog_flow;d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}";p=edits(d)
    p['items'][0]['none']=True
    for a in p['items'][0]['plans']:a['checked']=True
    d=client.put(url,headers=h,json=p).json()
    assert client.put(url,headers=h,json=p).status_code==409
    p=edits(d)
    for a in p['items'][0]['plans']:a['checked']=False
    d=client.put(url,headers=h,json=p).json();assert d['items'][0]['after']=='N'
    p=edits(d);p['items'][0]['none']=False
    d=client.put(url,headers=h,json=p).json();assert d['items'][0]['signal']=='N'

def test_candidate_search_and_legacy_snapshot(client,catalog_flow):
    h,p=catalog_flow;d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}"
    assert client.post(url+'/items',headers=h,json={'revision':1,'keyword':'튀김기'}).status_code==409
    assert client.post(url+'/items',headers=h,json={'revision':1,'keyword':'zzzz'}).status_code==422
    p=copy.deepcopy(p);p['request_key']=str(uuid.uuid4());p.pop('catalog_ids');p['text']='튀김기'
    r=client.post('/evals',headers=h,json=p);assert r.status_code==201,r.text
    import json
    state=d['items'][0]['catalog'];state['scenario']['policy_version']='CATALOG-3LEVEL-1.0'
    with engine.begin() as c:c.execute(text('UPDATE eval_dtl SET catalog_state=:s WHERE eval_dtl_no=:n'),{'s':json.dumps(state),'n':d['items'][0]['id']})
    assert client.get(url,headers=h).status_code==200
    assert client.put(url,headers=h,json=edits(d)).status_code==409
