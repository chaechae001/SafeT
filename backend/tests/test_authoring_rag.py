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

@pytest.mark.parametrize('description,reason', [
    ('튀김기는 안 씁니다.', 'input_denies_work'),
    ('튀김기는 사용하지 않습니다.', 'input_denies_work'),
    ('튀김기가 있습니다.', 'work_unconfirmed'),
])
def test_candidate_only_draft(client, rag_flow, monkeypatch, description, reason):
    headers, payload = rag_flow
    payload['text'] = description
    monkeypatch.setattr(authoring_rag, 'extract', lambda *args: dict(
        contract_version='assessment-authoring-1', candidates=[], unmatched_risks=[]))
    doc = create(client, rag_flow)
    path = f"/evals/{doc['eval_no']}"
    assert doc['items'] == []
    assert doc['result_status'] == 'no_supported_result'
    assert {'scenario_id': 'FRY', 'reason': reason} in doc['review_candidates']
    if reason == 'input_denies_work':
        assert doc['review_candidates'] == [{'scenario_id':'FRY', 'reason':reason}]
    assert create(client, rag_flow)['eval_no'] == doc['eval_no']
    saved = client.put(path, headers=headers, json=edits(doc))
    assert saved.status_code == 200, saved.text
    current = client.get(path, headers=headers).json()
    assert current['review_candidates'] == doc['review_candidates']
    assert current['revision'] == 2
    denied = client.post(path+'/confirm', headers=headers, json=edits(current))
    assert denied.status_code == 422 and denied.json()['detail']['code'] == 'NO_ASSESSED_ROWS'
    assert client.get(path, headers=headers).json() == current

def test_mixed_draft_exclusions_survive_and_unresolved_candidates_block_confirm(client, rag_flow, monkeypatch):
    headers, payload = rag_flow
    payload['text'] = '튀김기는 안 씁니다. 통로 이동을 합니다.'
    monkeypatch.setattr(authoring_rag, 'extract', lambda *args: dict(
        contract_version='assessment-authoring-1', candidates=[dict(
            scenario_id='ENV', rationale='합성 모델 응답',
            evidence=[dict(media_id='TEXT', statement='통로 이동을 합니다.')],
            control_evidence=[], assumptions=[], questions=[])], unmatched_risks=[]))
    doc = create(client, rag_flow)
    path = f"/evals/{doc['eval_no']}"
    assert len(doc['items']) == 1
    assert doc['review_candidates'] == [{'scenario_id': 'FRY', 'reason': 'input_denies_work'}]
    assert doc['excluded_review_candidates'] == []
    change = edits(doc)
    change['excluded_review_candidates'] = ['FRY']
    saved = client.put(path, headers=headers, json=change)
    assert saved.status_code == 200, saved.text

    fresh = client.get(path, headers=headers).json()
    assert fresh['excluded_review_candidates'] == ['FRY']
    saved_again = client.put(path, headers=headers, json=edits(fresh))
    assert saved_again.status_code == 200, saved_again.text
    assert saved_again.json()['excluded_review_candidates'] == ['FRY']

    finish = edits(saved_again.json())
    finish['items'][0].update(work_reviewed=True, owner={'type':'R','name':'근로자'}, due='2026-12-01')
    finish['items'][0]['plans'][0]['checked'] = True
    blocked = client.post(path+'/confirm', headers=headers, json=dict(finish, excluded_review_candidates=[]))
    assert blocked.status_code == 422
    assert blocked.json()['detail']['code'] == 'CANDIDATE_REVIEW_REQUIRED'
    assert client.get(path, headers=headers).json() == saved_again.json()
    confirmed = client.post(path+'/confirm', headers=headers, json=finish)
    assert confirmed.status_code == 200, confirmed.text
    final = client.get(path, headers=headers).json()
    assert final['eval_status'] == 'C'
    assert final['items'][0]['work_review']['excluded_candidates'] == ['FRY']
