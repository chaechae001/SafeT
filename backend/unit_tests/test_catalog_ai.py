"""외부 모델 없이 실제 요청 형식과 응답 신뢰 경계를 검사한다."""
import copy,json,sys
from pathlib import Path
import httpx,pytest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
from services import catalog_ai as ai
from services.auth import AuthError
CAT=json.loads((ROOT/'contracts/catalog_risk/catalog.json').read_text(encoding='utf-8'))['scenarios']
RESPONSE={'candidates':[{'scenario_id':'FRY','rationale':'사용자가 튀김 작업을 보고함','evidence':[{'media_id':'TEXT','statement':'튀김 작업'}],'questions':[]}],'unmatched_risks':[]}

@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('SAFET_AI_BASE_URL','https://model.invalid/v1');monkeypatch.setenv('SAFET_AI_MODEL','test-text-model')
    monkeypatch.setenv('SAFET_AI_API_KEY','test-secret-do-not-echo')
    monkeypatch.setenv('SAFET_DETECTOR_URL','https://detector.invalid/detect')
    monkeypatch.setenv('SAFET_AI_MAX_TOKENS','1024')
    # 실제 로컬 .env 주소가 모의 서버 검사에 섞이지 않도록 분리한다.
    monkeypatch.setenv('SAFET_AI_TOKENIZE_URL','https://model.invalid/tokenize')
    monkeypatch.setenv('SAFET_DETECTOR_THRESHOLD','0.05')
    monkeypatch.setenv('SAFET_DETECTOR_API_KEY','')


def transport(monkeypatch,handler):
    client=httpx.Client
    monkeypatch.setattr(ai.httpx,'Client',lambda **kwargs:client(transport=httpx.MockTransport(handler),**kwargs))


def test_text_model_receives_detection_json_not_images(configured,monkeypatch):
    sent=[]
    def handler(req):
        body=json.loads(req.content);sent.append(body)
        if req.url.host=='detector.invalid':
            assert body['photos'][0]['image_base64']=='YQ=='
            assert body['score_threshold']==0.05
            return httpx.Response(200,json=sam_response(body))
        if req.url.path=='/tokenize': return httpx.Response(200,json={'count':2000})
        assert isinstance(body['messages'][1]['content'],str)
        assert 'data:image' not in body['messages'][1]['content']
        assert 'sam3-test' in body['messages'][1]['content']
        assert body['model']=='test-text-model'
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(RESPONSE)}}]})
    transport(monkeypatch,handler)
    out=ai.analyze({'text':'튀김 작업','voice_text':'뜨거운 기름','photos':[{'name':'x.png','data':'data:image/png;base64,YQ==','place':'주방'}]},CAT)
    assert len(sent)==3 and out[0]['policy_version']=='CATALOG-MVP-1.1'


@pytest.mark.parametrize('change',[
 lambda r:r['candidates'][0].update(grade='하'),
 lambda r:r['candidates'][0].update(scenario_id='INVENTED'),
 lambda r:r['candidates'][0]['evidence'][0].update(media_id='FAKE'),
 lambda r:r['candidates'].append(copy.deepcopy(r['candidates'][0])),
 lambda r:r['candidates'][0].update(questions=[{'id':'Q1','text':'a'},{'id':'Q1','text':'b'}]),
])
def test_reject_invalid_model_claims(configured,monkeypatch,change):
    response=copy.deepcopy(RESPONSE);change(response)
    monkeypatch.setattr(ai,'request_analysis',lambda *a:response)
    with pytest.raises(AuthError) as e:ai.analyze({'text':'튀김'},CAT)
    assert e.value.code=='AI_RESPONSE_INVALID'


def test_outside_catalog_and_missing_configuration(configured,monkeypatch):
    response=copy.deepcopy(RESPONSE);response['unmatched_risks']=['기준에 없는 위험']
    monkeypatch.setattr(ai,'request_analysis',lambda *a:response)
    with pytest.raises(AuthError) as e:ai.analyze({'text':'튀김'},CAT)
    assert e.value.code=='AI_OUTSIDE_CATALOG'
    monkeypatch.delenv('SAFET_AI_MODEL')
    with pytest.raises(AuthError) as e:ai.analyze({'text':'튀김'},CAT)
    assert e.value.code=='AI_UNCONFIGURED'


@pytest.mark.parametrize('response',[
 httpx.Response(401,text='test-secret-do-not-echo private photo'),
 httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':json.dumps(RESPONSE)}}]}),
 httpx.Response(200,text='not JSON'),
 httpx.Response(200,content=b'x'*2_000_001),
])
def test_failure_not_leaked_or_replaced(configured,monkeypatch,response):
    transport(monkeypatch,lambda req:httpx.Response(200,json={'count':2000}) if req.url.path=='/tokenize' else response)
    with pytest.raises(AuthError) as e:ai.analyze({'text':'튀김'},CAT)
    assert e.value.code=='AI_REQUEST_FAILED' and 'test-secret' not in str(e.value)


def test_photo_requires_detector(configured,monkeypatch):
    monkeypatch.delenv('SAFET_DETECTOR_URL')
    with pytest.raises(AuthError) as e:ai.analyze({'photos':[{'data':'data:image/png;base64,YQ=='}]},CAT)
    assert e.value.code=='DETECTOR_UNCONFIGURED'


def sam_response(body):
    return {'model_output':{'request_id':body['request_id'],'status':'ok','error_code':None,
      'detector':{'model_name':'sam3-test','model_version':'test','score_threshold_applied':0.05},
      'photos':[{'photo_id':p['photo_id'],'status':'analyzed','width':1600,'height':900} for p in body['photos']],
      'detections':[{'detection_id':'d1','photo_id':'PHOTO1','equipment_id':'EQ_GRILL',
        'detector_class':'salamander broiler','confidence':0.9297,'bbox':[0.1,0.2,0.4,0.6]}]},
      'service_meta':{'per_image_s':[4.18]}}

@pytest.mark.parametrize('count,allowed',[(3008,True),(3009,False),(4096,False)])
def test_exact_context_budget(configured,monkeypatch,count,allowed):
    calls=[]
    def handler(req):
        calls.append(req.url.path)
        if req.url.path=='/tokenize':return httpx.Response(200,json={'count':count})
        assert json.loads(req.content)['max_tokens']+count+64<=4096
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(RESPONSE)}}]})
    transport(monkeypatch,handler)
    if allowed:ai.analyze({'text':'튀김'},CAT)
    else:
        with pytest.raises(AuthError) as err:ai.analyze({'text':'튀김'},CAT)
        assert err.value.code=='AI_INPUT_TOO_LONG' and calls==['/tokenize']

@pytest.mark.parametrize('change',[
 lambda x:x['model_output'].update(status='partial'),
 lambda x:x['model_output'].update(request_id='wrong'),
 lambda x:x['model_output'].update(photos=[]),
 lambda x:x['model_output']['detections'][0].update(photo_id='wrong'),
 lambda x:x['model_output']['detections'][0].update(bbox=[0.4,0.2,0.1,0.6]),
])
def test_sam_failure_never_becomes_empty_success(configured,monkeypatch,change):
    def handler(req):
        data=sam_response(json.loads(req.content));change(data);return httpx.Response(200,json=data)
    transport(monkeypatch,handler)
    with pytest.raises(AuthError) as err:ai.detect_equipment([{'data':'data:image/jpeg;base64,YQ=='}])
    assert err.value.code=='DETECTOR_FAILED'

@pytest.mark.parametrize('photos',[[],[{'data':'data:image/jpeg;base64,YQ=='}]*9,[{'data':'data:image/jpeg;base64,%%%'}]])
def test_invalid_photo_rejected_before_network(configured,monkeypatch,photos):
    transport(monkeypatch,lambda req:pytest.fail('must not call server'))
    with pytest.raises(AuthError) as err:ai.detect_equipment(photos)
    assert err.value.code=='AI_IMAGE_INVALID'

def test_tokenizer_unavailable_is_explicit(configured,monkeypatch):
    transport(monkeypatch,lambda req:httpx.Response(404))
    with pytest.raises(AuthError) as err:ai.analyze({'text':'튀김'},CAT)
    assert err.value.code=='AI_TOKENIZE_FAILED'

def test_photo_requires_human_confirmation(configured,monkeypatch):
    monkeypatch.setattr(ai,'request_analysis',lambda *a:copy.deepcopy(RESPONSE))
    monkeypatch.setattr(ai,'detect_equipment',lambda *a:{'model':'sam','detections':[]})
    ctx={'text':'튀김','photos':[{'data':'data:image/jpeg;base64,YQ=='}]}
    result=ai.analyze(ctx,CAT)
    assert result[0]['questions'][0]['id']=='EQUIPMENT_CONFIRM_FRY'
    result=ai.analyze(ctx,CAT,answers=[{'question_id':'EQUIPMENT_CONFIRM_FRY','answer':'튀김기이고 사용합니다.'}])
    assert result[0]['questions']==[]
