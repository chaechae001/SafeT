"""AI 후보·질문과 공통 현재/예상 판정의 DB 통합 검사. 모델 응답은 모의값이다."""
import copy
import pytest
from sqlalchemy import text
from test_catalog_flow import catalog_flow
from test_assessment import flow,create,edits
from conftest import engine
from services import catalog_ai
from services.auth import AuthError

@pytest.fixture
def ai_flow(catalog_flow,monkeypatch):
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE','catalog_ai_v1')
    monkeypatch.setenv('SAFET_AI_BASE_URL','https://model.invalid/v1');monkeypatch.setenv('SAFET_AI_MODEL','synthetic-test')
    report={'candidates':[{'scenario_id':'FRY','rationale':'튀김 작업 보고','evidence':[{'media_id':'TEXT','statement':'튀김 작업'}],
                          'questions':[{'id':'Q1','text':'실제로 튀김 작업을 하나요?'}]}],'unmatched_risks':[]}
    monkeypatch.setattr(catalog_ai,'request_analysis',lambda *a:copy.deepcopy(report))
    yield catalog_flow,report


def test_ai_questions_common_grades_preserved_inputs(client,ai_flow):
    flow,report=ai_flow;h,_=flow;doc=create(client,flow);url=f"/evals/{doc['eval_no']}";item=doc['items'][0]
    assert doc['generation_source']=='catalog_ai_v1'
    assert item['signal']=='N' and not any(a['checked'] for a in item['curr']+item['plans'])
    body=edits(doc);body['items'][0]['none']=True;body['items'][0]['controls_reviewed']=True
    for a in body['items'][0]['plans']:a['checked']=True
    body['items'][0].update(owner={'type':'R','name':'근로자'},due='2026-12-01')
    r=client.put(url,headers=h,json=body);assert r.status_code==200,r.text
    doc=r.json();assert doc['items'][0]['signal']=='N' and doc['items'][0]['after']=='N'
    assert client.post(url+'/confirm',headers=h,json=edits(doc)).status_code==422
    report['candidates'][0]['questions']=[]
    answer={'revision':doc['revision'],'answers':[{'item_id':item['id'],'question_id':'Q1','answer':'실제로 튀김을 합니다.'}]}
    r=client.post(url+'/risk-answers',headers=h,json=answer);assert r.status_code==200,r.text
    doc=r.json();assert doc['items'][0]['owner']['name']=='근로자' and all(a['checked'] for a in doc['items'][0]['plans'])
    assert not doc['items'][0]['controls_reviewed']
    assert client.post(url+'/risk-answers',headers=h,json=answer).status_code==409
    body=edits(doc);body['items'][0]['controls_reviewed']=True
    r=client.put(url,headers=h,json=body);assert r.status_code==200,r.text
    doc=r.json();assert doc['items'][0]['signal']=='Y' and doc['items'][0]['after']=='G'  # 1.2 · FRY S2
    r=client.post(url+'/confirm',headers=h,json=edits(doc));assert r.status_code==200,r.text
    assert client.post(url+'/risk-answers',headers=h,json={'revision':r.json()['revision'],'answers':answer['answers']}).status_code==409
    assert client.get(url,headers=h).json()['items'][0]['catalog']['ai_analysis']['model']=='synthetic-test'


def test_invalid_answers_and_upstream_failure_rollback(client,ai_flow,monkeypatch):
    flow,_=ai_flow;h,_=flow;doc=create(client,flow);url=f"/evals/{doc['eval_no']}"
    answer={'revision':doc['revision'],'answers':[{'item_id':doc['items'][0]['id'],'question_id':'FOREIGN','answer':'확인'}]}
    assert client.post(url+'/risk-answers',headers=h,json=answer).status_code==422
    answer['answers'][0]['question_id']='Q1'
    def fail(*args):raise AuthError(503,'AI_REQUEST_FAILED','재시도')
    monkeypatch.setattr(catalog_ai,'request_analysis',fail)
    assert client.post(url+'/risk-answers',headers=h,json=answer).status_code==503
    assert client.get(url,headers=h).json()==doc


def test_unanswered_questions_cannot_disappear(client,ai_flow):
    flow,report=ai_flow;h,_=flow
    report['candidates'][0]['questions'].append({'id':'Q2','text':'작업 위치는 어디인가요?'})
    doc=create(client,flow);url=f"/evals/{doc['eval_no']}";report['candidates'][0]['questions']=[]
    answer={'revision':doc['revision'],'answers':[{'item_id':doc['items'][0]['id'],'question_id':'Q1','answer':'예'}]}
    r=client.post(url+'/risk-answers',headers=h,json=answer);assert r.status_code==502,r.text
    assert client.get(url,headers=h).json()==doc


def test_failed_initial_analysis_creates_no_document(client,ai_flow):
    flow,report=ai_flow;h,p=flow;report['candidates'][0]['scenario_id']='INVENTED'
    r=client.post('/evals',headers=h,json=p);assert r.status_code==502,r.text
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM eval_mst WHERE request_key=:k'),{'k':p['request_key']}).scalar()==0


def test_other_user_cannot_reanalyze(client,ai_flow,monkeypatch):
    from test_workplaces import make_login
    flow,_=ai_flow;h,_=flow;doc=create(client,flow)
    # 기존 계정 토큰을 제거한 요청은 모델을 호출하기 전에 차단한다.
    answer={'revision':doc['revision'],'answers':[{'item_id':doc['items'][0]['id'],'question_id':'Q1','answer':'예'}]}
    def unexpected(*args):raise AssertionError('인증 실패 요청에서 모델 호출 금지')
    monkeypatch.setattr(catalog_ai,'request_analysis',unexpected)
    assert client.post(f"/evals/{doc['eval_no']}/risk-answers",json=answer).status_code==401
    assert client.post(f"/evals/{doc['eval_no']+100000}/risk-answers",headers=h,json=answer).status_code==404


def test_keyword_uses_original_ai_source(client,ai_flow,monkeypatch):
    flow,report=ai_flow;h,_=flow;doc=create(client,flow)
    report['candidates'][0].update(scenario_id='KNIFE_STORAGE',questions=[])
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE','demo')
    r=client.post(f"/evals/{doc['eval_no']}/items",headers=h,json={'revision':doc['revision'],'keyword':'칼 보관'})
    assert r.status_code==200,r.text
    assert r.json()['generation_source']=='catalog_ai_v1'
    assert len(r.json()['items'])==2
    assert r.json()['items'][1]['signal']=='N'
