"""MariaDB/API integration with synthetic model fixtures. No Cloud/GPU inference claim."""
import copy
import json
from pathlib import Path
import pytest
from services import restaurant_risk as risk
from test_assessment import flow,create,edits

CASES=json.loads((Path(__file__).resolve().parents[2]/'contracts/restaurant_risk_v2/examples.json').read_text(encoding='utf-8'))['cases']

def response(data,previous=None,known=False):
    analysis=copy.deepcopy(CASES[2]['expected_output']['analysis'])
    analysis['assessment_id']=data['assessment_id']
    analysis['evidence'][0]['media_id']='TEXT'
    if known:
        h=analysis['hazards'][0]
        h.update(severity_options=[2],control_options=[3],decision_evidence_complete=True,uncertainty=[])
        h.update(exposure='물기가 남은 통로로 근로자가 이동하고 출입 통제가 없다는 현재 보고',consequence='넘어져 치료가 필요한 염좌·골절',rationale='물기와 통행 노출이 확인됐고 핵심 조치인 오염 제거·통제가 없어 S2·C3, 상으로 판정한다.')
        h['controls'][0].update(state='absent',evidence_ids=['E1'])
        analysis['questions']=[]
    return analysis

@pytest.fixture
def real_flow(flow,monkeypatch):
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE','restaurant_v2')
    monkeypatch.setattr(risk,'request_analysis',response)
    return flow

def test_extract_questions_rejudge_save_confirm_roundtrip(client,real_flow,monkeypatch):
    auth,_=real_flow;doc=create(client,real_flow);no=doc['eval_no']
    assert doc['generation_source']=='restaurant_v2'
    assert doc['items'][0]['signal']=='N'
    assert doc['items'][0]['risk']['result']['grade']=='상'
    assert doc['items'][0]['risk']['result']['status']=='provisional'
    assert doc['risk_assessment']['analysis']['questions']
    body=edits(doc);body['items'][0]['none']=True
    stored=client.put(f'/evals/{no}',headers=auth,json=body).json()
    assert stored['risk_needs_reassessment']
    blocked=client.post(f'/evals/{no}/confirm',headers=auth,json=edits(stored))
    assert blocked.status_code==422
    monkeypatch.setattr(risk,'request_analysis',lambda data,previous=None:response(data,previous,True))
    out=client.post(f'/evals/{no}/risk-answers',headers=auth,json={'revision':stored['revision'],'answers':[{'question_id':'Q1','answer':'현재 물기가 남아 있고 통제도 없습니다.'}]})
    assert out.status_code==200,out.text
    ready=out.json();assert ready['items'][0]['signal']=='R' and not ready['risk_needs_reassessment']
    assert ready['items'][0]['id']==doc['items'][0]['id']
    assert ready['risk_assessment']['analysis']['questions']==[]
    body=edits(ready,True)
    done=client.post(f'/evals/{no}/confirm',headers=auth,json=body)
    assert done.status_code==200,done.text
    assert done.json()['items'][0]['after']=='N' # plans are not completed controls
    again=client.get(f'/evals/{no}',headers=auth).json()
    assert again['risk_assessment']==done.json()['risk_assessment']
    assert client.post(f'/evals/{no}/risk-answers',headers=auth,json={'revision':again['revision'],'answers':[]}).status_code==409

def test_bad_question_stale_revision_and_model_failure_preserve_document(client,real_flow,monkeypatch):
    auth,_=real_flow;doc=create(client,real_flow);no=doc['eval_no']
    assert client.post(f'/evals/{no}/risk-answers',headers=auth,json={'revision':1,'answers':[{'question_id':'FOREIGN','answer':'안전함'}]}).status_code==400
    assert client.post(f'/evals/{no}/risk-answers',headers=auth,json={'revision':999,'answers':[]}).status_code==409
    monkeypatch.setattr(risk,'request_analysis',lambda *a,**k:{'grade':'하'})
    assert client.post(f'/evals/{no}/risk-answers',headers=auth,json={'revision':1,'answers':[]}).status_code==502
    assert client.get(f'/evals/{no}',headers=auth).json()==doc

def test_current_control_edit_invalidates_previous_confirmed_grade(client,real_flow,monkeypatch):
    monkeypatch.setattr(risk,'request_analysis',lambda data,previous=None:response(data,previous,True))
    auth,_=real_flow;doc=create(client,real_flow);assert doc['items'][0]['signal']=='R'
    body=edits(doc);body['items'][0]['curr'][0]['checked']=True
    changed=client.put(f"/evals/{doc['eval_no']}",headers=auth,json=body).json()
    assert changed['items'][0]['signal']=='N' and changed['risk_needs_reassessment']

def test_photos_voice_and_machines_reach_provider_and_reanalysis(client,real_flow,monkeypatch):
    import base64
    auth,payload=real_flow;seen=[]
    def capture(data,previous=None):seen.append(copy.deepcopy(data));return response(data,previous)
    monkeypatch.setattr(risk,'request_analysis',capture)
    payload['voice_text']='돌아갈 때 손을 안 넣어요'
    payload['photos']=[dict(name='sample.png',place='주방',data='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode())]
    doc=create(client,real_flow)
    assert {m['modality'] for m in seen[0]['media']}=={'photo','text','voice_transcript'}
    assert any(m['id']=='MACHINES' for m in seen[0]['media'])
    result=client.post(f"/evals/{doc['eval_no']}/risk-answers",headers=auth,json={'revision':1,'answers':[],'additional_text':'점검 기록 확인 중'})
    assert result.status_code==200,result.text
    assert next(m['media_uri'] for m in seen[1]['media'] if m['modality']=='photo')==payload['photos'][0]['data']

def test_no_model_grade_or_policy_override_from_client(client,real_flow):
    auth,_=real_flow;doc=create(client,real_flow)
    r=client.post(f"/evals/{doc['eval_no']}/risk-answers",headers=auth,json={'revision':1,'answers':[],'grade':'하'})
    assert r.status_code==422
