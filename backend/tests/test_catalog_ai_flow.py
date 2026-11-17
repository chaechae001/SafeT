"""합성 추출 응답으로 DB ID 연결·미확인·공통 계산·트랜잭션을 검사한다."""
import copy
import uuid
import pytest
from sqlalchemy import text
from conftest import engine
from test_assessment import flow, create, edits
from services import catalog_ai as ai, catalog_risk
from services.auth import AuthError


def synthetic(input_data,candidates,previous=None,*,unknown=False):
    s=next(s for s in candidates if s['id']=='FRY')
    source=next(m for m in input_data['media'] if m['id']=='TEXT')
    return dict(evidence=[dict(id='E1',media_id='TEXT',kind='reported',statement=source['content'])],
        matches=[dict(scenario_id='FRY',applicability='confirmed',evidence_ids=['E1'],uncertainties=[],
          controls=[dict(control_id=c['id'],state='unknown' if unknown else 'absent',evidence_ids=[] if unknown else ['E1']) for c in s['controls']])],unmatched_observations=[])


@pytest.fixture
def ai_flow(flow,monkeypatch):
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE',ai.SOURCE)
    monkeypatch.setattr(ai,'request_analysis',synthetic)
    with engine.begin() as c: catalog_risk.seed(c)
    yield flow
    h,p=flow
    with engine.begin() as c:
        c.execute(text('DELETE FROM risk_event WHERE eval_no IN (SELECT eval_no FROM eval_mst WHERE request_key=:k)'),{'k':p['request_key']})


def test_common_policy_roundtrip_and_lock(client,ai_flow):
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    assert d['generation_source']==ai.SOURCE
    it=d['items'][0];assert it['signal']=='R' and it['none']
    assert it['catalog']['scenario']['policy_version']=='CATALOG-MVP-1.0'
    assert it['catalog']['ai']['evidence'][0]['media_id']=='TEXT'
    assert not d['risk_assessment']['questions']
    assert create(client,ai_flow)['eval_no']==d['eval_no']
    p=edits(d)
    for a in p['items'][0]['plans']:a['checked']=True
    d=client.put(url,headers=h,json=p).json()
    assert d['items'][0]['signal']=='R' and d['items'][0]['after']=='Y'
    p=edits(d);p['items'][0]['none']=False
    for a in p['items'][0]['curr']:a['checked']=True
    p['items'][0]['owner']={'type':'R','name':'근로자'};p['items'][0]['due']='2026-12-01'
    r=client.post(url+'/confirm',headers=h,json=p);assert r.status_code==200,r.text
    assert r.json()['items'][0]['signal']=='Y' # S3도 main 공통 정책과 동일
    assert client.put(url,headers=h,json=p).status_code==409
    assert client.post(url+'/risk-answers',headers=h,json={'revision':r.json()['revision']}).status_code==409
    assert client.get(url,headers=h).json()['items'][0]['catalog']['scenario']['source_refs']


def test_unknown_answers_and_revision(client,ai_flow,monkeypatch):
    monkeypatch.setattr(ai,'request_analysis',lambda *a,**k:synthetic(*a,**k,unknown=True))
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    assert d['items'][0]['signal']=='N' and d['risk_assessment']['questions']
    p=edits(d);p['items'][0]['curr'][0]['checked']=True
    r=client.put(url,headers=h,json=p);assert r.status_code==200,r.text
    d=r.json();assert d['items'][0]['signal']=='N'
    assert client.post(url+'/confirm',headers=h,json=edits(d,True)).status_code==422
    bad={'revision':d['revision'],'answers':[{'question_id':'forged','answer':'yes'}]}
    assert client.post(url+'/risk-answers',headers=h,json=bad).status_code==400
    monkeypatch.setattr(ai,'request_analysis',synthetic)
    body={'revision':d['revision'],'answers':[{'question_id':q['id'],'answer':'현장에서 없음 확인'} for q in d['risk_assessment']['questions']]}
    r=client.post(url+'/risk-answers',headers=h,json=body);assert r.status_code==200,r.text
    after=r.json();assert not after['risk_assessment']['questions']
    assert after['items'][0]['curr'][0]['checked'] # 기존 사용자 선택 보존
    assert client.post(url+'/risk-answers',headers=h,json=body).status_code==409


@pytest.mark.parametrize('kind',['scenario','control','evidence','shape','duplicate','grade','omitted_control'])
def test_invalid_model_leaves_no_document(client,ai_flow,monkeypatch,kind):
    def invalid(*args):
        r=synthetic(*args);m=r['matches'][0]
        if kind=='scenario':m['scenario_id']='UNKNOWN'
        if kind=='control':m['controls'][0]['control_id']='UNKNOWN'
        if kind=='evidence':m['evidence_ids']=['UNKNOWN']
        if kind=='shape':m['controls'][0]['state']='safe'
        if kind=='duplicate':r['matches'].append(copy.deepcopy(m))
        if kind=='grade':m['grade']='하'
        if kind=='omitted_control':m['controls'].pop()
        return r
    monkeypatch.setattr(ai,'request_analysis',invalid)
    h,p=ai_flow;r=client.post('/evals',headers=h,json=p);assert r.status_code==502,r.text
    with engine.connect() as c:assert c.execute(text('SELECT COUNT(*) FROM eval_mst WHERE request_key=:k'),{'k':p['request_key']}).scalar()==0


@pytest.mark.parametrize('status,code',[(503,'RISK_MODEL_FAILED'),(502,'RISK_RESPONSE_INVALID')])
def test_reanalysis_failure_keeps_data(client,ai_flow,monkeypatch,status,code):
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    def fail(*a):raise AuthError(status,code,'synthetic failure')
    monkeypatch.setattr(ai,'request_analysis',fail)
    r=client.post(url+'/risk-answers',headers=h,json={'revision':1,'additional_text':'재확인'})
    assert r.status_code==status
    assert client.get(url,headers=h).json()==d


def test_ownership_and_request_contract(client,ai_flow):
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    assert client.post(url+'/risk-answers',json={'revision':1}).status_code==401
    from test_workplaces import make_login
    from conftest import purge_user_rows
    other_email='other-'+uuid.uuid4().hex[:10]+'@test.invalid'
    other=make_login(client,other_email)
    try:
        assert client.post(url+'/risk-answers',headers=other,json={'revision':1}).status_code==404
    finally:
        with engine.begin() as c:purge_user_rows(c,other_email)
    p=edits(d);p['items'][0]['signal']='G'
    assert client.put(url,headers=h,json=p).status_code==422


def test_possible_and_unmatched_block_confirmation(client,ai_flow,monkeypatch):
    def candidate(*a):
        r=synthetic(*a);r['matches'][0]['applicability']='possible';r['unmatched_observations']=['DB 외 관찰'];return r
    monkeypatch.setattr(ai,'request_analysis',candidate)
    h,_=ai_flow;d=create(client,ai_flow)
    assert d['items'][0]['signal']=='N' and len(d['risk_assessment']['questions'])==2
    r=client.post(f"/evals/{d['eval_no']}/confirm",headers=h,json=edits(d,True));assert r.status_code==422
