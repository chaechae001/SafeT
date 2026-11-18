"""기기 탐지 응답(SAM 3 등, safe-t/equipment_detection.response.v2-draft)을 그래프의 기기 후보(ai_found)로 바꾼다.

규칙 출처: `261116_기기탐지_YOLO전환_DR/261116_기기인식_출력형식_제외규칙_v2_DR.md` 3절(R1~R8).
- R1  master_version·class_map_version 불일치 → 전체 미사용(master_mismatch / class_map_mismatch)
- R2  equipment_id null·마스터에 없음 → 제외(unmapped)
- R2a 대응표 detection_target이 no·hold → 제외(not_detection_target)
- R2b class_map_match=partial → 기본 제외(partial_mapping)
- R3  confidence < T → 제외(below_threshold). **T는 문서상 미정(Q1)**. 이 모듈은 T를 정하지 않고 호출자가 넘긴 값만 쓴다.
      T를 넘기지 않으면 R3을 적용하지 않고 그 사실을 기록한다.
- R4  같은 equipment_id는 하나로 합친다. detection_refs는 남은 검출 모두(photo_id#detection_id), 대표 신뢰도는 최댓값.
- R5  사업장 등록 기기(source=db)와 같은 equipment_id → 제외(registered_db)
- R6·R7(직접 입력 이름 일치) → 미구현. 입력이 오면 그대로 두고 미구현으로 기록한다.
- R8  남은 항목만 ai_found[](selected 기본 true)
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

DET_DIR_NAME = "261116_기기탐지_YOLO전환_DR"


def load_class_map(path: Path) -> dict:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"version": m["version"], "master_version": m["master_version"],
            "target": {r["equipment_id"]: r["detection_target"] for r in m["rows"]}}


def to_ai_found(resp: dict, class_map: dict, known_ids: set[str], expected: dict, threshold=None,
                use_partial: bool = False, registered: list[dict] | None = None, photo_ids: set[str] | None = None) -> dict:
    """resp: 탐지 응답(model_output). threshold: None | float | {"default": float|None, "per_equipment": {...}}.
    photo_ids: 이 평가(사업장)에 속한 사진만 쓴다(None이면 전부)."""
    ex = Counter()
    notes = []
    det = resp["detector"]
    if resp.get("master_version") != expected["master_version"]:
        return {"usable": False, "reason": "master_mismatch", "ai_found": [], "excluded": {}, "notes": notes}
    if det.get("class_map_version") != expected["class_map_version"]:
        return {"usable": False, "reason": "class_map_mismatch", "ai_found": [], "excluded": {}, "notes": notes}
    if isinstance(threshold, (int, float)) or threshold is None:
        threshold = {"default": threshold, "per_equipment": {}}
    if threshold["default"] is None and not threshold["per_equipment"]:
        notes.append("R3 미적용: 임계값 T 미정(문서 Q1)")
    reg_db = {r["equipment_id"] for r in (registered or []) if r.get("source") == "db"}
    if any(r.get("source") == "manual" for r in (registered or [])):
        notes.append("R6·R7 미구현: 직접 입력 이름 일치 제외는 적용하지 않음")
    photos = [p for p in resp["photos"] if photo_ids is None or p["photo_id"] in photo_ids]
    analyzed = {p["photo_id"] for p in photos if p["status"] == "analyzed"}
    merged: dict[str, dict] = {}
    for d in resp["detections"]:
        if d["photo_id"] not in analyzed:
            continue
        eid = d.get("equipment_id")
        if not eid or eid not in known_ids:
            ex["unmapped"] += 1
            continue
        if class_map["target"].get(eid) in ("no", "hold"):
            ex["not_detection_target"] += 1
            continue
        if d.get("class_map_match") == "partial" and not use_partial:
            ex["partial_mapping"] += 1
            continue
        t = threshold["per_equipment"].get(eid, threshold["default"])
        if t is not None and d["confidence"] < t:
            ex["below_threshold"] += 1
            continue
        if eid in reg_db:
            ex["registered_db"] += 1
            continue
        m = merged.setdefault(eid, {"equipment_id": eid, "confidence": 0.0, "detection_refs": [], "selected": True})
        m["confidence"] = max(m["confidence"], d["confidence"])
        m["detection_refs"].append(f'{d["photo_id"]}#{d["detection_id"]}')
    found = sorted(merged.values(), key=lambda x: -x["confidence"])
    return {"usable": True, "reason": None, "photos_used": len(analyzed), "ai_found": found, "excluded": dict(ex),
            "threshold": threshold, "notes": notes,
            "detector": {k: det.get(k) for k in ("model_name", "model_version", "class_map_version", "score_threshold_applied", "prompt_set_version")}}
