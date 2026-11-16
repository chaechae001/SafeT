"""Policy and real HTTP envelope tests. Model responses are synthetic fixtures, not inference accuracy."""
import base64
import json
import sys
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from services import restaurant_risk as risk
from services.restaurant_risk_engine import grade_hazard, evaluate
from services.auth import AuthError

CASES=json.loads((ROOT/'contracts/restaurant_risk_v2/examples.json').read_text(encoding='utf-8'))['cases']

def test_all_contracts_and_reference_examples():
    schemas,catalog,_=risk.resources()
    for schema in schemas.values(): Draft202012Validator.check_schema(schema)
    for c in CASES:
        output=c['expected_output']
        Draft202012Validator(schemas['input']).validate(c['input'])
        Draft202012Validator(schemas['analysis']).validate(output['analysis'])
        Draft202012Validator(schemas['output']).validate(output)
        assert evaluate(output['analysis'],c['input'],catalog)==output

@pytest.mark.parametrize('s,c,expected',[(1,1,1),(1,2,2),(1,3,2),(2,1,2),(2,2,2),(2,3,3),(3,1,3),(3,2,3),(3,3,3)])
def test_nine_cells(s,c,expected):
    h=deepcopy(CASES[3]['expected_output']['analysis']['hazards'][0])
    h['severity_options']=[s];h['control_options']=[c]
    assert grade_hazard(h)['ordinal']==expected

def test_no_low_or_confirmation_for_unknown_candidates():
    assert risk.to_items(CASES[1]['expected_output'])[0]['signal']=='N'
    assert risk.to_items(CASES[2]['expected_output'])[0]['signal']=='N'
    h=deepcopy(CASES[3]['expected_output']['analysis']['hazards'][0]);h['decision_evidence_complete']=False
    assert grade_hazard(h)['grade'] is None

def test_coverage_66_pages_and_27_categories():
    pages=json.loads((risk.KNOWLEDGE/'page_coverage.json').read_text(encoding='utf-8'))['pages']
    assert len(pages)==66
    assert {p['printed_page'] for p in pages}==set(range(94,97))|set(range(103,166))
    assert len(risk.resources()[1]['rules'])==27

def test_real_http_multimodal_envelope(monkeypatch):
    captured=[]
    result=CASES[2]['expected_output']['analysis']
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            captured.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            data=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        monkeypatch.setenv('SAFET_AI_BASE_URL',f'http://127.0.0.1:{server.server_port}/v1')
        monkeypatch.setenv('SAFET_AI_MODEL','synthetic-http-test')
        image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        data=risk.make_input(dict(request_key='EX03',text='바닥 물기',voice_text='손을 안 넣어요',photos=[dict(name='test.png',data=image,place='주방')],machines=[{'machine_nm':'반죽기'}]))
        risk.request_analysis(data)
        path,payload=captured[0];assert path=='/v1/chat/completions'
        parts=payload['messages'][1]['content']
        assert any(p.get('image_url',{}).get('url')==image for p in parts)
        assert '손을 안 넣어요' in parts[0]['text'] and '반죽기' in parts[0]['text']
        assert image not in parts[0]['text'] # actual multimodal part, not a base64 string in prose
        assert payload['response_format']=={'type':'json_object'}
    finally:server.shutdown();server.server_close();thread.join(timeout=2)

def test_unconfigured_and_invalid_response_fail_closed(monkeypatch):
    monkeypatch.delenv('SAFET_AI_MODEL',raising=False)
    with pytest.raises(AuthError) as e:risk.configuration()
    assert e.value.code=='RISK_MODEL_UNCONFIGURED'
    monkeypatch.setattr(risk,'request_analysis',lambda *a,**k:{'hazards':[]})
    with pytest.raises(AuthError) as e:risk.analyze(CASES[2]['input'])
    assert e.value.code=='RISK_RESPONSE_INVALID'

def test_unknown_evidence_and_law_cannot_be_accepted():
    schemas,catalog,_=risk.resources()
    for field in ('evidence','law'):
        a=deepcopy(CASES[3]['expected_output']['analysis'])
        if field=='evidence':a['hazards'][0]['evidence_ids']=['NONEXISTENT']
        else:a['hazards'][0]['safety_flags']['verified_legal_breach'].update(value='yes',evidence_ids=['E1'],registry_ids=['FAKE-LAW'])
        with pytest.raises(ValueError):evaluate(a,CASES[3]['input'],catalog)

def test_critical_unknown_cannot_be_complete():
    a=deepcopy(CASES[3]['expected_output']['analysis'])
    a['hazards'][0]['controls'][0]['state']='unknown'
    with pytest.raises(ValueError):evaluate(a,CASES[3]['input'],risk.resources()[1])

def test_reanalysis_cannot_drop_previous_hazard(monkeypatch):
    previous=deepcopy(CASES[2]['expected_output']['analysis'])
    candidate=deepcopy(previous);candidate['hazards']=[];candidate['questions']=[];candidate['actions']=[]
    monkeypatch.setattr(risk,'request_analysis',lambda *a,**k:candidate)
    with pytest.raises(AuthError):risk.analyze(CASES[2]['input'],previous)

def test_long_model_text_preserved_in_report_but_fits_existing_columns():
    report=deepcopy(CASES[2]['expected_output']);h=report['analysis']['hazards'][0]
    for key in ('task','subject','event','exposure','rationale'):h[key]='가'*1000
    item=risk.to_items(report)[0]
    for key,n in [('job',100),('title',200),('type',50),('cause',500),('reason',500)]:assert len(item[key])<=n
    assert len(h['rationale'])==1000
