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
    return dict(evidence=[dict(id='E1',media_id='TEXT',kind='reported',time_scope='current',statement=source['content'])],
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
    assert r.json()['items'][0]['signal']=='Y' # 현재 조치 충족 결과는 main 공통 정책과 동일
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
    after=r.json();assert after['risk_assessment']['questions'] # 기존 선택과 새 부재 근거의 상충은 확인 필요
    assert after['items'][0]['curr'][0]['checked'] # 기존 사용자 선택 보존
    assert client.post(url+'/risk-answers',headers=h,json=body).status_code==409


@pytest.mark.parametrize('kind',['scenario','control','evidence','shape','duplicate','grade','omitted_control','planned','unknown_time','missing_scope','planned_control'])
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
        if kind=='planned':r['evidence'][0]['time_scope']='planned'
        if kind=='unknown_time':r['evidence'][0]['time_scope']='unknown'
        if kind=='missing_scope':r['evidence'][0].pop('time_scope')
        if kind=='planned_control':
            r['evidence'].append({**r['evidence'][0],'id':'E2','time_scope':'planned'})
            m['controls'][0]['evidence_ids']=['E2']
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


@pytest.mark.parametrize('old_state,new_state',[('present','unknown'),('absent','unknown'),('present','absent'),('absent','present')])
def test_new_facts_do_not_reuse_stale_current_choice(client,ai_flow,monkeypatch,old_state,new_state):
    def response(state):
        def model(*args):
            r=synthetic(*args)
            for c in r['matches'][0]['controls']:
                c['state']=state;c['evidence_ids']=[] if state=='unknown' else ['E1']
            return r
        return model
    monkeypatch.setattr(ai,'request_analysis',response(old_state))
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    before=copy.deepcopy(d['items'][0])
    monkeypatch.setattr(ai,'request_analysis',response(new_state))
    r=client.post(url+'/risk-answers',headers=h,json={'revision':d['revision'],'additional_text':'현재 상태를 다시 확인해 주세요.'})
    assert r.status_code==200,r.text
    d=r.json()
    assert d['items'][0]['signal']=='N'
    assert d['items'][0]['curr']==before['curr'] and d['items'][0]['none']==before['none']
    assert d['risk_assessment']['questions']
    # 변경 없는 저장·계획 선택·확정으로 새 미확인/상충 정보를 지울 수 없다.
    payload=edits(d)
    for a in payload['items'][0]['plans']:a['checked']=True
    payload['items'][0]['owner']={'type':'R','name':'근로자'};payload['items'][0]['due']='2026-12-01'
    r=client.put(url,headers=h,json=payload);assert r.status_code==200,r.text
    d=r.json();assert d['items'][0]['signal']=='N' and d['items'][0]['after']=='N'
    assert client.post(url+'/confirm',headers=h,json=edits(d)).status_code==422


def test_answer_question_is_context_not_reported_fact(client,ai_flow,monkeypatch):
    monkeypatch.setattr(ai,'request_analysis',lambda *a:synthetic(*a,unknown=True))
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    q=d['risk_assessment']['questions'][0]
    def quote_question(input_data,candidates,previous):
        r=synthetic(input_data,candidates,previous)
        source=next(m for m in input_data['media'] if m['id'].startswith('ANSWER-'))
        r['evidence']=[dict(id='E1',media_id=source['id'],kind='reported',time_scope='current',statement=q['question'])]
        return r
    monkeypatch.setattr(ai,'request_analysis',quote_question)
    r=client.post(url+'/risk-answers',headers=h,json={'revision':d['revision'],'answers':[{'question_id':q['id'],'answer':'모르겠습니다.'}]})
    assert r.status_code==502,r.text
    assert client.get(url,headers=h).json()==d


@pytest.mark.parametrize('target',['present','absent'])
def test_explicit_current_edit_resolves_new_unknown(client,ai_flow,monkeypatch,target):
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    if target=='absent':
        p=edits(d);p['items'][0]['none']=False
        for a in p['items'][0]['curr']:a['checked']=True
        d=client.put(url,headers=h,json=p).json()
    monkeypatch.setattr(ai,'request_analysis',lambda *a:synthetic(*a,unknown=True))
    d=client.post(url+'/risk-answers',headers=h,json={'revision':d['revision'],'additional_text':'현재 상태 미확인'}).json()
    assert d['items'][0]['signal']=='N'
    p=edits(d);p['items'][0]['none']=target=='absent'
    for a in p['items'][0]['curr']:a['checked']=target=='present'
    r=client.put(url,headers=h,json=p);assert r.status_code==200,r.text
    d=r.json();assert not d['risk_assessment']['questions']
    assert d['items'][0]['signal']==('Y' if target=='present' else 'R')


def test_all_ai_endpoints_enforce_auth_and_ownership(client,ai_flow,monkeypatch):
    from test_workplaces import make_login
    from conftest import purge_user_rows
    h,p=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    other_email='other-'+uuid.uuid4().hex[:10]+'@test.invalid';other=make_login(client,other_email)
    cases=[('GET',url,None),('PUT',url,edits(d)),('POST',url+'/confirm',edits(d)),
           ('POST',url+'/items',{'revision':1,'keyword':'추가 작업'}),
           ('POST',url+'/risk-answers',{'revision':1}),('POST','/evals',{**p,'request_key':str(uuid.uuid4())})]
    def forbidden(*a):raise AssertionError('인증·소유권 검사 전에 모델을 호출하면 안 됨')
    monkeypatch.setattr(ai,'request_analysis',forbidden)
    try:
        for method,path,body in cases:
            for headers,status in [({},401),({'Authorization':'Bearer invalid-token'},401),(other,404)]:
                options={'headers':headers}
                if body is not None:options['json']=body
                r=client.request(method,path,**options);assert r.status_code==status,(path,r.text)
    finally:
        with engine.begin() as c:purge_user_rows(c,other_email)
    assert client.get(url,headers=h).json()==d


@pytest.mark.parametrize('winner',['answers','confirm'])
def test_concurrent_answers_and_confirm_respect_revision_and_lock(client,ai_flow,monkeypatch,winner):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from services import assessment as service
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    r=client.put(url,headers=h,json=edits(d,True));assert r.status_code==200,r.text
    d=r.json();body={'revision':d['revision'],'additional_text':'현재 상태 확인'};save_body=edits(d)
    entered=Event();release=Event();contender=Event();calls=[]
    original_owned=service.owned;original_validation=service.validation
    def observe_lock(db,email,no,lock=False):
        if lock and entered.is_set():contender.set()
        return original_owned(db,email,no,lock)
    def model(*a):
        calls.append(1)
        assert winner=='answers','확정 잠금 후 모델 호출 금지'
        entered.set();assert release.wait(15)
        return synthetic(*a)
    def validation(items):
        if winner=='confirm':entered.set();assert release.wait(15)
        return original_validation(items)
    monkeypatch.setattr(service,'owned',observe_lock)
    monkeypatch.setattr(service,'validation',validation)
    monkeypatch.setattr(ai,'request_analysis',model)
    def answers():return client.post(url+'/risk-answers',headers=h,json=body)
    def confirm():return client.post(url+'/confirm',headers=h,json=save_body)
    first,second=(answers,confirm) if winner=='answers' else (confirm,answers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(first)
        try:
            assert entered.wait(10)
            two=pool.submit(second)
            assert contender.wait(10)
        finally:release.set()
        a,b=one.result(timeout=15),two.result(timeout=15)
    assert a.status_code==200,a.text
    assert b.status_code==409,b.text
    assert b.json()['detail']['code']==('STALE_REVISION' if winner=='answers' else 'EVAL_LOCKED')
    final=client.get(url,headers=h).json()
    assert final['revision']==d['revision']+1
    assert final['eval_status']==('W' if winner=='answers' else 'C')
    assert len(calls)==(1 if winner=='answers' else 0)


def test_action_kind_forgery_rolls_back_ai_document(client,ai_flow):
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}";p=edits(d)
    p['items'][0]['curr'][0]=copy.deepcopy(p['items'][0]['plans'][0])
    r=client.put(url,headers=h,json=p);assert r.status_code==400,r.text
    assert client.get(url,headers=h).json()==d



def test_legacy_evidence_needs_reanalysis_before_confirmation(client,ai_flow):
    import json
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    with engine.begin() as c:
        raw=c.execute(text('SELECT risk_state FROM eval_mst WHERE eval_no=:n'),{'n':d['eval_no']}).scalar_one()
        old=json.loads(raw);old.pop('contract_version')
        for e in old['report']['evidence']:e.pop('time_scope')
        c.execute(text('UPDATE eval_mst SET risk_state=:s WHERE eval_no=:n'),{'s':json.dumps(old),'n':d['eval_no']})
        item_state=copy.deepcopy(d['items'][0]['catalog']);item_state['ai'].pop('contract_version')
        for e in item_state['ai']['evidence']:e.pop('time_scope')
        c.execute(text('UPDATE eval_dtl SET catalog_state=:s WHERE eval_dtl_no=:n'),{'s':json.dumps(item_state),'n':d['items'][0]['id']})
    d=client.get(url,headers=h).json()
    assert d['risk_assessment']['needs_reanalysis'] and d['items'][0]['signal']=='N'
    assert d['items'][0]['catalog']['current_result']['grade'] is None
    assert client.post(url+'/confirm',headers=h,json=edits(d,True)).status_code==422
    d=client.post(url+'/risk-answers',headers=h,json={'revision':d['revision'],'additional_text':'현재 상태 재확인'}).json()
    assert not d['risk_assessment']['needs_reanalysis'] and not d['risk_assessment']['questions']
    assert d['items'][0]['signal']=='R'


def test_many_questions_fit_one_answer_batch(client,ai_flow,monkeypatch):
    captured=[]
    def full_catalog(input_data,candidates,previous=None):
        r=synthetic(input_data,candidates,previous)
        matches=[]
        for scenario in candidates:
            match=copy.deepcopy(r['matches'][0]);match['scenario_id']=scenario['id']
            match['controls']=[dict(control_id=c['id'],state='absent' if previous else 'unknown',evidence_ids=['E1'] if previous else []) for c in scenario['controls']]
            matches.append(match)
        r['matches']=matches
        if previous:captured.append(input_data)
        return r
    monkeypatch.setattr(ai,'request_analysis',full_catalog)
    h,_=ai_flow;d=create(client,ai_flow);questions=d['risk_assessment']['questions']
    assert len(questions)>100
    r=client.post(f"/evals/{d['eval_no']}/risk-answers",headers=h,json={'revision':d['revision'],'answers':[{'question_id':q['id'],'answer':'없음 확인'} for q in questions]})
    assert r.status_code==200,r.text
    answer_media=[m for m in captured[0]['media'] if m['id'].startswith('ANSWER-')]
    assert len(answer_media)==1 and len(answer_media[0]['answers'])==len(questions)
    assert answer_media[0]['content']=='\n'.join('없음 확인' for q in questions)
    assert not r.json()['risk_assessment']['questions']



def test_legacy_confirmed_result_remains_readonly_history(client,ai_flow):
    import json
    h,_=ai_flow;d=create(client,ai_flow);url=f"/evals/{d['eval_no']}"
    r=client.post(url+'/confirm',headers=h,json=edits(d,True));assert r.status_code==200,r.text
    confirmed=r.json()
    with engine.begin() as c:
        raw=c.execute(text('SELECT risk_state FROM eval_mst WHERE eval_no=:n'),{'n':d['eval_no']}).scalar_one()
        state=json.loads(raw);state.pop('contract_version')
        c.execute(text('UPDATE eval_mst SET risk_state=:s WHERE eval_no=:n'),{'s':json.dumps(state),'n':d['eval_no']})
    history=client.get(url,headers=h).json()
    assert history['risk_assessment']['legacy_contract'] and not history['risk_assessment']['needs_reanalysis']
    assert history['items']==confirmed['items'] and history['revision']==confirmed['revision']
    assert client.put(url,headers=h,json=edits(history)).status_code==409
    assert client.post(url+'/risk-answers',headers=h,json={'revision':history['revision']}).status_code==409
