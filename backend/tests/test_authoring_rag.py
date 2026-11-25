"""격리 MariaDB에서 생성·근거 저장·재조회·변조 거절·확정 잠금을 검사한다."""
import copy
import io
from uuid import uuid4
import pytest
from pypdf import PdfReader
from sqlalchemy import text
from test_assessment import flow, create, edits
from conftest import engine
from services import authoring_rag, catalog_risk, risk_law
from services.catalog_risk import seed
from services.auth import AuthError


PHOTO = {
    'name': 'synthetic-fryer.png',
    'place': '주방',
    'data': ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8'
             '/x8AAwMCAO+aCuoAAAAASUVORK5CYII='),
}


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
    assert item['signal']=='Y' and item['curr']==[] and not item['none']
    assert item['document_evidence'][0]['source_evidence'][0]['source_id']=='SYNTHETIC-1'
    stored=copy.deepcopy(item['authoring'])
    change=edits(doc);change['items'][0]['plans'][0]['checked']=True
    response=client.put(f'/evals/{no}',headers=h,json=change)
    assert response.status_code==200,response.text
    fresh=client.get(f'/evals/{no}',headers=h).json()
    assert fresh['revision']==2 and fresh['items'][0]['plans'][0]['checked']
    assert fresh['items'][0]['authoring']==stored
    assert fresh['items'][0]['signal']=='Y' and fresh['items'][0]['after']=='Y'  # 1.2: FRY S2·핵심 미충족 → 중
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


def law_hit(sid):
    return dict(card_id='TEST-'+sid, title='합성 위험 '+sid, risk_type='화상',
                scenario={'scenario_id': sid, 'status': 'confirmed'},
                law={'law_name': '검수용 법령', 'locator': '제1조', 'article_title': '합성 조문'})


def law_result():
    return {'units': [
        dict(source='TEXT', text='주방에서 튀김기로 조리를 합니다.', risks=[law_hit('FRY'), law_hit('GAS'), law_hit('MIX')]),
        dict(source='MACHINE', text='튀김기', risks=[law_hit('FIRE')]),
        dict(source='MACHINE', text='반죽기', risks=[law_hit('MIX'), law_hit('CUT')]),
    ]}


@pytest.mark.parametrize('search_policy', [catalog_risk.ACTIVE_POLICY, catalog_risk.POLICY],
                         ids=['new-1.2', 'legacy-1.1'])
def test_authoring_law_and_pending_roundtrip(client, rag_flow, monkeypatch, search_policy):
    headers, payload = rag_flow
    monkeypatch.setenv('SAFET_RISK_LAW_URL', 'http://law.invalid')
    if search_policy == catalog_risk.POLICY:
        list_catalog = catalog_risk.list_catalog
        monkeypatch.setattr(catalog_risk, 'list_catalog',
                            lambda db, version=search_policy: list_catalog(db, version))
        monkeypatch.setattr(authoring_rag, 'regrade', lambda row: row)
    calls = []
    def search(*args):
        calls.append(args)
        return law_result()
    monkeypatch.setattr(risk_law, 'analyze', search)
    payload['add_custom_machines'] = ['반죽기']
    doc = create(client, rag_flow)
    path = f"/evals/{doc['eval_no']}"
    assert {row['authoring']['row']['scenario_id'] for row in doc['items'] if 'authoring' in row} == {'FRY'}
    fryer, fire = doc['items']
    assert fryer['law_reference']['candidate']['locator'] == '제1조'
    assert fire['catalog']['scenario']['id'] == 'FIRE' and fire['signal'] == 'R'
    assert doc['base_policy_version'] == catalog_risk.POLICY
    assert fire['policy_version'] == search_policy
    assert {row['scenario_id']: row['machine_kind'] for row in doc['pending_rows']} == {
        'GAS': 'input', 'MIX': 'unregistered', 'CUT': 'unregistered'}
    assert create(client, rag_flow) == doc and len(calls) == 1
    blocked = client.post(path+'/confirm', headers=headers, json=edits(doc))
    assert blocked.json()['detail']['code'] == 'PENDING_ROWS_REVIEW_REQUIRED'

    def review(document, scenario, decision):
        return client.post(path+'/pending-rows', headers=headers,
                           json={'revision': document['revision'], 'scenario_id': scenario, 'decision': decision})

    dismissed = review(doc, 'CUT', 'dismiss')
    assert dismissed.status_code == 200, dismissed.text
    assert review(doc, 'MIX', 'add').json()['detail']['code'] == 'STALE_REVISION'
    added = review(dismissed.json(), 'MIX', 'add')
    assert added.status_code == 200, added.text
    doc = added.json()
    assert doc['items'][-1]['catalog']['scenario']['id'] == 'MIX'
    assert doc['items'][-1]['signal'] == 'R' and doc['items'][-1]['policy_version'] == search_policy
    assert doc['items'][-1]['catalog']['risk_law']['other_cards'][0]['from_machine'] is False
    added_text = review(doc, 'GAS', 'add')
    assert added_text.status_code == 200, added_text.text
    doc = added_text.json()
    assert not doc['pending_rows']
    gas = doc['items'][-1]
    assert gas['catalog']['scenario']['id'] == 'GAS'
    assert gas['signal'] == 'R' and not gas['catalog']['risk_law']['card']['from_machine']
    assert gas['policy_version'] == search_policy

    form = edits(doc)
    saved = client.put(path, headers=headers, json=form)
    assert saved.status_code == 200, saved.text
    assert saved.json()['items'][-1]['signal'] == 'R'
    fresh = client.get(path, headers=headers).json()
    blocked = client.post(path+f"/items/{fryer['id']}/delete", headers=headers, json={'revision': fresh['revision']})
    assert blocked.json()['detail']['code'] == 'AUTHORING_REMOVE_UNSUPPORTED'
    for item in (fire, gas):
        removed = client.post(path+f"/items/{item['id']}/delete", headers=headers, json={'revision': fresh['revision']})
        assert removed.status_code == 200, removed.text
        fresh = removed.json()
    assert len(fresh['items']) == 2 and 'authoring' in fresh['items'][0]
    form = edits(fresh)
    form['excluded_review_candidates'] = [c['scenario_id'] for c in fresh['review_candidates']]
    for row, edit in zip(fresh['items'], form['items']):
        edit.update(work_reviewed=bool(row.get('authoring')), owner={'type':'R','name':'근로자'}, due='2026-12-01')
        edit['none'] = 'authoring' not in row
        edit['plans'][0]['checked'] = True
    confirmed = client.post(path+'/confirm', headers=headers, json=form)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['items'][-1]['signal'] != 'N'
    report = client.get(path+'/report', headers=headers)
    assert report.status_code == 200
    assert '검수용 법령' in ''.join(page.extract_text() for page in PdfReader(io.BytesIO(report.content)).pages)


def test_law_search_cannot_restore_a_denied_activity(client, rag_flow, monkeypatch):
    monkeypatch.setenv('SAFET_RISK_LAW_URL', 'http://law.invalid')
    monkeypatch.setattr(risk_law, 'analyze', lambda *args: law_result())
    rag_flow[1]['text'] = '튀김기는 사용하지 않습니다.'
    doc = create(client, rag_flow)
    assert {'scenario_id': 'FRY', 'reason': 'input_denies_work'} in doc['review_candidates']
    assert all(row.get('catalog', {}).get('scenario', {}).get('id') != 'FRY' for row in doc['items'])


def test_photo_only_uses_detected_machines_for_law_without_registering_them(client, rag_flow, monkeypatch):
    headers, payload = rag_flow
    source = client.get(f"/workplaces/{payload['work_no']}", headers=headers).json()
    work = client.post('/workplaces', headers=headers,
                       json={'workplace':'사진 검수', 'biz_code':source['biz_code']}).json()['work_no']
    monkeypatch.setenv('SAFET_RISK_LAW_URL', 'http://law.invalid')
    monkeypatch.setattr(authoring_rag.catalog_ai, 'detect_equipment', lambda photos: dict(
        model='sam3-mock', detections=[dict(photo_id='PHOTO1', equipment='deep fryer',
                                           bbox=[0, 0, 1, 1], confidence=0.91)]))
    def search(text, voice, machines):
        assert text == voice == ''
        assert [m['machine_nm'] for m in machines] == ['튀김기']
        return {'units':[dict(source='MACHINE', text='튀김기', risks=[law_hit('FRY')])]}
    monkeypatch.setattr(risk_law, 'analyze', search)
    payload.update(work_no=work, text='', photos=[PHOTO])
    doc = create(client, rag_flow)
    assert not doc['items']
    assert [(row['scenario_id'], row['machine_kind']) for row in doc['pending_rows']] == [('FRY', 'unregistered')]
    assert not client.get(f"/workplaces/{work}", headers=headers).json()['machines']


def test_law_excludes_registered_mixer_when_input_denies_its_synonym(client, rag_flow, monkeypatch):
    monkeypatch.setenv('SAFET_RISK_LAW_URL', 'http://law.invalid')
    payload = rag_flow[1]
    # 반죽 믹서는 반죽기와 같은 기기 코드의 별칭이다. 믹서(블렌더)는 다른 기기라 반죽기를 제외하지 않는다.
    payload.update(text='반죽 믹서는 사용하지 않습니다.', add_custom_machines=['반죽기'],
                   save_machines_to_workplace=True)
    def search(text, voice, machines):
        assert '반죽기' not in [m['machine_nm'] for m in machines]
        return {'units':[dict(source='TEXT', text=text, risks=[law_hit('MIX'), law_hit('CUT')])]}
    monkeypatch.setattr(risk_law, 'analyze', search)
    doc = create(client, rag_flow)
    assert not doc['items']
    assert [(row['scenario_id'], row['machine_kind']) for row in doc['pending_rows']] == [('CUT', 'input')]


@pytest.mark.parametrize('field', ['text', 'voice_text'])
@pytest.mark.parametrize('description', ['육절기는 사용하지 않습니다.',
                                         '채소절단기로 채소를 썹니다. 육절기는 사용하지 않습니다.'])
def test_law_excludes_only_the_denied_machine_sharing_a_scenario(client, rag_flow, monkeypatch, field, description):
    # PR #61 재리뷰: 채소절단기·육절기는 같은 위험요인(CUT)이지만 미사용 진술은 육절기에만 적용한다.
    monkeypatch.setenv('SAFET_RISK_LAW_URL', 'http://law.invalid')
    payload = rag_flow[1]
    payload.update(text='', add_custom_machines=['채소절단기', '육절기'], save_machines_to_workplace=True)
    payload[field] = description
    # 이 시험은 법령 검색 대상만 본다. 고정 모의 분석은 다른 작업 문장용이라 빈 분석으로 둔다.
    monkeypatch.setattr(authoring_rag, 'extract', lambda *args: dict(
        contract_version='assessment-authoring-1', candidates=[], unmatched_risks=[]))
    searched = []
    def search(text, voice, machines):
        searched.append([m['machine_nm'] for m in machines])
        return {'units':[dict(source='MACHINE', text='채소절단기', risks=[law_hit('CUT')])]}
    monkeypatch.setattr(risk_law, 'analyze', search)
    doc = create(client, rag_flow)
    assert searched and '채소절단기' in searched[0] and '육절기' not in searched[0]
    assert any(row.get('catalog', {}).get('scenario', {}).get('id') == 'CUT'
               or row.get('scenario_id') == 'CUT' for row in doc['items'] + doc.get('pending_rows', []))


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


def test_same_photo_three_inputs_and_confirmed_pdf(client, rag_flow, monkeypatch, tmp_path):
    headers, payload = rag_flow
    calls = []
    observed = []
    monkeypatch.setenv('SAFET_DETECTOR_REVISION', 'mock-v1')

    def detect(photos):
        calls.append(photos)
        return dict(model='sam3-mock', detections=[
            dict(photo_id='PHOTO1', equipment='deep fryer', bbox=[0, 0, 1, 1], confidence=0.91),
        ])

    def extract(context, retrieval, snapshot, evidence):
        observed.append(context)
        work = context['media'][0]['text']
        scenario_id = retrieval['candidates'][0]['scenario_id']
        controls = []
        statement = work.split('. ', 1)[0].removesuffix('.') + '.'
        if scenario_id == 'FRY' and statement == '튀김기로 조리합니다.':
            controls = [
                dict(control_id='FRY-C2', state='supported', evidence_refs=['TEXT'],
                     statement='기름은 식힌 뒤 배유합니다.'),
                dict(control_id='FRY-C1', state='not_effective', evidence_refs=['TEXT'],
                     statement='온도 제어 장치는 고장 났습니다.'),
            ]
        supported = controls or (scenario_id == 'KNIFE' and statement == '칼로 채소를 썹니다.')
        candidates = [dict(scenario_id=scenario_id, rationale='합성 모델 응답',
                           evidence=[dict(media_id='TEXT', statement=statement)],
                           control_evidence=controls, assumptions=[], questions=[])] if supported else []
        return dict(contract_version='assessment-authoring-1', candidates=candidates, unmatched_risks=[])

    monkeypatch.setattr(authoring_rag.catalog_ai, 'detect_equipment', detect)
    monkeypatch.setattr(authoring_rag, 'extract', extract)
    payload['photos'] = [PHOTO]
    for work, review, expected_rows in [
        ('칼로 채소를 썹니다.', 'work_unconfirmed', ['KNIFE']),
        ('튀김은 하지 않습니다.', 'input_denies_work', []),
    ]:
        payload.update(request_key=str(uuid4()), text=work)
        doc = create(client, rag_flow)
        assert [item['authoring']['analysis']['scenario_id'] for item in doc['items']] == expected_rows
        assert {'scenario_id': 'FRY', 'reason': review} in doc['review_candidates']
        assert doc['inputs'][-1]['ori_file_nm'] == PHOTO['name']
    payload.update(request_key=str(uuid4()),
                   text='튀김기로 조리합니다. 기름은 식힌 뒤 배유합니다. 온도 제어 장치는 고장 났습니다.')
    doc = create(client, rag_flow)
    assert len(calls) == 1
    assert observed[-1]['equipment_ids'] == ['EQ_FRYER']
    assert any(m['id'] == 'PHOTO1' and '튀김기' in m['text'] for m in observed[-1]['media'])
    item, = doc['items']
    evidence = item['authoring']['analysis']['control_evidence']
    assert {(e['statement'], e['state']) for e in evidence if e['state'] != 'unknown'} == {
        ('기름은 식힌 뒤 배유합니다.', 'supported'),
        ('온도 제어 장치는 고장 났습니다.', 'not_effective'),
    }
    assert 'photo_cache' not in item['authoring']
    with engine.connect() as db:
        assert authoring_rag.cached_photos(db, 'other@test.invalid', payload['work_no'], [PHOTO]) is None
    path = f"/evals/{doc['eval_no']}"
    saved = client.put(path, headers=headers, json=edits(doc))
    assert saved.status_code == 200, saved.text
    draft = client.get(path, headers=headers).json()
    assert draft['items'][0]['authoring'] == item['authoring']
    finish = edits(draft)
    finish['items'][0].update(work_reviewed=True, owner={'type': 'R', 'name': '근로자'}, due='2026-12-01')
    finish['items'][0]['plans'][0]['checked'] = True
    confirmed = client.post(path + '/confirm', headers=headers, json=finish)
    assert confirmed.status_code == 200, confirmed.text
    final = client.get(path, headers=headers).json()
    assert final['eval_status'] == 'C' and final['items'][0]['authoring'] == item['authoring']
    pdf = client.get(path + '/report', headers=headers)
    assert pdf.status_code == 200 and pdf.headers['content-type'] == 'application/pdf'
    (tmp_path / 'confirmed-fryer.pdf').write_bytes(pdf.content)
    pdf_text = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert '튀김기' in pdf_text and '근로자' in pdf_text


def test_zero_detection_cache_refresh_and_failure(client, rag_flow, monkeypatch):
    headers, payload = rag_flow
    payload['photos'] = [PHOTO]
    calls = []

    def detect(photos):
        calls.append(photos)
        if len(calls) > 1:
            raise AuthError(503, 'DETECTOR_FAILED', '모의 탐지 실패')
        return dict(model='sam3-mock', detections=[])

    monkeypatch.setattr(authoring_rag.catalog_ai, 'detect_equipment', detect)
    monkeypatch.setenv('SAFET_DETECTOR_REVISION', 'mock-v1')
    for _ in range(2):
        payload['request_key'] = str(uuid4())
        assert create(client, rag_flow)['items']
    assert len(calls) == 1
    monkeypatch.setenv('SAFET_DETECTOR_REVISION', 'mock-v2')
    payload['request_key'] = str(uuid4())
    failure = client.post('/evals', headers=headers, json=payload)
    assert failure.status_code == 503 and failure.json()['detail']['code'] == 'DETECTOR_FAILED'
    assert len(calls) == 2
    with engine.connect() as db:
        assert db.execute(text('SELECT COUNT(*) FROM eval_mst WHERE request_key=:key'),
                          {'key': payload['request_key']}).scalar() == 0
