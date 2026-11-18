"""기존 PR #11의 멀티모달 HTTP 연결을 공통 카탈로그 후보 분석에 맞춰 통합한다.

SAM 사진 탐지 결과·전사문 전달, 제한된 응답 크기, 오류 시 원문 비노출을 유지한다.
판정 엔진은 가져오지 않는다. 모든 등급 계산은 domain.risk_policy가 담당한다.
"""
import base64
import hashlib
import uuid
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import httpx
from pydantic import ValidationError
from schemas.catalog_ai import Analysis, SamResponse
from services.auth import AuthError
from domain.risk_policy import POLICY

SOURCE = 'catalog_ai_v1'
ROOT = Path(__file__).resolve().parents[2]


def gateway_url():
    """관문 설정 시 모든 모델 요청을 같은 주소로 보낸다."""
    base = os.getenv('SAFET_AI_GATEWAY_URL', '').strip().rstrip('/')
    if not base:
        return ''
    uri = urlparse(base)
    if uri.scheme not in ('http', 'https') or not uri.netloc or uri.username or uri.password or uri.query or uri.fragment:
        raise AuthError(503, 'AI_UNCONFIGURED', 'AI 관문 주소를 확인해 주세요.')
    return base


def model_headers(detector=False):
    name = 'SAFET_DETECTOR_API_KEY' if detector and not gateway_url() else 'SAFET_AI_API_KEY'
    key = os.getenv(name, '').strip()
    if gateway_url() and not key:
        raise AuthError(503, 'AI_UNCONFIGURED', 'AI 관문 인증 키가 필요해요. 입력은 유지됩니다.')
    return {'Authorization': 'Bearer ' + key} if key else {}


def configuration():
    base = gateway_url() + '/v1' if gateway_url() else os.getenv('SAFET_AI_BASE_URL', '').rstrip('/')
    model = os.getenv('SAFET_AI_MODEL', '').strip()
    uri = urlparse(base)
    try:
        tokens = int(os.getenv('SAFET_AI_MAX_TOKENS', '1024'))
        valid = 256 <= tokens <= 2048
        uri.port
    except ValueError:
        valid = False
    if not valid or not model or uri.scheme not in ('http', 'https') or not uri.netloc or uri.username or uri.password or uri.query or uri.fragment:
        raise AuthError(503, 'AI_UNCONFIGURED', 'AI API 기본 주소·모델명·출력 길이 설정을 확인해 주세요.')
    return base, model, tokens


def detect_equipment(photos):
    endpoint=gateway_url() + '/v1/detect' if gateway_url() else os.getenv('SAFET_DETECTOR_URL','').strip()
    uri=urlparse(endpoint)
    if uri.scheme not in ('http','https') or not uri.netloc or uri.username or uri.password or uri.query or uri.fragment:
        raise AuthError(503,'DETECTOR_UNCONFIGURED','사진 기기 탐지 서버 설정이 필요해요. 사진은 유지됩니다.')
    if not 1 <= len(photos) <= 8:
        raise AuthError(422,'AI_IMAGE_INVALID','사진은 1~8장까지 전달할 수 있어요.')
    try:
        threshold=float(os.getenv('SAFET_DETECTOR_THRESHOLD','0.05'))
        if not 0 <= threshold <= 1: raise ValueError()
        payload={'request_id':str(uuid.uuid4()),'score_threshold':threshold,'photos':[]}
        for i,p in enumerate(photos):
            prefix,encoded=p['data'].split(',',1)
            if prefix not in ('data:image/png;base64','data:image/jpeg;base64','data:image/webp;base64'):
                raise ValueError()
            if len(encoded)>4*((12*1024*1024+2)//3): raise ValueError()
            decoded=base64.b64decode(encoded,validate=True)
            if not decoded or len(decoded)>12*1024*1024: raise ValueError()
            payload['photos'].append({'photo_id':f'PHOTO{i+1}','image_base64':encoded})
    except (ValueError,KeyError,TypeError):
        raise AuthError(422,'AI_IMAGE_INVALID','사진 형식·용량(장당 12MB 이하)과 탐지 임계값을 확인해 주세요.') from None
    headers=model_headers(detector=True)
    try:
        with httpx.Client(timeout=httpx.Timeout(180,connect=10),follow_redirects=False,trust_env=False) as client:
            with client.stream('POST',endpoint,json=payload,headers=headers) as response:
                response.raise_for_status();raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>1_000_000:raise ValueError('응답 크기 초과')
        parsed=SamResponse.model_validate_json(raw).model_output
        photo_ids={p['photo_id'] for p in payload['photos']}
        if parsed.request_id!=payload['request_id'] or parsed.status!='ok' or parsed.error_code:
            raise ValueError('요청 불일치 또는 일부 탐지 실패')
        if {p.photo_id for p in parsed.photos}!=photo_ids or len(parsed.photos)!=len(photo_ids):
            raise ValueError('사진 결과 누락')
        if any(p.status!='analyzed' or p.error_code for p in parsed.photos): raise ValueError('사진 분석 실패')
        if len({d.detection_id for d in parsed.detections})!=len(parsed.detections): raise ValueError('중복 탐지 ID')
        if any(d.photo_id not in photo_ids or d.bbox[0]>=d.bbox[2] or d.bbox[1]>=d.bbox[3] for d in parsed.detections):
            raise ValueError('잘못된 사진 ID 또는 박스')
        return {'model':parsed.detector.model_name,'metadata':parsed.model_dump(exclude={'detections'}),
                'detections':[dict(d.model_dump(),equipment=d.detector_class) for d in parsed.detections]}
    except (httpx.HTTPError,ValueError,TypeError):
        raise AuthError(503,'DETECTOR_FAILED','사진 기기 탐지를 완료하지 못했어요. 입력을 유지하고 다시 시도해 주세요.') from None


def make_input(context, answers=None):
    media = []
    for key, mid in [('text','TEXT'),('voice_text','VOICE')]:
        if context.get(key): media.append({'id':mid,'text':context[key]})
    if context.get('machines'):
        media.append({'id':'MACHINES','text':'보유기기이며 실제 가동·노출 확정 아님: '+json.dumps(context['machines'],ensure_ascii=False)})
    images = []
    if context.get('photos'):
        # 서버가 보관한 동일 사진·임계값의 탐지만 재사용한다. 클라이언트 입력 계약에는 캐시 필드가 없다.
        signature=json.dumps({'photos':[{'data':p['data'],'place':p.get('place','')} for p in context['photos']],
                              'threshold':os.getenv('SAFET_DETECTOR_THRESHOLD','0.05')},sort_keys=True)
        fingerprint=hashlib.sha256(signature.encode()).hexdigest()
        cache=context.get('_photo_cache')
        if not context.get('_refresh_photos') and cache and cache.get('version')==1 and cache.get('fingerprint')==fingerprint:
            detected=cache['detection']
        else:
            detected=detect_equipment(context['photos'])
        context['_photo_cache']={'version':1,'fingerprint':fingerprint,'detection':detected}
        for i,p in enumerate(context['photos']):
            mid=f'PHOTO{i+1}'
            hits=[d for d in detected['detections'] if d['photo_id']==mid]
            media.append({'id':mid,'place':p.get('place',''),'kind':'equipment_detection',
                          'detector_model':detected['model'],'detections':hits,
                          'notice':'기기 후보 탐지 결과이며 누출·정상 작동·현재 조치·노출을 확인한 것이 아님'})
    for i,a in enumerate(answers or []):
        media.append({'id':f'ANSWER{i+1}','text':json.dumps(a,ensure_ascii=False)})
    return media, images


def output_budget(base, model, messages, headers, requested):
    """vLLM의 동일 채팅 템플릿으로 계수한다. 미지원·실패 시 추정값으로 호출하지 않는다."""
    endpoint=(gateway_url() + '/tokenize') if gateway_url() else (os.getenv('SAFET_AI_TOKENIZE_URL','').strip() or (base[:-3] if base.endswith('/v1') else base)+'/tokenize')
    # 계수 요청에도 동일 인증을 사용하므로 다른 호스트로 키가 전달되지 않게 제한한다.
    if urlparse(endpoint).scheme!=urlparse(base).scheme or urlparse(endpoint).netloc!=urlparse(base).netloc:
        raise AuthError(503,'AI_UNCONFIGURED','토큰 계수 주소는 모델 서버와 같은 호스트여야 해요.')
    try:
        with httpx.Client(timeout=httpx.Timeout(180,connect=10),follow_redirects=False,trust_env=False) as client:
            with client.stream('POST',endpoint,headers=headers,json={'model':model,'messages':messages,'add_generation_prompt':True}) as response:
                response.raise_for_status();raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>2_000_000: raise ValueError()
        count=json.loads(raw)['count']
        if type(count) is not int or count<1: raise ValueError()
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        raise AuthError(503,'AI_TOKENIZE_FAILED','모델 서버의 토큰 계수 연결을 확인해 주세요. 입력은 유지됩니다.') from None
    # 배포 안내를 보수적으로 해석하여 입력+출력 전체를 4096 이내로 제한한다.
    available=4096-count-64
    if available<requested:
        raise AuthError(422,'AI_INPUT_TOO_LONG','AI 입력과 답변 공간이 4,096토큰을 넘어요. 현장 설명·사진 수를 줄여 주세요. 입력은 유지됩니다.')
    return requested


def request_analysis(media, images, scenarios, previous=None):
    base, model, tokens = configuration()
    prompt=(ROOT/'ai/catalog_ai/system_prompt.md').read_text(encoding='utf-8-sig')
    candidate_index=[{k:s[k] for k in ('id','title','task','scenario')} for s in scenarios]
    prompt+='\n기준 후보 목록:\n'+json.dumps(candidate_index,ensure_ascii=False,separators=(',',':'))
    prompt+='\n출력 형식:\n'+'{"candidates":[{"scenario_id":"기준 ID","rationale":"짧은 이유","evidence":[{"media_id":"입력 ID","statement":"근거"}],"questions":[{"id":"Q1","text":"질문"}]}],"unmatched_risks":[]}'
    previous_context=[{k:p[k] for k in ('scenario_id','rationale','evidence','questions')} for p in (previous or [])]
    task={'media':media,'previous':previous_context,'existing_scenario_ids':[p['scenario_id'] for p in (previous or [])]}
    content=json.dumps(task,ensure_ascii=False)  # EXAONE에는 탐지 JSON과 텍스트만 전달한다.
    headers=model_headers()
    messages=[{'role':'system','content':prompt},{'role':'user','content':content}]
    tokens=output_budget(base,model,messages,headers,tokens)
    payload={'model':model,'messages':messages,
             'temperature':0,'max_tokens':tokens,'response_format':{'type':'json_object'}}
    try:
        with httpx.Client(timeout=httpx.Timeout(180,connect=10),follow_redirects=False,trust_env=False) as client:
            with client.stream('POST',base+'/chat/completions',json=payload,headers=headers) as response:
                response.raise_for_status()
                raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>2_000_000:raise ValueError('응답 크기 초과')
        choice=json.loads(raw)['choices'][0]
        if choice.get('finish_reason') not in ('stop',None):raise ValueError('미완료 응답')
        return json.loads(choice['message']['content'])
    except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
        raise AuthError(503,'AI_REQUEST_FAILED','AI 분석을 완료하지 못했어요. 입력을 유지하고 다시 시도해 주세요.') from None


def analyze(context, scenarios, answers=None, previous=None):
    # 설정·스키마가 잘못됐을 때 다른 모드나 고정 등급으로 자동 대체하지 않는다.
    _,model,_=configuration()
    media,images=make_input(context,answers)
    known={s['id']:s for s in scenarios}
    if not known or any(s['policy_version']!=POLICY for s in scenarios):
        raise AuthError(503,'AI_CATALOG_MISSING','현재 정책의 기준 DB를 준비해 주세요.')
    raw=request_analysis(media,images,scenarios,previous)
    try:
        parsed=Analysis.model_validate(raw)
        if sum(len(c.questions) for c in parsed.candidates)>100:raise ValueError('질문 한도 초과')
        ids=[c.scenario_id for c in parsed.candidates]
        if len(ids)!=len(set(ids)) or set(ids)-known.keys():raise ValueError('잘못된 기준 ID')
        if previous and set(ids)!={c['scenario_id'] for c in previous}:raise ValueError('기존 후보 누락·변경')
        if set(context.get('catalog_ids',[]))-set(ids):raise ValueError('사용자 선택 후보 누락')
        media_ids={m['id'] for m in media}
        for c in parsed.candidates:
            if {e.media_id for e in c.evidence}-media_ids:raise ValueError('없는 근거 ID')
            if len({q.id for q in c.questions})!=len(c.questions):raise ValueError('중복 질문 ID')
    except (ValidationError,ValueError,TypeError):
        raise AuthError(502,'AI_RESPONSE_INVALID','AI 후보 또는 근거 형식을 확인하지 못했어요. 임의 등급으로 대체하지 않습니다.') from None
    if parsed.unmatched_risks:
        raise AuthError(422,'AI_OUTSIDE_CATALOG','현재 기준으로 다룰 수 없는 위험이 포함돼 있어요. 입력과 기준 범위를 검토해 주세요.')
    if context.get('photos'):
        for candidate in parsed.candidates:
            qid='EQUIPMENT_CONFIRM_'+candidate.scenario_id
            if any(a.get('question_id')==qid for a in (answers or [])): continue
            if any(q.id==qid for q in candidate.questions): continue
            from schemas.catalog_ai import Question
            candidate.questions.append(Question(id=qid,text='사진 탐지는 틀릴 수 있어요. 이 위험 후보와 관련된 기기가 실제로 있고 해당 작업을 하나요? 잘못 인식한 기기는 답변에 알려 주세요.'))
    if any(len(c.questions)>11 for c in parsed.candidates) or sum(len(c.questions) for c in parsed.candidates)>100:
        raise AuthError(422,'AI_QUESTION_LIMIT','확인 질문이 너무 많아요. 입력 범위를 나누어 주세요. 질문을 삭제하지 않았습니다.')
    stamp={'model':model,'analyzed_at':datetime.now(timezone.utc).isoformat(),'policy_version':POLICY,'prompt_version':'catalog-ai-2'}
    if context.get('_photo_cache'):stamp['photo_cache']=context['_photo_cache']
    return [dict(c.model_dump(),input_evidence=[m for m in media if m['id'] in {e.media_id for e in c.evidence}],**stamp) for c in parsed.candidates]


def restore_input(doc):
    context={'text':'','voice_text':'','photos':[],'machines':doc['machines']}
    for f in doc['inputs']:
        if f['file_type']=='P':context['photos'].append({'name':f['ori_file_nm'],'place':f['place_nm'],'data':f['file_text']})
        elif f['file_type']=='T':context['text']+='\n'+f['file_text']
        elif f['file_type']=='V':context['voice_text']+='\n'+f['file_text']
    for item in doc['items']:
        cache=(item.get('catalog') or {}).get('ai_analysis',{}).get('photo_cache')
        if cache:
            context['_photo_cache']=cache
            break
    return context
