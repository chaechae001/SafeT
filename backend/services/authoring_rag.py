"""입력 기반 평가 파이프라인을 기존 평가표 API와 저장 구조에 연결한다."""
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import text

from services.auth import AuthError
from services import catalog_ai, rag_retrieval

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ai.assessment_authoring.pipeline import run_pipeline
from ai.assessment_authoring.detection_adapter import photo_detector_source
from ai.assessment_authoring.input_adapter import build_context as adapt_input
from ai.assessment_authoring.contracts import load_catalog
from ai.assessment_authoring.evidence_qualification import qualify_direct_evidence
from ai.assessment_authoring.live_text_check import build_messages, request_json, output_budget, parse_completion, model_response_format
from ai.assessment_authoring.retrieval_adapter import _positive

SOURCE = 'authoring_rag_v1'
LINK_FILE = '261116_RAG_기기위험요인링크_v2_DR.jsonl'
RAG_LINKS = {'EQ_FRYER:burn': ['FRY'], 'EQ_FRYER:slip': ['ENV']}
SIGNALS = {'상': 'R', '중': 'Y', '하': 'G'}


def enabled():
    return os.getenv('SAFET_ASSESSMENT_MODE') == SOURCE


def qualified_candidates(ids, k=None):
    response = rag_retrieval.candidates(ids, k=k)
    try:
        root = rag_retrieval.data_dir()
        manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
        hashes = {f['file']: f['sha256'] for f in manifest['files']}
        if LINK_FILE not in manifest['roles']['retrieval']:
            raise ValueError('not retrieval data')
        raw = (root / LINK_FILE).read_bytes()
        if hashlib.sha256(raw).hexdigest() != hashes[LINK_FILE]:
            raise ValueError('link hash mismatch')
        links = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
        qualified, excluded = qualify_direct_evidence(response, links)
        qualified['excluded_links'] = excluded
        qualified['links_sha256'] = hashes[LINK_FILE]
        from ai.assessment_authoring.reference_expansion import expand
        return expand(qualified, os.getenv("SAFET_RAG_CONTEXT_DIR"))
    except (OSError, ValueError, KeyError, TypeError):
        raise AuthError(503, 'RAG_LINKS_INVALID', '검색 근거 연결 파일의 구성·무결성을 확인해 주세요.') from None


def build_context(context):
    if context.get('catalog_ids'):
        raise AuthError(422, 'AUTHORING_INPUT_UNSUPPORTED', '작업 설명, 음성 전사문 또는 사진을 사용해 주세요.')
    # 등록 기기 전체를 검색 후보로 추가하면 기존 텍스트 평가의 범위가 달라진다.
    observed_context = {**context, 'machines': []}
    bundle = adapt_input(observed_context)
    if '_photo_cache' in observed_context:
        context['_photo_cache'] = observed_context['_photo_cache']
    work = '\n'.join(m['text'] for m in bundle['media'] if m['kind'] in ('text', 'voice_transcript'))
    if _positive(work, '튀김기') and 'EQ_FRYER' not in bundle['equipment_ids']:
        bundle['equipment_ids'].append('EQ_FRYER')
    return bundle


def cached_photos(db, email, work_no, photos):
    cache = db.execute(text("""
        SELECT JSON_EXTRACT(authoring_snapshot, '$.photo_cache')
        FROM eval_mst
        WHERE email=:email AND work_no=:work AND del_yn='N' AND generation_source=:source
          AND JSON_VALUE(authoring_snapshot, '$.photo_cache.fingerprint')=:fingerprint
          AND JSON_VALUE(authoring_snapshot, '$.photo_cache.detector_source')=:detector
        ORDER BY eval_no DESC LIMIT 1
    """), dict(email=email, work=work_no, source=SOURCE,
               fingerprint=catalog_ai.photo_fingerprint(photos), detector=photo_detector_source())).scalar()
    return json.loads(cache) if cache else None


def extract(context, retrieval, snapshot, evidence):
    base = catalog_ai.gateway_url()
    _, model, _ = catalog_ai.configuration()
    catalog_ai.model_headers()  # 관문 인증 설정 검사
    if not base:
        raise AuthError(503, 'AI_UNCONFIGURED', '입력 기반 평가의 AI 관문을 설정해 주세요.')
    messages = build_messages(context, retrieval, snapshot, evidence)
    key = os.getenv('SAFET_AI_API_KEY', '')
    from ai.assessment_authoring.extraction_adapter import check_batch_output, ExtractionError
    try:
        count = request_json(base, key, '/tokenize', dict(model=model, messages=messages, add_generation_prompt=True))['count']
        budget = output_budget(count)
        response = request_json(base, key, '/v1/chat/completions', dict(model=model, messages=messages,
            temperature=0, max_tokens=budget, response_format=model_response_format(context, retrieval, snapshot)))
        decoded = parse_completion(response, context)
        checked = check_batch_output(decoded, context, [r['scenario_id'] for r in retrieval['candidates']],
                                  {s['id']: s for s in snapshot['scenarios']})
        # A fryer document can suggest a passage hazard, but only the user's work can establish exposure.
        from ai.assessment_authoring.retrieval_adapter import text_candidates
        checked['candidates'] = [candidate for candidate in checked['candidates']
            if candidate['scenario_id'] != 'ENV' or not evidence.get('ENV')
            or any('ENV' in text_candidates({'id': quote['media_id'], 'text': quote['statement']}, [])[0]
                   for quote in candidate['evidence'])]
        return checked
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, IndexError, ExtractionError):
        raise AuthError(502, 'AUTHORING_MODEL_FAILED', '모델 응답을 완료하지 못했어요. 입력을 유지하고 다시 시도해 주세요.') from None


def negation_judge():
    """SAFET_NEGATION_JUDGE=exaone일 때만 불확실한 미사용 진술을 관문 모델로 확인한다(기본 꺼짐).

    모델 판정은 형태소 규칙의 잠정 판정과 같을 때만 확정하고, 호출 실패·불일치는 작업 미확인으로 둔다.
    """
    if os.getenv('SAFET_NEGATION_JUDGE', '').strip() != 'exaone':
        return None
    base = catalog_ai.gateway_url()
    _, model, _ = catalog_ai.configuration()
    if not base or not model:
        return None
    from ai.assessment_authoring.negation_judge import exaone_judge
    return exaone_judge(base, os.getenv('SAFET_AI_API_KEY', ''), model)


def generate(scenarios, context):
    snapshot = load_catalog()
    byid = {s['id']:s for s in scenarios}
    if byid != {s['id']:s for s in snapshot['scenarios']}:
        raise AuthError(503, 'AUTHORING_CATALOG_MISMATCH', 'DB 기준과 파이프라인 기준 버전이 일치하지 않습니다.')
    try:
        bundle = build_context(context)
        out = run_pipeline(bundle, build_context=lambda prepared: prepared, extract_analysis=None,
            catalog_snapshot=snapshot, rag_provider=qualified_candidates, rag_links=RAG_LINKS,
            extract_with_evidence=extract, batch_size=1, negation_judge=negation_judge())
    except ValueError:
        raise AuthError(502, 'AUTHORING_RESPONSE_INVALID', '분석 근거 검증에 실패했어요. 평가표는 생성하지 않았습니다.') from None
    if not out['assessment']['rows'] and not out['assessment']['core']['review_candidates']:
        raise AuthError(422, 'AUTHORING_NO_RESULT', '현재 기준으로 연결할 수 있는 위험 항목이 없습니다.')
    reports = {a['scenario_id']:a for a in out['analysis']['candidates']}
    trace = out['retrieval_trace']
    rag = trace['rag_response'] or {}
    stamp = dict(model=os.getenv('SAFET_AI_MODEL'), generated_at=datetime.now(timezone.utc).isoformat(),
        assessment_mode='input_based', result_status=out['assessment']['core']['result_status'],
        base_policy_version=out['assessment']['core']['base_policy_version'],
        review_candidates=out['assessment']['core']['review_candidates'],
        unmatched_risks=out['assessment']['core']['unmatched_risks'],
        decision_policy_version=out['assessment']['core']['decision_policy_version'],
        retrieval_mode=trace['retrieval_mode'], data_version=rag.get('data_version'),
        index_sha256=rag.get('index_sha256'), links_sha256=rag.get('links_sha256'),
        excluded_links=rag.get('excluded_links', []),
        context_version=rag.get('context_version'), context_sha256=rag.get('context_sha256'))
    items = []
    for row in out['assessment']['rows']:
        scenario = byid[row['scenario_id']]
        supported = {e['control_id'] for e in row['current_controls']}
        current = [c['current_text'] for c in scenario['controls'] if c['id'] in supported]
        items.append(dict(job=scenario['task'][:100], title=scenario['title'][:200], type=scenario['event'][:50],
            cause=row['risk'][:500], signal=SIGNALS[row['grade']], reason=row['rationale'][:500], curr=current,
            plans=[c['text'] for c in row['improvement_candidates']],
            authoring=dict(**stamp, row=copy.deepcopy(row), analysis=reports[row['scenario_id']])))
    return SOURCE, items, stamp


def initialize(db, item_id, snapshot):
    db.execute(text('UPDATE eval_dtl SET catalog_state=:s WHERE eval_dtl_no=:n'),
        {'s':json.dumps({'authoring':snapshot}, ensure_ascii=False), 'n':item_id})
    db.execute(text("UPDATE eval_action SET check_yn='Y' WHERE eval_dtl_no=:n AND action_type='C'"), {'n':item_id})


def enrich(item, state):
    if not state or 'authoring' not in state:
        return
    snapshot = copy.deepcopy(state['authoring'])
    from ai.assessment_authoring.explanations import document_summaries
    snapshot['row'].setdefault('document_summaries', document_summaries(snapshot['row']['document_evidence']))
    item.pop('catalog', None)
    item['work_review'] = state.get('work_review')
    item['work_reviewed'] = bool(item['work_review'])
    item['assessment_mode'] = 'input_based'
    item['authoring'] = snapshot
    item['reason'] = snapshot['row']['rationale']
    item['document_evidence'] = snapshot['row']['document_evidence']


def protect_current(original, edit):
    expected = [{k:a[k] for k in ('id','text','checked')} for a in original['curr']]
    if ([a.model_dump() for a in edit.curr] != expected or edit.none != original['none'] or edit.controls_reviewed):
        raise AuthError(400, 'AUTHORING_CURRENT_IMMUTABLE', '입력에서 분석한 현재 조치와 위험도는 이 화면에서 변경할 수 없습니다.')
