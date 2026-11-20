"""기존 평가 요청을 공통 입력 계약에 맞는 객체로 정리한다."""
from pydantic import ValidationError
from schemas.assessment import CreateAssessment, Photo
from services.auth import AuthError

from contracts.assessment_authoring.v1.validate import check, read

from .detection_adapter import EQUIPMENT_IDS, INVENTORY_NAMES, adapt_detections, resolve_detection

INPUT_SCHEMA = read("schemas/input.schema.json")


def _inventory(machines):
    if not isinstance(machines, list):
        raise AuthError(422, "INVALID_MACHINE", "사업장 기기 목록을 확인해 주세요.")
    names, ids = {}, {}
    for machine in machines:
        if not isinstance(machine, dict):
            raise AuthError(422, "INVALID_MACHINE", "사업장 기기 목록을 확인해 주세요.")
        name = machine.get("machine_nm")
        code = machine.get("machine_code")
        if not isinstance(name, str) or not name.strip() or (code is not None and not isinstance(code, str)):
            raise AuthError(422, "INVALID_MACHINE", "사업장 기기 이름과 코드를 확인해 주세요.")
        if code and code.startswith("EQ_") and code not in EQUIPMENT_IDS:
            raise AuthError(422, "INVALID_MACHINE", "등록되지 않은 표준 기기 ID가 있어요.")
        names[name] = None
        equipment_id = code if code in EQUIPMENT_IDS else INVENTORY_NAMES.get(name.strip().casefold())
        if equipment_id:
            ids[equipment_id] = None
    return list(names), list(ids)


def build_context(raw_request, detection_result=None):
    """InputBundle을 반환한다. 사진 캐시는 서버가 관리하는 요청 사전에 저장한다."""
    request = raw_request.model_dump() if isinstance(raw_request, CreateAssessment) else raw_request
    if not isinstance(request, dict):
        raise AuthError(422, "AI_INPUT_INVALID", "평가표 입력 형식을 확인해 주세요.")

    media = []
    for key, media_id, kind in (("text", "TEXT", "text"), ("voice_text", "VOICE", "voice_transcript")):
        value = request.get(key, "")
        if not isinstance(value, str) or len(value) > 10000:
            raise AuthError(422, "AI_INPUT_INVALID", "글·전사문은 각각 10,000자 이하여야 해요.")
        if value.strip():
            media.append({"id": media_id, "kind": kind, "text": value})

    names, equipment_ids = _inventory(request.get("machines", []))
    if names:
        media.append({"id": "MACHINES", "kind": "equipment_inventory", "text": "등록 기기: " + ", ".join(names) + "."})

    raw_photos = request.get("photos", [])
    if not isinstance(raw_photos, list) or len(raw_photos) > 6:
        raise AuthError(422, "AI_IMAGE_INVALID", "사진은 최대 6장까지 전달할 수 있어요.")
    try:
        photos = [Photo.model_validate(photo).model_dump() for photo in raw_photos]
    except ValidationError:
        raise AuthError(422, "AI_IMAGE_INVALID", "사진 이름·위치와 파일 형식(PNG/JPEG/WebP)·용량(2MB 이하)을 확인해 주세요.") from None

    cache = None
    if photos:
        if detection_result is None:
            detection_result, cache = resolve_detection(photos, request)
        photo_media, equipment_by_photo, unmapped = adapt_detections(photos, detection_result)
        media.extend(photo_media)
        for detected_ids in equipment_by_photo.values():
            equipment_ids.extend(detected_ids)
    elif detection_result is not None:
        raise AuthError(422, "AI_IMAGE_INVALID", "탐지 결과와 연결할 사진이 필요해요.")

    if not media:
        raise AuthError(422, "AI_INPUT_EMPTY", "사진·전사문·글 또는 사업장 기기가 필요해요.")

    bundle = {
        "contract_version": INPUT_SCHEMA["properties"]["contract_version"]["const"],
        "catalog_version": INPUT_SCHEMA["properties"]["catalog_version"]["const"],
        "media": media,
        "equipment_ids": list(dict.fromkeys(equipment_ids)),
    }
    check(bundle, INPUT_SCHEMA)
    if cache is not None:
        request["_photo_cache"] = {**cache, "equipment_ids_by_photo": equipment_by_photo, "unmapped": unmapped}
    return bundle
