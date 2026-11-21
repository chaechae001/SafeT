"""내부 검토 화면(--risk-test)의 판정. 실제 평가표와 같은 판정 함수(backend.domain.risk_policy.evaluate)와
같은 시나리오 카탈로그(FOOD-3LEVEL-1.2, scenario_map.load_catalog)를 쓴다. 판정 근거 문구도 evaluate 결과 그대로다."""
import json
import os
import sqlite3
from pathlib import Path

from backend.domain.risk_policy import evaluate


def assess_selection(linker, body, *, draft=False):
    card = body.get("card_id")
    sid = body.get("scenario_id")
    if not isinstance(card, str) or not card:
        raise ValueError("위험카드 ID가 필요합니다.")
    if sid is not None and not isinstance(sid, str):
        raise ValueError("시나리오 ID가 올바르지 않습니다.")
    scenario = linker.by_id.get(sid) if linker else None
    if sid and not scenario:
        raise ValueError("등록되지 않은 시나리오입니다.")
    controls = scenario["controls"] if scenario else []
    known = {c["id"] for c in controls}

    def selected(key):
        values = body.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or v not in known for v in values):
            raise ValueError("해당 시나리오의 기준 조치를 선택해 주세요.")
        return set(values)

    current = set() if draft else selected("current_ids")
    plans = set() if draft else selected("plan_ids")
    credited = current | plans
    policy = evaluate(scenario, credited, answered=True) if scenario else None
    field = "current_risk" if draft else "expected_risk"
    result = {"card_id": card, "scenario_id": sid, field: policy["grade"] if policy else None,
              "status": ("draft" if draft else "recalculated") if policy else "unmapped"}
    result["assessment_policy"] = policy["policy_version"] if policy else None
    result["reduction_required"] = result[field] != "하"  # 미연결(None)도 검토 대상
    critical = {c["id"] for c in controls if c["critical"]}
    missing = sorted(critical - credited)
    audit = {
        **result, "stage": "draft" if draft else "expected",
        "severity": policy["severity"] if policy else None,
        "control_band": policy["control_band"] if policy else None,
        "current_ids": sorted(current), "plan_ids": sorted(plans),
        "critical_ids": sorted(critical), "missing_critical_ids": missing,
        "source_refs": scenario.get("source_refs", []) if scenario else [],
        "applied_control_ids": policy["applied_control_ids"] if policy else [],
        "missing_supplementary_ids": policy["missing_supplementary_ids"] if policy else [],
        "reason": policy["reason"] if policy else "시나리오 미연결 · 판단 필요(담당자 검토)",
    }
    return result, audit


def grade_selection(linker, body, *, draft=False):
    result, _ = assess_selection(linker, body, draft=draft)
    return result


def record_selection(linker, body, *, draft=False):
    result, audit = assess_selection(linker, body, draft=draft)
    configured = os.getenv("SAFET_RISK_AUDIT_DB")
    path = Path(configured) if configured else Path.home() / ".safet" / "risk-assessments.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS assessments "
                   "(id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)")
        db.execute("INSERT INTO assessments(payload) VALUES (?)", (json.dumps(audit, ensure_ascii=False),))
    return result
