"""외부 연결 없이 실제 HTTP 어댑터 경로·근거 검증을 검사한다."""
import base64,copy,json,sys
from pathlib import Path
import httpx,pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services import catalog_ai as ai
from services.auth import AuthError
CAT=json.loads(ai.catalog.SEED.read_text(encoding='utf-8'))['scenarios']


def test_text_evidence_and_machine_registration_are_not_observations():
    inp=ai.make_input({'request_key':'test','text':'튀김 작업','machines':[{'machine_nm':'튀김기'}]})
    r={'evidence':[{'id':'E1','media_id':'TEXT','kind':'reported','statement':'없는 문구'}],'matches':[],'unmatched_observations':[]}
    with pytest.raises(AuthError):ai.validate(r,inp,CAT)
    r['evidence'][0].update(media_id='MACHINES',statement=inp['media'][1]['content'])
    with pytest.raises(AuthError):ai.validate(r,inp,CAT)
    r['evidence'][0].update(media_id='TEXT',kind='observed',statement='튀김 작업')
    with pytest.raises(AuthError):ai.validate(r,inp,CAT)


@pytest.mark.parametrize('failure',['timeout','invalid_json','truncated','upstream','oversize','success'])
def test_transport_validated_image_and_safe_failure(monkeypatch,failure):
    monkeypatch.setenv('SAFET_AI_BASE_URL','http://127.0.0.1:39999/v1')
    monkeypatch.setenv('SAFET_AI_MODEL','synthetic-model')
    monkeypatch.setenv('SAFET_AI_API_KEY','synthetic-private-key')
    image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nsynthetic').decode()
    inp=ai.make_input({'request_key':'test','text':'튀김 작업','voice_text':'브라우저 전사문','photos':[{'name':'synthetic.png','data':image}]})
    actual=httpx.Client;captured=[]
    def handler(request):
        captured.append(json.loads(request.content));assert request.headers['Authorization']=='Bearer synthetic-private-key'
        if failure=='timeout':raise httpx.ReadTimeout('private upstream data')
        if failure=='upstream':return httpx.Response(500,text='private upstream data')
        content='not json' if failure=='invalid_json' else '{}'
        if failure=='oversize':return httpx.Response(200,content=b'x'*2_000_001)
        return httpx.Response(200,json={'choices':[{'finish_reason':'length' if failure=='truncated' else 'stop','message':{'content':content}}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:actual(transport=httpx.MockTransport(handler),**kw))
    if failure=='success':assert ai.request_analysis(inp,CAT)=={}
    else:
        with pytest.raises(AuthError) as err:ai.request_analysis(inp,CAT)
        assert err.value.code=='RISK_MODEL_FAILED' and 'private' not in err.value.message
    payload=captured[0];parts=payload['messages'][1]['content']
    assert any(p.get('type')=='image_url' and p['image_url']['url']==image for p in parts)
    assert image not in parts[0]['text'] and inp['media'][-1]['media_uri']==image


def test_missing_endpoint_is_explicit(monkeypatch):
    monkeypatch.delenv('SAFET_AI_MODEL',raising=False)
    with pytest.raises(AuthError) as err:ai.configuration()
    assert err.value.code=='RISK_MODEL_UNCONFIGURED'


@pytest.mark.parametrize('value',['bad','0','999999'])
def test_invalid_token_limit_is_configuration_error(monkeypatch,value):
    monkeypatch.setenv('SAFET_AI_BASE_URL','http://127.0.0.1:39999/v1')
    monkeypatch.setenv('SAFET_AI_MODEL','synthetic')
    monkeypatch.setenv('SAFET_AI_MAX_TOKENS',value)
    with pytest.raises(AuthError) as err:ai.configuration()
    assert err.value.code=='RISK_MODEL_UNCONFIGURED'


def test_photo_only_retrieval_and_public_schema(monkeypatch):
    monkeypatch.setattr(ai.catalog,'list_catalog',lambda db:CAT)
    candidates=ai.retrieve(None,{'photos':[{'name':'synthetic.png'}]})
    assert {s['id'] for s in candidates}=={s['id'] for s in CAT}
    stored=json.loads((ai.PROMPT.parents[2]/'contracts/catalog_ai/analysis.schema.json').read_text(encoding='utf-8'))
    assert stored==ai.Extraction.model_json_schema()
