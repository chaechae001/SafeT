import base64
import copy
import json
import os
import unittest
from unittest.mock import patch

from ai.assessment_authoring.tests.test_input import PHOTO, TEXT, fixture

import httpx
from services import catalog_ai
from services.auth import AuthError

from ai.assessment_authoring.input_adapter import build_context


class DetectionTests(unittest.TestCase):
    def test_keeps_highest_score_per_photo_and_deduplicates_search_ids(self):
        result = build_context({"photos": [PHOTO, PHOTO]}, fixture("sam_response.json"))
        first, second = [row["text"] for row in result["media"]]
        self.assertIn("튀김기 0.91", first)
        self.assertNotIn("0.62", first)
        self.assertNotIn("적재 선반", first)
        self.assertIn("미등록 탐지 클래스 1종", first)
        self.assertIn("튀김기 0.72", second)
        self.assertNotIn("0.75", second)
        self.assertIn("적재 선반 0.77", second)
        self.assertEqual(result["equipment_ids"], ["EQ_FRYER", "EQ_SHELF"])

    def test_unmapped_is_separate_from_zero(self):
        response = {"model": "sam3-mock", "detections": [
            {"photo_id": "PHOTO1", "equipment": "tongs", "confidence": 0.85},
        ]}
        result = build_context({"photos": [PHOTO]}, response)
        self.assertEqual(result["equipment_ids"], [])
        self.assertIn("표준 ID에 연결된 기기 후보 없음.", result["media"][0]["text"])

    def test_zero_with_text_keeps_text_searchable(self):
        result = build_context({"photos": [PHOTO], "text": TEXT}, {"model": "sam3-mock", "detections": []})
        self.assertEqual(result["media"][0]["text"], TEXT)
        self.assertEqual(result["media"][1]["text"], "탐지된 기기 없음.")

    def test_missing_failed_or_mismatched_photos_are_not_zero(self):
        for field in ("file_error", "partial", "missing_photo", "duplicate_photo", "unknown_photo",
                      "duplicate_detection_id", "bad_box", "bad_score", "missing_detections"):
            with self.subTest(field=field):
                response = fixture("sam_response.json")
                output = response["model_output"]
                if field == "file_error":
                    output["photos"][0].update(status="error", error_code="IMAGE_DECODE_FAILED")
                elif field == "partial":
                    output["status"] = "partial"
                elif field == "missing_photo":
                    output["photos"].pop()
                elif field == "duplicate_photo":
                    output["photos"][1]["photo_id"] = "PHOTO1"
                elif field == "unknown_photo":
                    output["detections"][0]["photo_id"] = "PHOTO3"
                elif field == "duplicate_detection_id":
                    output["detections"][1]["detection_id"] = "d1"
                elif field == "bad_box":
                    output["detections"][0]["bbox"] = [0.5, 0, 0.1, 1]
                elif field == "bad_score":
                    output["detections"][0]["confidence"] = 1.5
                else:
                    del output["detections"]
                with self.assertRaises(AuthError) as error:
                    build_context({"photos": [PHOTO, PHOTO], "text": TEXT}, response)
                self.assertEqual((error.exception.status, error.exception.code), (503, "DETECTOR_FAILED"))

    def test_cache_reuses_existing_entry_and_refreshes_on_changes(self):
        response = {"model": "sam3-mock", "detections": []}
        request = {"photos": [dict(PHOTO)]}
        env = {"SAFET_AI_GATEWAY_URL": "", "SAFET_DETECTOR_URL": "https://mock.invalid/detect",
               "SAFET_DETECTOR_THRESHOLD": ""}
        with patch.dict(os.environ, env), patch.object(catalog_ai, "detect_equipment", return_value=response) as detect:
            first = build_context(request)
            cached = copy.deepcopy(request)
            self.assertEqual(build_context(cached), first)
            self.assertEqual(detect.call_count, 1)
            self.assertEqual(cached["_photo_cache"]["detection"], response)
            with patch.dict(os.environ, {"SAFET_DETECTOR_THRESHOLD": "0.5"}):
                build_context(cached)
            self.assertEqual(detect.call_count, 2)
            with patch.dict(os.environ, {"SAFET_DETECTOR_URL": "https://other.invalid/detect"}):
                build_context(request)
            self.assertEqual(detect.call_count, 3)
            header, encoded = PHOTO["data"].split(",", 1)
            revised = base64.b64encode(base64.b64decode(encoded) + b"x").decode()
            request["photos"][0]["data"] = f"{header},{revised}"
            build_context(request)
            self.assertEqual(detect.call_count, 4)
            request["photos"][0]["place"] = "주방"
            build_context(request)
            self.assertEqual(detect.call_count, 5)
            request["_refresh_photos"] = True
            build_context(request)
            self.assertEqual(detect.call_count, 6)

    def test_timeout_then_retry_via_existing_http_client(self):
        request = {"photos": [PHOTO, PHOTO], "text": TEXT}
        original = copy.deepcopy(request)
        sent = []

        def respond(http_request):
            payload = json.loads(http_request.content)
            sent.append(payload)
            if len(sent) == 1:
                raise httpx.ReadTimeout("synthetic timeout", request=http_request)
            output = fixture("sam_response.json")
            output["model_output"]["request_id"] = payload["request_id"]
            return httpx.Response(200, json=output)

        client = httpx.Client
        env = {"SAFET_AI_GATEWAY_URL": "", "SAFET_DETECTOR_URL": "https://mock.invalid/detect",
               "SAFET_DETECTOR_THRESHOLD": "", "SAFET_DETECTOR_API_KEY": ""}
        with patch.dict(os.environ, env), patch.object(
            catalog_ai.httpx, "Client", side_effect=lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs)
        ):
            with self.assertRaises(AuthError) as error:
                build_context(request)
            self.assertEqual(error.exception.code, "DETECTOR_FAILED")
            self.assertEqual(request, original)
            self.assertEqual(build_context(request)["equipment_ids"], ["EQ_FRYER", "EQ_SHELF"])
            self.assertEqual(build_context(request)["equipment_ids"], ["EQ_FRYER", "EQ_SHELF"])
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[1]["score_threshold"], 0.35)
        self.assertEqual([row["photo_id"] for row in sent[1]["photos"]], ["PHOTO1", "PHOTO2"])
        self.assertEqual(request["_photo_cache"]["detection"]["metadata"]["detector"]["model_version"], "fixture-1")
        self.assertEqual(request["_photo_cache"]["detection"]["detections"][1]["confidence"], 0.91)
        self.assertEqual(request["_photo_cache"]["unmapped"], fixture("unmapped.json"))
        self.assertEqual(
            request["_photo_cache"]["equipment_ids_by_photo"],
            {"PHOTO1": ["EQ_FRYER"], "PHOTO2": ["EQ_SHELF", "EQ_FRYER"]},
        )

    def test_invalid_refresh_leaves_previous_cache_untouched(self):
        request = {"photos": [PHOTO], "text": TEXT}
        with patch.object(catalog_ai, "detect_equipment", return_value={"model": "sam3-mock", "detections": []}):
            build_context(request)
        request["_refresh_photos"] = True
        original = copy.deepcopy(request)
        with patch.object(catalog_ai, "detect_equipment", return_value={"model": "sam3-mock", "detections": [
            {"photo_id": "PHOTO2", "equipment": "deep fryer", "confidence": 0.91},
        ]}):
            with self.assertRaises(AuthError) as error:
                build_context(request)
        self.assertEqual(error.exception.code, "DETECTOR_FAILED")
        self.assertEqual(request, original)
