"""검증된 입력 근거로 계산한다. 모델·DB 호출과 사용자 확인 플래그 없음."""
import copy
from backend.domain.risk_policy import MATRIX
from .analysis_validator import validate_analysis
from .catalog import catalog_index
from .contracts import schema

def compose_assessment(context, retrieval_bundle, analysis_bundle, catalog_snapshot, *, legal_registry=None):
    analysis = validate_analysis(context, retrieval_bundle, analysis_bundle, catalog_snapshot, legal_registry)
    catalog = catalog_index(catalog_snapshot)
    items = []
    for candidate in analysis["candidates"]:
        scenario = catalog[candidate["scenario_id"]]
        supported = {e["control_id"] for e in candidate["control_evidence"] if e["state"] == "supported"}
        critical = {c["id"] for c in scenario["controls"] if c["critical"]}
        known = {c["id"] for c in scenario["controls"]}
        band = 3 if not critical <= supported else (1 if known <= supported else 2)
        items.append(dict(scenario_id=scenario["id"], severity=scenario["severity"], control_band=band,
                          grade=MATRIX[scenario["severity"]][band], status="estimated_from_input"))
    unmatched = list(dict.fromkeys(retrieval_bundle["unmatched"] + analysis["unmatched_risks"]))
    result = dict(contract_version="assessment-authoring-1", assessment_mode="input_based",
                  decision_policy_version="CATALOG-MVP-1.1-AUTO-1.0", items=items, unmatched_risks=unmatched,
                  result_status=("partial" if unmatched else "complete") if items else "no_supported_result")
    schema("assessment", result)
    return result

def render_assessment(context, retrieval_bundle, analysis_bundle, catalog_snapshot, *, legal_registry=None):
    analysis = validate_analysis(context, retrieval_bundle, analysis_bundle, catalog_snapshot, legal_registry)
    core = compose_assessment(context, retrieval_bundle, analysis, catalog_snapshot, legal_registry=legal_registry)
    catalog = catalog_index(catalog_snapshot)
    retrieved = {c["scenario_id"]: c for c in retrieval_bundle["candidates"]}
    rows = []
    for candidate, result in zip(analysis["candidates"], core["items"]):
        scenario = catalog[candidate["scenario_id"]]
        states = {e["control_id"]: e["state"] for e in candidate["control_evidence"]}
        rows.append(dict(result, risk=scenario["scenario"], rationale=candidate["rationale"],
            current_controls=[e for e in candidate["control_evidence"] if e["state"] == "supported"],
            improvement_candidates=[{"control_id": c["id"], "text": c["plan_text"]}
                for c in scenario["controls"] if states[c["id"]] != "supported"],
            control_evidence=candidate["control_evidence"], evidence=candidate["evidence"],
            assumptions=candidate["assumptions"], source_refs=retrieved[scenario["id"]]["source_refs"],
            legal_refs=retrieved[scenario["id"]]["legal_refs"]))
    return copy.deepcopy(dict(core=core, rows=rows, base_policy_version=catalog_snapshot["policy_version"]))

