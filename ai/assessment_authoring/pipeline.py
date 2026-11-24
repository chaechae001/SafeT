"""입력·추출 담당 구현을 함수 주입으로 연결하는 독립 실행 경로."""
import copy
from .retrieval_adapter import retrieve_with_evidence, candidate_batches, work_supported
from .assessment_composer import render_assessment
from .segments import split_sentences

def run_pipeline(raw_request, *, build_context, extract_analysis, catalog_snapshot,
                 rag_provider=None, rag_links=None, legal_registry=None, extract_with_evidence=None, batch_size=3,
                 negation_judge=None, candidate_enricher=None):
    context = build_context(copy.deepcopy(raw_request))
    retrieval, trace = retrieve_with_evidence(context, catalog_snapshot, rag_provider=rag_provider,
                                              rag_links=rag_links, legal_registry=legal_registry,
                                              negation_judge=negation_judge)
    if candidate_enricher is not None:
        candidate_enricher(context, retrieval, trace)
    analysis = dict(contract_version="assessment-authoring-1", candidates=[], unmatched_risks=[])
    has_work_input = any(m["kind"] in ("text", "voice_transcript") for m in context["media"])
    # 사진·등록 기기만으로 올라온 후보는 노출 근거가 아니다. 작업 문장이 그 작업·기기를
    # 직접 언급할 때만 평가 행으로 인정하고, 아니면 작업 미확인 후보로 남긴다.
    work_media = {m["id"] for m in context["media"] if m["kind"] in ("text", "voice_transcript")}
    scenarios = {s["id"]: s for s in catalog_snapshot["scenarios"]}
    # 미사용인지 불확실한 작업도 같은 기준(작업 근거)을 적용한다.
    needs_work = set(trace["equipment_candidates"]) | set(trace.get("uncertain_work_candidates", []))
    equipment_only = needs_work - set(trace["text_candidates"])
    # 모델이 인용할 수 있는 작업 문장 중 어느 것도 작업 근거가 되지 않는 후보는 모델 결과와 관계없이
    # 아래에서 제외된다. 결과가 같으므로 모델 호출을 하지 않는다(호출 수·지연 감소, 다기기 502 예방).
    sentences = [part for m in context["media"] if m["id"] in work_media for part in split_sentences(m["text"])]
    unsupportable = {sid for sid in equipment_only
                     if not any(work_supported(scenarios[sid], sentence) for sentence in sentences)}
    trace["extraction_skipped"] = sorted(unsupportable)
    for sid in sorted(unsupportable):
        trace["diagnostics"].append("작업 근거 문장 없음, 모델 호출 생략: " + sid)
    to_extract = dict(retrieval, candidates=[c for c in retrieval["candidates"] if c["scenario_id"] not in unsupportable])
    batches = candidate_batches(to_extract, size=batch_size) if has_work_input and to_extract["candidates"] else []
    for batch in batches:
        if extract_with_evidence is None:
            part = extract_analysis(copy.deepcopy(context), copy.deepcopy(batch), copy.deepcopy(catalog_snapshot))
        else:
            evidence = {row["scenario_id"]: copy.deepcopy(trace["scenario_evidence"].get(row["scenario_id"], []))
                        for row in batch["candidates"]}
            part = extract_with_evidence(copy.deepcopy(context), copy.deepcopy(batch),
                                         copy.deepcopy(catalog_snapshot), evidence)
        # 각 배치 소속을 먼저 검사하여 다른 배치 ID를 끼워넣지 못하게 한다.
        from .analysis_validator import validate_analysis
        part = validate_analysis(context, batch, part, catalog_snapshot, legal_registry)
        analysis["candidates"].extend(part["candidates"])
        analysis["unmatched_risks"].extend(part["unmatched_risks"])
    supported = []
    for candidate in analysis["candidates"]:
        sid = candidate["scenario_id"]
        if sid in equipment_only and not any(
                quote["media_id"] in work_media and work_supported(scenarios[sid], quote["statement"])
                for quote in candidate["evidence"]):
            trace["diagnostics"].append("작업 근거 없음: " + sid)
            continue
        supported.append(candidate)
    analysis["candidates"] = supported
    denied = set(trace["not_applicable_candidates"])
    assessed = {candidate["scenario_id"] for candidate in analysis["candidates"]}
    pending = needs_work - assessed - denied
    review_candidates = [
        {"scenario_id": sid, "reason": "input_denies_work" if sid in denied else "work_unconfirmed"}
        for sid in sorted(pending | denied)
    ]
    trace["work_review_candidates"] = sorted(pending)
    rendered = render_assessment(context, retrieval, analysis, catalog_snapshot,
                                 legal_registry=legal_registry, review_candidates=review_candidates,
                                 document_evidence=trace["scenario_evidence"])
    from .document_evidence import attach_document_evidence
    rendered = attach_document_evidence(rendered, trace["scenario_evidence"])
    return dict(input=context, retrieval=retrieval, analysis=analysis, assessment=rendered, retrieval_trace=trace)

