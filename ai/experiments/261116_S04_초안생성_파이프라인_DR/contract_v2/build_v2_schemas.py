"""v1 계약(../../261115_AI출력계약_신호기준_DR/schemas, 읽기만)에서 v2 초안 스키마를 만든다.
추가: Detection(탐지 결과 자리), Observation(VLM 상태 관찰), RiskItemAI.evidence_refs 필수 + observation_refs·detection_refs,
요청 detections[], 응답 observations[]·analysis_stages[]. v1 원본은 고치지 않는다.
python contract_v2/build_v2_schemas.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent / "261115_AI출력계약_신호기준_DR" / "schemas"
tax = json.loads((HERE / "observation_taxonomy.json").read_text(encoding="utf-8"))
codes = list(tax["codes"])


def load(n):
    return json.loads((SRC / n).read_text(encoding="utf-8"))


def save(n, obj):
    (HERE / n).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


common = load("common.schema.json")
common["$id"] = "https://safe-t.local/schemas/v2/common.schema.json"
common["title"] = "Safe-T AI 출력 계약 공통 정의 v2 초안(사진 분석 단계 추가)"
common["description"] += (" v2(2026-11-16, 제안): 사진 상태 관찰(Observation)·기기 탐지(Detection) 정의와 "
                          "RiskItemAI의 근거 참조(observation_refs·detection_refs)를 추가했다. v1 원본은 고치지 않는다.")
d = common["$defs"]
d["HazardStateCode"] = {"description": "관찰 위험 상태 분류. contract_v2/observation_taxonomy.json(기기마스터 hazard_codes와 같은 코드 + none)",
                        "type": "string", "enum": codes}
d["BBoxNorm"] = {"description": "정규화 좌표 [x0, y0, x1, y1] (0~1, EXIF 회전 적용 화면 기준)", "type": "array",
                 "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 4, "maxItems": 4}
d["Detection"] = {
    "description": "기기 탐지 결과(탐지 모델 담당). VLM은 기기를 판정하지 않는다. 탐지 모델 전에는 평가셋 라벨을 source=oracle_label로 넣는다.",
    "type": "object", "additionalProperties": False,
    "required": ["detection_id", "photo_id", "equipment_id", "bbox_norm", "confidence", "source"],
    "properties": {
        "detection_id": {"type": "string", "minLength": 1},
        "photo_id": {"type": "string", "minLength": 1},
        "equipment_id": {"type": "string", "pattern": "^EQ_[A-Z0-9_]+$", "description": "기기마스터 equipment_id"},
        "bbox_norm": {"$ref": "#/$defs/BBoxNorm"},
        "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "source": {"type": "string", "enum": ["model", "oracle_label"],
                   "description": "oracle_label = 평가셋 라벨을 탐지 결과 대신 넣은 것(탐지 성능 평가에 쓰면 안 됨)"},
        "detector_version": {"type": ["string", "null"]},
    },
}
d["Observation"] = {
    "description": "VLM 사진 상태 관찰 1건. 보이는 상태(물기·기름·적재·불꽃·전선 등)만 쓰고 기기 이름을 판정하지 않는다.",
    "type": "object", "additionalProperties": False,
    "required": ["observation_id", "photo_id", "location", "text", "hazard_state", "confidence", "confidence_source", "model_version"],
    "properties": {
        "observation_id": {"type": "string", "pattern": "^obs-"},
        "photo_id": {"type": "string", "minLength": 1},
        "location": {"type": ["string", "null"], "description": "사진별 장소 입력(S02). 없으면 null"},
        "text": {"type": "string", "minLength": 1, "maxLength": 200},
        "hazard_state": {"$ref": "#/$defs/HazardStateCode"},
        "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "confidence_source": {"type": "string", "enum": ["model_self_report", "calibrated", "none"],
                              "description": "model_self_report = 모델이 스스로 적은 값(보정 전, 신뢰 근거 아님)"},
        "model_version": {"type": "string", "minLength": 1},
        "equipment_term_flag": {"type": "boolean", "description": "관찰 문장에 기기 이름이 들어가 있으면 true(후처리 검사 결과)"},
    },
}
ri = d["RiskItemAI"]
ri["properties"]["observation_refs"] = {
    "type": "array", "items": {"type": "string", "pattern": "^obs-"},
    "description": "근거 관찰 ID. 사진 입력이 있는데 비어 있으면 그 항목은 signal=off(insufficient_input)로 둔다(파이프라인 규칙)."}
ri["properties"]["detection_refs"] = {"type": "array", "items": {"type": "string"}, "description": "근거 탐지 ID"}
ri["required"] = ri["required"] + ["evidence_refs"]
ri["description"] += " v2: evidence_refs 필수, observation_refs·detection_refs 추가."
save("common.schema.json", common)

req = load("s04_draft.request.schema.json")
req["$id"] = "https://safe-t.local/schemas/v2/s04_draft.request.schema.json"
req["title"] = "S04 초안 생성 요청 v2 초안 (사진 분석 단계 포함)"
req["properties"]["detections"] = {"type": "array", "items": {"$ref": "common.schema.json#/$defs/Detection"},
                                   "description": "기기 탐지 결과(사진별). 탐지 모델 준비 전에는 source=oracle_label."}
save("s04_draft.request.schema.json", req)

resp = load("s04_draft.response.schema.json")
resp["$id"] = "https://safe-t.local/schemas/v2/s04_draft.response.schema.json"
resp["title"] = "S04 초안 생성 응답 v2 초안 (사진 상태 관찰 포함)"
resp["else"]["properties"]["observations"] = {"type": "array", "items": {"$ref": "common.schema.json#/$defs/Observation"},
                                              "description": "사진 상태 관찰(VLM). 사진이 없으면 빈 배열."}
resp["else"]["properties"]["analysis_stages"] = {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["stage", "model_version"],
                               "properties": {"stage": {"type": "string", "enum": ["detect_equipment", "observe_state", "generate_items", "select_measures"]},
                                              "model_version": {"type": "string"}, "source": {"type": ["string", "null"]}}}}
resp["else"]["required"] = resp["else"]["required"] + ["observations"]
save("s04_draft.response.schema.json", resp)

ps = json.loads((SRC / "progress_stages.json").read_text(encoding="utf-8"))
ps["s04_draft"]["stages"][0]["work"] = "사진 기기 탐지(탐지 모델)·사진 상태 관찰(VLM)·글·음성 전사문·기기 목록 정리, 사진 장소 연결"
ps["s04_draft"]["note_v2"] = "v2 제안: 사진 분석(탐지·관찰)은 20% 단계(analyze_input)에 포함한다. 15쪽 진행률 값은 바꾸지 않는다. 별도 단계로 나눌지는 팀 결정."
save("progress_stages.json", ps)
print("ok", codes)
