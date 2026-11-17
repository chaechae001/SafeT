"""v2.1 스키마·예시 생성 (2026-11-17).

팀 결정: AI 출력 형식은 HITL v2를 따르고, 위험도 계산은 백엔드 정책 CATALOG-MVP-1.0
(backend/domain/risk_policy.py, contracts/catalog_risk, SafeT #10)을 따른다.
- 바뀌는 것: 사용자 선택(c)과 위험도 결과(d). 가능성×중대성 척도 대신 피해 수준(카탈로그) × 조치 구간.
- 그대로인 것: 기기 인식(a), 위험요인 후보(b) 본문. 후보에 카탈로그 시나리오 ID 연결 필드만 추가.
v2 파일은 수정하지 않는다(기존 파이프라인이 v2를 검증에 쓴다).
실행: 이 폴더의 상위에서 python scripts/build_v2_1.py
"""
import copy, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V2, OUT, EX = ROOT / "schemas_v2", ROOT / "schemas_v2_1", ROOT / "examples_v2_1"
OUT.mkdir(exist_ok=True); EX.mkdir(exist_ok=True)
BASE = "https://safe-t.local/schemas/v2_1/"
POLICY_SRC = "SafeT backend/domain/risk_policy.py · docs/implementation/catalog-risk.md (main 1daa5d8, #10)"


def load(name):
    return json.loads((V2 / name).read_text(encoding="utf-8"))


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


# common: v2를 그대로 쓰고, 정책 관련 정의만 추가한다
common = load("common.v2.schema.json")
common["$id"] = BASE + "common.v2_1.schema.json"
common["title"] = "Safe-T 계약 v2.1 공통 정의"
d = common["$defs"]
d["CatalogScenarioId"] = {"type": "string", "pattern": "^[A-Z][A-Z0-9_]*$",
                          "description": "contracts/catalog_risk/catalog.json scenarios[].id"}
d["ControlId"] = {"type": "string", "pattern": "^[A-Z][A-Z0-9_]*-C[0-9]+$",
                  "description": "catalog.json scenarios[].controls[].id (예: ENV-C1)"}
d["PolicyVersion"] = {"const": "CATALOG-MVP-1.0", "description": "백엔드 위험도 정책 버전. 바뀌면 이 계약도 올린다"}
d["Grade"] = {"type": ["string", "null"], "enum": ["상", "중", "하", None]}
d["Signal"] = {"type": "string", "enum": ["R", "Y", "G", "N"],
               "description": "상=R, 중=Y, 하=G, 미계산=N(판단 필요). 백엔드 SIGNAL 표와 같다"}
save(OUT / "common.v2_1.schema.json", common)

# 같은 폴더의 common을 가리키도록 $ref 교체
def reref(o):
    if isinstance(o, dict):
        return {k: (v.replace("common.v2.schema.json", "common.v2_1.schema.json") if k == "$ref" and isinstance(v, str) else reref(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [reref(x) for x in o]
    return o

# (a) 기기 인식, (b) 요청: 내용 동일, id만 v2_1
for name, new in [("equipment_confirmed.v2.schema.json", "equipment_confirmed.v2_1.schema.json"),
                  ("hazard_candidates.v2.request.schema.json", "hazard_candidates.v2_1.request.schema.json")]:
    s = reref(load(name)); s["$id"] = BASE + new
    save(OUT / new, s)

# (b) 응답: 후보에 catalog_scenario_ids(선택) 추가
resp = reref(load("hazard_candidates.v2.response.schema.json"))
resp["$id"] = BASE + "hazard_candidates.v2_1.response.schema.json"
cand = resp["else"]["properties"]["groups"]["items"]["properties"]["candidates"]["items"]
cand["properties"]["catalog_scenario_ids"] = {
    "type": "array", "items": {"$ref": "common.v2_1.schema.json#/$defs/CatalogScenarioId"}, "uniqueItems": True,
    "description": "v2.1 추가. 이 후보와 같은 사고 경로의 카탈로그 시나리오. 백엔드가 키워드로 찾거나 LLM이 주어진 목록 안에서 고른다. 없으면 빈 배열(위험도 계산 불가, 사용자 확인 필요)"}
save(OUT / "hazard_candidates.v2_1.response.schema.json", resp)

# (c) 사용자 선택: 가능성·중대성 → 카탈로그 시나리오 + 현재·계획 조치 ID
sel = reref(load("user_selection.v2.schema.json"))
sel["$id"] = BASE + "user_selection.v2_1.schema.json"
sel["description"] = ("사용자가 고른 위험요인과 현재 조치·개선 계획. 피해 수준은 카탈로그 시나리오가 정하고 사용자는 고르지 않는다. "
                      "위험도는 백엔드가 계산한다(" + POLICY_SRC + ").")
sel["required"] = ["assessment_id", "policy_version", "candidates_request_id", "selections"]
props = sel["properties"]
props.pop("scale_id"); props.pop("scale_version")
props["policy_version"] = {"$ref": "common.v2_1.schema.json#/$defs/PolicyVersion"}
item = props["selections"]["items"]
ip = item["properties"]
for k in ("likelihood", "severity", "phase", "parent_selection_id", "current_measures"):
    ip.pop(k)
ip["catalog_scenario_id"] = {"oneOf": [{"$ref": "common.v2_1.schema.json#/$defs/CatalogScenarioId"}, {"type": "null"}],
                             "description": "사용자가 확인한 카탈로그 시나리오. null이면 직접 추가 위험이며 계산하지 않는다(판단 필요)"}
ip["current_control_ids"] = {"type": "array", "uniqueItems": True, "items": {"$ref": "common.v2_1.schema.json#/$defs/ControlId"},
                             "description": "현재 시행 중이라고 고른 카탈로그 조치"}
ip["no_current_controls"] = {"type": "boolean", "description": "'현재 조치 없음'을 명시적으로 골랐는지. 둘 다 비어 있고 false면 미응답"}
ip["plan_control_ids"] = {"type": "array", "uniqueItems": True, "items": {"$ref": "common.v2_1.schema.json#/$defs/ControlId"},
                          "description": "개선 계획으로 고른 카탈로그 조치. 예상 위험도 계산에 쓴다"}
ip["custom_current_measures"] = {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 500},
                                 "description": "직접 적은 현재 조치. 저장만 하고 계산에는 쓰지 않는다"}
item["required"] = ["selection_id", "equipment_id", "origin", "hazard", "accident_type", "catalog_scenario_id",
                    "current_control_ids", "no_current_controls", "plan_control_ids", "selected_measures", "decided_by", "decided_at"]
item["allOf"] = [item["allOf"][0],
                 {"if": {"properties": {"no_current_controls": {"const": True}}},
                  "then": {"properties": {"current_control_ids": {"maxItems": 0}}}}]
save(OUT / "user_selection.v2_1.schema.json", sel)

# (d) 위험도 결과: 백엔드 정책 결과 형식
res = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": BASE + "risk_result.v2_1.schema.json",
    "title": "(d) 위험도 계산 결과 (백엔드 정책 → 화면)",
    "description": ("백엔드 risk_policy.evaluate 결과를 항목·단계별로 담는다. AI(LLM)는 관여하지 않는다. "
                    "피해 S1~S3(카탈로그) × 조치 구간 C1~C3 → 상·중·하. 미응답이면 needs_information·N. "
                    "예상(expected)은 계획 이행을 가정한 값이며 현재 결과를 바꾸지 않는다. 근거: " + POLICY_SRC),
    "type": "object", "additionalProperties": False,
    "required": ["assessment_id", "computed_by", "policy_version", "computed_at", "results"],
    "properties": {
        "assessment_id": {"type": "string"},
        "computed_by": {"const": "backend_risk_policy"},
        "policy_version": {"$ref": "common.v2_1.schema.json#/$defs/PolicyVersion"},
        "computed_at": {"$ref": "common.v2_1.schema.json#/$defs/IsoDateTime"},
        "results": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["selection_id", "phase", "status", "catalog_scenario_id", "severity", "control_band", "grade", "signal", "reason"],
            "properties": {
                "selection_id": {"type": "string"},
                "phase": {"type": "string", "enum": ["current", "expected"],
                          "description": "current=현재 조치 기준. expected=현재+계획 조치 이행 가정"},
                "status": {"type": "string", "enum": ["calculated", "needs_information", "not_in_catalog"],
                           "description": "not_in_catalog=시나리오가 없는 직접 추가 위험. 판단 필요로 표시"},
                "catalog_scenario_id": {"oneOf": [{"$ref": "common.v2_1.schema.json#/$defs/CatalogScenarioId"}, {"type": "null"}]},
                "severity": {"type": ["integer", "null"], "enum": [1, 2, 3, None], "description": "카탈로그 피해 수준. 1 경미, 2 치료 필요, 3 사망·영구장해 가능"},
                "control_band": {"type": ["integer", "null"], "enum": [1, 2, 3, None],
                                 "description": "1 필요한 조치 모두, 2 핵심 조치만, 3 핵심 조치 미선택"},
                "grade": {"$ref": "common.v2_1.schema.json#/$defs/Grade"},
                "signal": {"$ref": "common.v2_1.schema.json#/$defs/Signal"},
                "reason": {"type": "string"}
            },
            "allOf": [
                {"if": {"properties": {"status": {"const": "calculated"}}},
                 "then": {"properties": {"severity": {"type": "integer"}, "control_band": {"type": "integer"},
                                         "grade": {"type": "string"}, "signal": {"enum": ["R", "Y", "G"]}}},
                 "else": {"properties": {"control_band": {"type": "null"}, "grade": {"type": "null"}, "signal": {"const": "N"}}}}
            ]}}
    }
}
save(OUT / "risk_result.v2_1.schema.json", res)

# 정책 사본(참조용). 운영 기준은 백엔드 코드다
policy = {
    "policy_version": "CATALOG-MVP-1.0", "owner": "backend", "source": POLICY_SRC, "copied_at": "2026-11-17",
    "note": "참조용 사본. 기준이 바뀌면 백엔드 코드가 우선이며 이 파일과 계약 버전을 함께 올린다. MVP 운영 규칙이며 전문가가 승인한 안전 기준이 아니다.",
    "severity_levels": {"1": "경미", "2": "치료 필요", "3": "사망·영구장해 가능"},
    "control_bands": {"1": "필요한 조치 모두 선택", "2": "핵심 조치 선택·보완 미흡", "3": "핵심 조치 미선택"},
    "matrix": {"1": {"1": "하", "2": "중", "3": "중"}, "2": {"1": "중", "2": "중", "3": "상"}, "3": {"1": "중", "2": "상", "3": "상"}},
    "signal": {"상": "R", "중": "Y", "하": "G", "null": "N"}
}
save(OUT / "risk_policy.CATALOG-MVP-1.0.reference.json", policy)

# 예시 (값은 예시이며 실제 카탈로그 조치 구성과 다를 수 있다)
save(EX / "user_selection.v2_1.example.json", {
    "assessment_id": "A-EXAMPLE-1", "policy_version": "CATALOG-MVP-1.0",
    "candidates_request_id": "7a2d0c11-5b6e-4f0a-8c21-000000000101",
    "selections": [
        {"selection_id": "sel-1", "equipment_id": None, "origin": "ai_candidate", "candidate_id": "cand-floor-1",
         "hazard": "[예시] 젖거나 기름진 통로 바닥에서 미끄러져 넘어짐", "hazard_edited": False,
         "accident_type": {"code": "slip", "label": "미끄러짐·넘어짐"}, "source_refs": [],
         "catalog_scenario_id": "ENV", "current_control_ids": ["ENV-C1", "ENV-C2"], "no_current_controls": False,
         "plan_control_ids": ["ENV-C3", "ENV-C4"], "custom_current_measures": [], "selected_measures": [],
         "owner_name": None, "due_date": None, "decided_by": "user", "decided_at": "2026-11-17T10:00:00+09:00"},
        {"selection_id": "sel-2", "equipment_id": None, "origin": "user_custom", "candidate_id": None,
         "hazard": "[예시] 염지기 회전부 청소 중 손 끼임", "hazard_edited": False,
         "accident_type": {"code": "cut", "label": "베임·절단·끼임"}, "source_refs": [],
         "catalog_scenario_id": None, "current_control_ids": [], "no_current_controls": True,
         "plan_control_ids": [], "custom_current_measures": [], "selected_measures": [],
         "owner_name": None, "due_date": None, "decided_by": "user", "decided_at": "2026-11-17T10:01:00+09:00"}]})
save(EX / "risk_result.v2_1.example.json", {
    "assessment_id": "A-EXAMPLE-1", "computed_by": "backend_risk_policy", "policy_version": "CATALOG-MVP-1.0",
    "computed_at": "2026-11-17T10:02:00+09:00",
    "results": [
        {"selection_id": "sel-1", "phase": "current", "status": "calculated", "catalog_scenario_id": "ENV", "severity": 2,
         "control_band": 3, "grade": "상", "signal": "R", "reason": "피해 S2 · 조치 C3 → 상. 선택한 현재 조치를 기준으로 계산했습니다."},
        {"selection_id": "sel-1", "phase": "expected", "status": "calculated", "catalog_scenario_id": "ENV", "severity": 2,
         "control_band": 2, "grade": "중", "signal": "Y", "reason": "[예시] 계획 조치 이행을 가정한 값입니다."},
        {"selection_id": "sel-2", "phase": "current", "status": "not_in_catalog", "catalog_scenario_id": None, "severity": None,
         "control_band": None, "grade": None, "signal": "N", "reason": "카탈로그에 없는 직접 추가 위험입니다. 판단이 필요합니다."}]})
print("written", sorted(p.name for p in OUT.iterdir()), sorted(p.name for p in EX.iterdir()))
