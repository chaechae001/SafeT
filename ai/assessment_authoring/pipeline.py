"""입력·추출 담당 구현을 함수 주입으로 연결하는 독립 실행 경로."""
import copy
from .retrieval_adapter import retrieve_with_evidence, candidate_batches
from .assessment_composer import render_assessment

def run_pipeline(raw_request, *, build_context, extract_analysis, catalog_snapshot,
                 rag_provider=None, rag_links=None, legal_registry=None):
    context = build_context(copy.deepcopy(raw_request))
    retrieval, trace = retrieve_with_evidence(context, catalog_snapshot, rag_provider=rag_provider,
                                              rag_links=rag_links, legal_registry=legal_registry)
    analysis = dict(contract_version="assessment-authoring-1", candidates=[], unmatched_risks=[])
    has_work_input = any(m["kind"] in ("text", "voice_transcript") for m in context["media"])
    batches = candidate_batches(retrieval) if has_work_input else []
    if not has_work_input:
        trace["work_review_candidates"] = [c["scenario_id"] for c in retrieval["candidates"]]
    for batch in batches:
        part = extract_analysis(copy.deepcopy(context), copy.deepcopy(batch), copy.deepcopy(catalog_snapshot))
        # 각 배치 소속을 먼저 검사하여 다른 배치 ID를 끼워넣지 못하게 한다.
        from .analysis_validator import validate_analysis
        part = validate_analysis(context, batch, part, catalog_snapshot, legal_registry)
        analysis["candidates"].extend(part["candidates"])
        analysis["unmatched_risks"].extend(part["unmatched_risks"])
    rendered = render_assessment(context, retrieval, analysis, catalog_snapshot, legal_registry=legal_registry)
    return dict(input=context, retrieval=retrieval, analysis=analysis, assessment=rendered, retrieval_trace=trace)

