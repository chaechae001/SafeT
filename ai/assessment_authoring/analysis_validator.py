"""모델 결과의 계약·소속·입력 인용 검증 및 누락 조치 정규화."""
import copy
from contracts.assessment_authoring.v1.validate import validate_bundles
from .catalog import catalog_index


def validate_analysis(i, r, a, catalog_snapshot, legal_registry=None):
    catalog = catalog_index(catalog_snapshot)
    validate_bundles(i, r, a, catalog, legal_registry or [])
    a = copy.deepcopy(a)
    for c in a["candidates"]:
        scenario = catalog[c["scenario_id"]]
        existing = {e["control_id"]: e for e in c["control_evidence"]}
        c["control_evidence"] = [existing.get(control["id"], dict(control_id=control["id"],
            state="unknown", evidence_refs=[], statement="입력에서 확인되지 않음"))
            for control in scenario["controls"]]
    return a
