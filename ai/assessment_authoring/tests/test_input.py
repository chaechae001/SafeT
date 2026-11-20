import copy
from importlib.util import find_spec
import json
from pathlib import Path
import unittest
from unittest.mock import patch

if find_spec("schemas") is None:
    raise unittest.SkipTest("입력 어댑터 검사에는 PYTHONPATH=backend와 백엔드 의존성이 필요합니다.")

from schemas.assessment import CreateAssessment
from services.auth import AuthError

from ai.assessment_authoring.input_adapter import build_context
from ai.assessment_authoring.detection_adapter import adapt_detections, DETECTOR_CLASSES, EQUIPMENT_IDS, EQUIPMENT_NAMES
from contracts.assessment_authoring.v1.validate import check, read

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/input"
PHOTO = {
    "name": "synthetic.png",
    "data": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII=",
}
TEXT = "  주방에서 180도 기름을 사용합니다.\n장갑을 착용하지 않습니다.  "
VOICE = "  오늘은 튀김기를 사용하지 않습니다.\n횟수는 0회입니다.  "
MACHINES = [
    {"machine_code": "001", "machine_nm": "튀김기"},
    {"machine_code": None, "machine_nm": "포장 실링기", "custom": True},
    {"machine_code": "EQ_FRYER", "machine_nm": "튀김기"},
]


def fixture(path):
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


def cases():
    return {
        "text": ({"text": TEXT}, None),
        "voice": ({"voice_text": VOICE}, None),
        "photo": ({"photos": [dict(PHOTO, place="주방"), dict(PHOTO, place="창고")]}, fixture("sam_response.json")),
        "mixed": (
            {"text": TEXT, "voice_text": VOICE, "machines": MACHINES, "photos": [PHOTO]},
            {"model": "sam3-mock", "detections": [{"photo_id": "PHOTO1", "equipment": "deep fryer", "confidence": 0.91}]},
        ),
        "inventory": ({"machines": MACHINES}, None),
        "zero_detection": ({"photos": [PHOTO]}, {"model": "sam3-mock", "detections": []}),
    }


class InputTests(unittest.TestCase):
    def test_examples_match_schema_and_keep_inputs(self):
        schema = read("schemas/input.schema.json")
        for name, (request, response) in cases().items():
            with self.subTest(name=name):
                original = copy.deepcopy((request, response))
                with patch("services.catalog_ai.detect_equipment") as detect:
                    result = build_context(request, response)
                detect.assert_not_called()
                check(result, schema)
                self.assertEqual(result, fixture(f"{name}/input.json"))
                self.assertEqual((request, response), original)
                media_ids = [row["id"] for row in result["media"]]
                self.assertEqual(len(set(media_ids)), len(media_ids))
                self.assertEqual(len(set(result["equipment_ids"])), len(result["equipment_ids"]))

    def test_original_text_preserves_negation_numbers_and_whitespace(self):
        media = build_context({"text": TEXT, "voice_text": VOICE})["media"]
        self.assertEqual(media[0], {"id": "TEXT", "kind": "text", "text": TEXT})
        self.assertEqual(media[1], {"id": "VOICE", "kind": "voice_transcript", "text": VOICE})

    def test_accepts_existing_create_assessment_instance(self):
        request = CreateAssessment(
            request_key="00000000-0000-0000-0000-000000000001",
            work_no=1, eval_dt="2026-11-19", eval_writer="평가자", text=TEXT,
        )
        self.assertEqual(build_context(request)["media"][0]["text"], request.text)

    def test_inventory_preserves_custom_names_and_does_not_infer_from_text(self):
        result = build_context({"machines": MACHINES, "text": "가스레인지를 사용합니다."})
        self.assertEqual(result["equipment_ids"], ["EQ_FRYER"])
        self.assertEqual(result["media"][1]["text"], "등록 기기: 튀김기, 포장 실링기.")
        self.assertEqual(build_context({"machines": [{"machine_nm": "업소용 냉장고"}]})["equipment_ids"], ["EQ_REFRIGERATOR"])

    def test_bad_input_uses_existing_error_path(self):
        requests = [
            (None, "AI_INPUT_INVALID"),
            ({"text": " \n", "voice_text": ""}, "AI_INPUT_EMPTY"),
            ({"catalog_ids": ["FRY"]}, "AI_INPUT_EMPTY"),
            ({"text": 180}, "AI_INPUT_INVALID"),
            ({"voice_text": "x" * 10001}, "AI_INPUT_INVALID"),
            ({"photos": [PHOTO] * 7}, "AI_IMAGE_INVALID"),
            ({"photos": "사진"}, "AI_IMAGE_INVALID"),
            ({"photos": [dict(PHOTO, data="data:image/png;base64,YQ==")]}, "AI_IMAGE_INVALID"),
            ({"photos": [dict(PHOTO, data="x" * 2800001)]}, "AI_IMAGE_INVALID"),
            ({"photos": [dict(PHOTO, name="x" * 101)]}, "AI_IMAGE_INVALID"),
            ({"machines": [None]}, "INVALID_MACHINE"),
            ({"machines": [{"machine_nm": "튀김기", "machine_code": "EQ_UNKNOWN"}]}, "INVALID_MACHINE"),
        ]
        for request, code in requests:
            with self.subTest(code=code), patch("services.catalog_ai.detect_equipment") as detect:
                with self.assertRaises(AuthError) as error:
                    build_context(request)
                self.assertEqual((error.exception.status, error.exception.code), (422, code))
                detect.assert_not_called()

    def test_requires_photo_for_injected_detection(self):
        with self.assertRaises(AuthError) as error:
            build_context({"text": TEXT}, {"model": "sam3-mock", "detections": []})
        self.assertEqual(error.exception.code, "AI_IMAGE_INVALID")

    def test_error_examples_are_public_error_bodies(self):
        samples = {
            "empty_input": ({}, None),
            "invalid_photo": ({"photos": [dict(PHOTO, data="invalid")]}, None),
            "detector_failure": ({"photos": [PHOTO]}, {"model": "sam3-mock", "status": "error", "detections": []}),
        }
        with patch("services.catalog_ai.detect_equipment") as detect:
            for name, params in samples.items():
                with self.subTest(name=name), self.assertRaises(AuthError) as error:
                    build_context(*params)
                exc = error.exception
                self.assertEqual(
                    {"status": exc.status, "body": {"detail": {"code": exc.code, "message": exc.message}}},
                    fixture("errors.json")[name],
                )
        detect.assert_not_called()

    def test_mapping_and_unmapped_examples(self):
        self.assertEqual(
            fixture("equipment_mapping.json"),
            {key: {"name": EQUIPMENT_NAMES[key],
                   "detector_classes": sorted(label for label, value in DETECTOR_CLASSES.items() if value == key)}
             for key in sorted(EQUIPMENT_IDS)},
        )
        request, response = cases()["photo"]
        self.assertEqual(adapt_detections(request["photos"], response)[2], fixture("unmapped.json"))
