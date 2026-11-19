"""기존 SAM 탐지와 사진 캐시를 공통 입력의 사진 근거로 연결한다."""
import hashlib
import json
import os
from pathlib import Path

from schemas.catalog_ai import SamResponse
from services import catalog_ai
from services.auth import AuthError

from contracts.assessment_authoring.v1.validate import read

EQUIPMENT_IDS = frozenset(read("reference/equipment_ids.json"))
ROOT = Path(__file__).resolve().parents[2]
CLASS_MAP_PATH = ROOT / "ai/experiments/261116_기기탐지_YOLO전환_DR/261116_사전학습클래스_대응표_v1_DR.json"
MASTER_PATH = ROOT / read("reference/SOURCE.json")["equipment_source_path"]


def _load_equipment_map():
    master = json.loads(MASTER_PATH.read_text(encoding="utf-8-sig"))["equipment"]
    rows = json.loads(CLASS_MAP_PATH.read_text(encoding="utf-8-sig"))["rows"]
    names = {row["equipment_id"]: row["standard_name"] for row in master if row["equipment_id"] in EQUIPMENT_IDS}
    inventory = {}
    for row in master:
        if row["equipment_id"] in names:
            for label in [row["standard_name"], *row["synonyms"]]:
                inventory.setdefault(label.strip().casefold(), set()).add(row["equipment_id"])
    classes = {}
    for row in rows:
        if row["equipment_id"] in names:
            prompts = (row["open_vocab_prompt_draft"] or "").split(";")
            if row["coco_match"] == "direct":
                prompts.append(row["coco_class"])
            for label in prompts:
                if label.strip():
                    classes.setdefault(label.strip().casefold(), set()).add(row["equipment_id"])
    # 서비스의 고정 탐지 검사에서 사용한 클래스 표기.
    classes.setdefault("deep fryer", set()).add("EQ_FRYER")
    classes.setdefault("shelf", set()).add("EQ_SHELF")
    return (
        names,
        {label: next(iter(ids)) for label, ids in inventory.items() if len(ids) == 1},
        {label: next(iter(ids)) for label, ids in classes.items() if len(ids) == 1},
    )


EQUIPMENT_NAMES, INVENTORY_NAMES, DETECTOR_CLASSES = _load_equipment_map()


def _detection_failed():
    return AuthError(503, "DETECTOR_FAILED", "사진 기기 탐지를 완료하지 못했어요. 입력을 유지하고 다시 시도해 주세요.")


def resolve_detection(photos, request):
    """make_input이 쓰는 사진 탐지·임계값·서버 캐시 경로를 재사용한다."""
    gateway = catalog_ai.gateway_url()
    endpoint = gateway + "/v1/detect" if gateway else os.getenv("SAFET_DETECTOR_URL", "").strip()
    detector_source = hashlib.sha256(endpoint.encode()).hexdigest()
    previous = request.get("_photo_cache")
    if not isinstance(previous, dict) or previous.get("detector_source") != detector_source:
        previous = None
    context = {
        "photos": photos,
        "_photo_cache": previous,
        "_refresh_photos": request.get("_refresh_photos"),
    }
    try:
        catalog_ai.make_input(context)
        cache = context["_photo_cache"]
        return cache["detection"], {**cache, "detector_source": detector_source}
    except (AttributeError, KeyError, TypeError, ValueError):
        raise _detection_failed() from None


def _validated_hits(result, expected_photo_ids):
    if not isinstance(result, dict):
        raise ValueError
    if "model_output" in result:
        output = SamResponse.model_validate(result).model_output
        result = {
            "model": output.detector.model_name,
            "metadata": output.model_dump(exclude={"detections"}),
            "detections": [hit.model_dump() for hit in output.detections],
        }
    model = result["model"]
    if not isinstance(model, str) or not model.strip() or result.get("status", "ok") != "ok" or result.get("error_code"):
        raise ValueError

    if "metadata" in result:
        metadata = result["metadata"]
        if metadata["status"] != "ok" or metadata.get("error_code"):
            raise ValueError
        photos = metadata["photos"]
        if len(photos) != len(expected_photo_ids) or {item["photo_id"] for item in photos} != expected_photo_ids:
            raise ValueError
        if any(item["status"] != "analyzed" or item.get("error_code") for item in photos):
            raise ValueError

    hits = result["detections"]
    if not isinstance(hits, list) or len(hits) > 1000:
        raise ValueError
    detection_ids = set()
    for hit in hits:
        photo_id, confidence = hit["photo_id"], hit["confidence"]
        label = hit.get("detector_class", hit.get("equipment"))
        if (photo_id not in expected_photo_ids or not isinstance(label, str)
                or not label.strip() or len(label) > 2000
                or type(confidence) not in (int, float) or not 0 <= confidence <= 1):
            raise ValueError
        detection_id = hit.get("detection_id")
        if detection_id is not None:
            if not isinstance(detection_id, str) or not detection_id.strip() or detection_id in detection_ids:
                raise ValueError
            detection_ids.add(detection_id)
        if "bbox" in hit:
            x1, y1, x2, y2 = hit["bbox"]
            if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
                raise ValueError
        equipment_id = hit.get("equipment_id")
        if equipment_id is not None and not isinstance(equipment_id, str):
            raise ValueError
        yield photo_id, label.strip(), confidence, equipment_id


def adapt_detections(photos, result):
    """사진 media, 사진별 표준 기기 ID, 미매핑 목록을 반환한다."""
    by_photo = {f"PHOTO{i}": [] for i in range(1, len(photos) + 1)}
    unmapped = {}
    try:
        for photo_id, label, confidence, equipment_id in _validated_hits(result, set(by_photo)):
            if equipment_id is None:
                equipment_id = DETECTOR_CLASSES.get(label.casefold())
            if equipment_id not in EQUIPMENT_IDS:
                unmapped.setdefault(photo_id, {})[(label, equipment_id)] = None
                continue
            by_photo[photo_id].append({
                "equipment": EQUIPMENT_NAMES[equipment_id],
                "confidence": confidence,
                "equipment_id": equipment_id,
            })
    except (KeyError, TypeError, ValueError, AttributeError):
        raise _detection_failed() from None

    media, equipment_by_photo, audit = [], {}, []
    for (photo_id, hits), photo in zip(by_photo.items(), photos):
        rows = catalog_ai.summarize_detections(hits)
        unknown = unmapped.get(photo_id, {})
        if rows:
            summary = "탐지 기기 후보: " + ", ".join(rows) + "."
        elif unknown:
            summary = "표준 ID에 연결된 기기 후보 없음."
        else:
            summary = "탐지된 기기 없음."
        if unknown:
            summary += f" 미등록 탐지 클래스 {len({label for label, _ in unknown})}종."
        if rows or unknown:
            summary += " 작동 상태와 안전조치 실행 여부는 확인되지 않았습니다."
        if photo["place"]:
            summary = f"입력 위치: {photo['place']}. {summary}"
        media.append({"id": photo_id, "kind": "equipment_detection", "text": summary})
        equipment_by_photo[photo_id] = list(dict.fromkeys(hit["equipment_id"] for hit in hits))
        audit.extend(
            {"photo_id": photo_id, "detector_class": label, "equipment_id": reported_id}
            for label, reported_id in unknown
        )
    return media, equipment_by_photo, audit
