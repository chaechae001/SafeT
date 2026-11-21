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
    p=edits(d);p['items'][0]['none']=True;p['items'][0]['controls_reviewed']=True
    r=client.put(url,headers=h,json=p);assert r.status_code==200,r.text
    # FOOD-3LEVEL-1.2 · FRY S2: 현재 조치 없음 → 중, 계획 전체 이행 가정 → 하
    d=r.json();assert d['items'][0]['signal']=='Y' and d['items'][0]['after']=='N'
    assert d['items'][0]['catalog']['current_result']['policy_version']=='FOOD-3LEVEL-1.2'
    p=edits(d)
    for a in p['items'][0]['plans']:a['checked']=True
    r=client.put(url,headers=h,json=p);assert r.status_code==200,r.text
    d=r.json();assert d['items'][0]['signal']=='Y' and d['items'][0]['after']=='G'
    assert d['items'][0]['catalog']['projected_result']['grade']=='하'
    critical={a['id'] for a in d['items'][0]['curr'] if a['control'].get('critical')}
    p=edits(d);p['items'][0]['none']=False;p['items'][0]['controls_reviewed']=True
    for a in p['items'][0]['curr']:a['checked']=a['id'] in critical  # 핵심만 현재 시행 → 중
    p['items'][0]['owner']={'type':'R','name':'근로자'};p['items'][0]['due']='2026-12-01'
    r=client.post(url+'/confirm',headers=h,json=p);assert r.status_code==200,r.text
    assert r.json()['items'][0]['signal']=='Y'
    assert client.put(url,headers=h,json=p).status_code==409
    assert client.get(url,headers=h).json()['items'][0]['after']=='G'

def test_unanswered_and_free_text_do_not_get_low_grade(client,catalog_flow):
    h,_=catalog_flow;d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}";p=edits(d)
    assert client.post(url+'/confirm',headers=h,json=p).status_code==422
    p['items'][0]['curr'].append({'text':'교육 반복','checked':True})
    r=client.put(url,headers=h,json=p);assert r.status_code==200,r.text
    assert r.json()['items'][0]['signal']=='N'
    p=edits(r.json());p['items'][0]['signal']='G'
    assert client.put(url,headers=h,json=p).status_code==422

def test_clear_selections_and_stale_revision(client,catalog_flow):
    h,_=catalog_flow;d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}";p=edits(d)
    p['items'][0]['none']=True;p['items'][0]['controls_reviewed']=True
    for a in p['items'][0]['plans']:a['checked']=True
    d=client.put(url,headers=h,json=p).json()
    assert client.put(url,headers=h,json=p).status_code==409
    p=edits(d)
    for a in p['items'][0]['plans']:a['checked']=False
    d=client.put(url,headers=h,json=p).json();assert d['items'][0]['after']=='N'
    p=edits(d);p['items'][0]['none']=False;p['items'][0]['controls_reviewed']=True
    d=client.put(url,headers=h,json=p).json();assert d['items'][0]['signal']=='N'

def test_candidate_search_and_legacy_snapshot(client,catalog_flow):
    h,p=catalog_flow;d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}"
    assert client.post(url+'/items',headers=h,json={'revision':1,'keyword':'튀김기'}).status_code==409
    assert client.post(url+'/items',headers=h,json={'revision':1,'keyword':'zzzz'}).status_code==422
    p=copy.deepcopy(p);p['request_key']=str(uuid.uuid4());p.pop('catalog_ids');p['text']='튀김기'
    r=client.post('/evals',headers=h,json=p);assert r.status_code==201,r.text
    import json
    state=d['items'][0]['catalog'];state['scenario']['policy_version']='CATALOG-MVP-1.0'
    with engine.begin() as c:c.execute(text('UPDATE eval_dtl SET catalog_state=:s WHERE eval_dtl_no=:n'),{'s':json.dumps(state),'n':d['items'][0]['id']})
    assert client.get(url,headers=h).status_code==200
    assert client.put(url,headers=h,json=edits(d)).status_code==409


def test_review_required_and_projection_does_not_change_current(client,catalog_flow):
    h,p=catalog_flow
    # FOOD-3LEVEL-1.2 · 휴업 부상(S2) 작업: 현재 핵심 조치 없음은 중, 모든 계획 이행 가정은 하.
    with engine.connect() as c:
        scenario=next(s for s in catalog_risk.list_catalog(c) if s['severity']==2)
    p['catalog_ids']=[scenario['id']]
    d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}"
    body=edits(d);body['items'][0]['none']=True
    for a in body['items'][0]['plans']:a['checked']=True
    r=client.put(url,headers=h,json=body);assert r.status_code==200,r.text
    d=r.json();assert d['items'][0]['signal']=='N' and d['items'][0]['after']=='N'
    body=edits(d);body['items'][0]['controls_reviewed']=True
    r=client.put(url,headers=h,json=body);assert r.status_code==200,r.text
    d=r.json();assert d['items'][0]['signal']=='Y' and d['items'][0]['after']=='G'
    assert d['items'][0]['catalog']['projected_result']['kind']=='projected'
    assert client.get(url,headers=h).json()['items'][0]['after']=='G'
    body=edits(d)
    for a in body['items'][0]['plans']:a['checked']=False
    body['items'][0]['plans'].append({'text':'직접 추가한 미검토 대책','checked':True})
    r=client.put(url,headers=h,json=body);assert r.status_code==200,r.text
    assert r.json()['items'][0]['after']=='Y'  # 직접 추가는 계산 제외 → 현재와 같은 중
    # 목록 확인 해제 시 기존 계산 결과를 확정 신호로 유지하지 않는다.
    body=edits(r.json());body['items'][0]['controls_reviewed']=False
    r=client.put(url,headers=h,json=body);assert r.status_code==200,r.text
    assert r.json()['items'][0]['signal']=='N' and r.json()['items'][0]['after']=='N'


def test_final_policy_to_signed_shared_pdf(client,catalog_flow):
    """최종 계산 결과가 PR19 문서·서명·공유 흐름까지 유지된다."""
    import base64, io
    from PIL import Image
    from urllib.parse import urlparse, parse_qs
    from services.report_service import build_context
    h,_=catalog_flow;d=create(client,catalog_flow);url=f"/evals/{d['eval_no']}"
    body=edits(d);it=body['items'][0]
    it.update(none=True,controls_reviewed=True,owner={'type':'R','name':'근로자'},due='2026-12-01')
    for a in it['plans']:a['checked']=True
    res=client.post(url+'/confirm',headers=h,json=body)
    assert res.status_code==200,res.text
    assert (res.json()['items'][0]['signal'],res.json()['items'][0]['after'])==('Y','G')  # 1.2 · FRY S2
    with engine.connect() as c:
        ctx=build_context(d['eval_no'],lambda sql,p:list(c.execute(text(sql),p).mappings()))
    assert (ctx['rows'][0]['grade'],ctx['rows'][0]['after'])==('Y','G')
    assert client.get(url+'/report',headers=h).content.startswith(b'%PDF')
    assert client.post(url+'/share',headers=h).status_code==409
    image=io.BytesIO();Image.new('RGB',(100,50),'white').save(image,format='PNG')
    signature='data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()
    for member in client.get(url+'/signs',headers=h).json()['members']:
        res=client.post(url+'/signs',headers=h,json={'member_no':member['member_no'],'confirm':True,'sign_img':signature})
        assert res.status_code==201,res.text
    res=client.post(url+'/share',headers=h);assert res.status_code==200,res.text
    token=parse_qs(urlparse(res.json()['share']['url']).query)['t'][0]
    assert client.get('/share/'+token+'/pdf').content.startswith(b'%PDF')
    assert client.post(url+'/share/stop',headers=h).status_code==200
    assert client.get('/share/'+token+'/pdf').status_code==410
