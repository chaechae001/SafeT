"""격리 MariaDB에서 생성·근거 저장·재조회·변조 거절·확정 잠금을 검사한다."""
import copy
import pytest
from sqlalchemy import text
from test_assessment import flow, create, edits
from conftest import engine
from services import authoring_rag
from services.catalog_risk import seed
from services.auth import AuthError


@pytest.fixture
def rag_flow(flow, monkeypatch):
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE',authoring_rag.SOURCE)
    with engine.begin() as c: seed(c)
    flow[1]['text']='주방에서 튀김기로 조리를 합니다.'
    def retrieval(*args,**kwargs):
        return dict(data_version='synthetic-test',index_sha256='test-hash',candidates=[dict(
            hazard_code='burn',equipment_ids=['EQ_FRYER'],source_ids=['SYNTHETIC-1'],
            hazard_texts=['합성 튀김기 화상 위험'],source_evidence=[dict(link_id='TEST-LINK',
                hazard_text='합성 튀김기 화상 위험',source_id='SYNTHETIC-1',source_file='synthetic.pdf',pdf_pages=[1])])])
    def extract(context,retrieval,snapshot,evidence):
        return dict(contract_version='assessment-authoring-1',candidates=[dict(scenario_id=c['scenario_id'],
            rationale='합성 모델 응답',evidence=[dict(media_id='TEXT',statement=context['media'][0]['text'])],
            control_evidence=[],assumptions=[],questions=[]) for c in retrieval['candidates']],unmatched_risks=[])
    monkeypatch.setattr(authoring_rag,'qualified_candidates',retrieval)
    monkeypatch.setattr(authoring_rag,'extract',extract)
    return flow


def test_document_evidence_roundtrip_and_input_grade_survive_save(client,rag_flow):
    h,p=rag_flow;doc=create(client,rag_flow);no=doc['eval_no']
    assert doc['assessment_mode']=='input_based'
    item=doc['items'][0]
    assert item['signal']=='R' and item['curr']==[] and not item['none']
    assert item['document_evidence'][0]['source_evidence'][0]['source_id']=='SYNTHETIC-1'
    stored=copy.deepcopy(item['authoring'])
    change=edits(doc);change['items'][0]['plans'][0]['checked']=True
    response=client.put(f'/evals/{no}',headers=h,json=change)
    assert response.status_code==200,response.text
    fresh=client.get(f'/evals/{no}',headers=h).json()
    assert fresh['revision']==2 and fresh['items'][0]['plans'][0]['checked']
    assert fresh['items'][0]['authoring']==stored
    assert fresh['items'][0]['signal']=='R' and fresh['items'][0]['after']=='N'
    assert client.put(f'/evals/{no}',headers=h,json=change).status_code==409
    assert client.get(f'/evals/{no}').status_code==401
    confirm=edits(fresh)
    confirm['items'][0].update(owner={'type':'R','name':'근로자'},due='2026-12-01')
    blocked=client.post(f'/evals/{no}/confirm',headers=h,json=confirm)
    assert blocked.status_code==422 and blocked.json()['detail']['code']=='WORK_REVIEW_REQUIRED'
    confirm['items'][0]['work_reviewed']=True
    done=client.post(f'/evals/{no}/confirm',headers=h,json=confirm)
    assert done.status_code==200,done.text
    final=client.get(f'/evals/{no}',headers=h).json()
    assert final['eval_status']=='C' and final['items'][0]['authoring']==stored
    assert client.put(f'/evals/{no}',headers=h,json=edits(final)).status_code==409


def test_client_cannot_overwrite_current_or_document_evidence(client,rag_flow):
    h,p=rag_flow;doc=create(client,rag_flow);no=doc['eval_no']
    for field,value in [('document_evidence',[]),('authoring',{}),('signal','G')]:
        body=edits(doc);body['items'][0][field]=value
        assert client.put(f'/evals/{no}',headers=h,json=body).status_code==422
    body=edits(doc);body['items'][0]['none']=True
    denied=client.put(f'/evals/{no}',headers=h,json=body)
    assert denied.status_code==400 and denied.json()['detail']['code']=='AUTHORING_CURRENT_IMMUTABLE'
    assert client.get(f'/evals/{no}',headers=h).json()==doc


def test_control_quotes_and_excluded_candidates_survive_confirm(client,rag_flow,monkeypatch):
    """조치별 입력 원문, 확정본 제외 이력(읽을 수 있는 작업명), 원문 연결 이전 저장본 표시."""
    h,p=rag_flow
    p['text']='주방 통로를 오가며 음식을 나릅니다. 통로 옆에 튀김기가 있습니다. 바닥은 매일 닦아 기름을 제거합니다.'
    def retrieval(*args,**kwargs):
        return dict(data_version='synthetic-test',index_sha256='test-hash',candidates=[dict(
            hazard_code=code,equipment_ids=['EQ_FRYER'],source_ids=['SYNTHETIC-'+code],hazard_texts=['합성 '+code],
            source_evidence=[dict(link_id='TEST-'+code,hazard_text='합성 '+code,source_id='SYNTHETIC-'+code,
                                  source_file='synthetic.pdf',pdf_pages=[1])]) for code in ('burn','slip')])
    def extract(context,retrieval,snapshot,evidence):
        return dict(contract_version='assessment-authoring-1',candidates=[dict(scenario_id='ENV',rationale='합성',
            evidence=[dict(media_id='TEXT',statement='주방 통로를 오가며 음식을 나릅니다.')],
            control_evidence=[dict(control_id='ENV-C1',state='supported',evidence_refs=['TEXT'],statement='바닥은 매일 닦아 기름을 제거합니다.')],
            assumptions=[],questions=[]) for c in retrieval['candidates'] if c['scenario_id']=='ENV'],unmatched_risks=[])
    monkeypatch.setattr(authoring_rag,'qualified_candidates',retrieval)
    monkeypatch.setattr(authoring_rag,'extract',extract)
    doc=create(client,rag_flow);no=doc['eval_no'];item=doc['items'][0]
    assert [c['scenario_id'] for c in doc['review_candidates']]==['FRY']
    details={c['control_id']:c for c in item['authoring']['row']['control_details']}
    assert details['ENV-C1']['statement']=='바닥은 매일 닦아 기름을 제거합니다.' and details['ENV-C1']['state']=='supported'
    assert details['ENV-C2']['state']=='unknown' and details['ENV-C2']['statement']==''
    assert '합성 slip' not in item['reason']
    body=edits(doc);body['excluded_review_candidates']=['FRY']
    body['items'][0].update(work_reviewed=True,owner={'type':'R','name':'근로자'},due='2026-12-01')
    body['items'][0]['plans'][0]['checked']=True
    assert client.put(f'/evals/{no}',headers=h,json=body).status_code==200
    body['revision']=2
    assert client.post(f'/evals/{no}/confirm',headers=h,json=body).status_code==200
    final=client.get(f'/evals/{no}',headers=h).json()
    review=final['items'][0]['work_review']
    assert review['excluded_details']==[dict(scenario_id='FRY',task='튀김 조리',reason='work_unconfirmed')]
    with engine.begin() as c:
        c.execute(text("UPDATE eval_dtl SET catalog_state=JSON_REMOVE(catalog_state,'$.authoring.row.control_details') WHERE eval_no=:n"),{'n':no})
    legacy=client.get(f'/evals/{no}',headers=h).json()['items'][0]['authoring']['row']['control_details']
    assert {c['control_id']:c['statement'] for c in legacy}['ENV-C1']=='바닥은 매일 닦아 기름을 제거합니다.'


def test_search_failure_does_not_create_partial_db_record(client,rag_flow,monkeypatch):
    h,p=rag_flow
    def fail(*args,**kwargs):raise AuthError(503,'RAG_DATA_UNAVAILABLE','검색 실패 시험')
    monkeypatch.setattr(authoring_rag,'qualified_candidates',fail)
    assert client.post('/evals',headers=h,json=p).status_code==503
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM eval_mst WHERE request_key=:k'),{'k':p['request_key']}).scalar()==0


def test_idempotency_and_unsupported_operations(client,rag_flow):
    h,p=rag_flow;doc=create(client,rag_flow);no=doc['eval_no']
    assert create(client,rag_flow)['eval_no']==no
    r=client.post(f'/evals/{no}/items',headers=h,json={'revision':1,'keyword':'새 작업'})
    assert r.status_code==409 and r.json()['detail']['code']=='AUTHORING_ADD_UNSUPPORTED'
    assert client.post(f'/evals/{no}/risk-answers',headers=h,json={'revision':1,'answers':[]}).status_code in (409,422)
