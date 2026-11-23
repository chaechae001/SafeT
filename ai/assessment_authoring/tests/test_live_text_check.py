import unittest
from ai.assessment_authoring.live_text_check import output_budget, parse_completion

class LiveTransportTests(unittest.TestCase):
    def test_model_rationale_is_not_displayed_as_verified_fact(self):
        from ai.assessment_authoring.contracts import read, load_catalog
        from ai.assessment_authoring.assessment_composer import render_assessment
        i, r, a = [read("examples/unknown/" + n + ".json") for n in ("input", "retrieval", "analysis")]
        a["candidates"][0]["rationale"] = "안전 조치가 없습니다."
        result = render_assessment(i, r, a, load_catalog())
        self.assertNotIn("안전 조치가 없습니다", result["rows"][0]["rationale"])
        self.assertEqual(result["core"]["items"][0]["grade"], "상")

    def test_budget_includes_safety_margin(self):
        self.assertEqual(output_budget(3000), 1032)
        self.assertEqual(output_budget(1000), 1536)

    def test_invalid_or_insufficient_budget(self):
        for count in (True, -1, 4000, "10"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                output_budget(count)

    def test_truncated_response_rejected(self):
        response = {"choices":[{"finish_reason":"length","message":{"content":"{}"}}]}
        with self.assertRaises(ValueError):
            parse_completion(response)

    def test_whitespace_runaway_after_complete_body_is_repaired(self):
        # 2026-11-23 다기기 502 원문: 본문을 다 쓴 뒤 바깥 "}" 대신 줄바꿈·공백만 반복하다 길이 제한에 걸림.
        body = ('{\n  "candidates": [\n    {\n      "scenario_id": "GRIDDLE",\n'
                '      "work_ref": "S1"  ,\n      "controls": []\n    }\n  ]')
        response = {"choices": [{"finish_reason": "length", "message": {"content": body + "\n  " * 200}}]}
        self.assertEqual(parse_completion(response),
                         {"candidates": [{"scenario_id": "GRIDDLE", "work_ref": "S1", "controls": []}]})

    def test_truncation_inside_body_is_not_repaired(self):
        cases = [
            '{"candidates": [{"scenario_id": "FRY", "work_ref": "S1", "controls": [{"control_id": "FRY-C1", "sta',
            '{"candidates": [{"scenario_id": "FRY", "work_ref": "S1", "controls": [' + " " * 200,
            '{"candidates": []}' + " " * 10,
        ]
        for content in cases:
            with self.subTest(content=content[:40]), self.assertRaises(ValueError):
                parse_completion({"choices": [{"finish_reason": "length", "message": {"content": content}}]})

    def test_prompt_asks_single_line_json(self):
        from ai.assessment_authoring.contracts import read, load_catalog
        from ai.assessment_authoring.live_text_check import build_messages
        i, r = [read("examples/unknown/" + n + ".json") for n in ("input", "retrieval")]
        self.assertIn("줄바꿈과 들여쓰기 없이 한 줄로", build_messages(i, r, load_catalog())[0]["content"])

    def test_only_json_object_accepted(self):
        response = {"choices":[{"finish_reason":"stop","message":{"content":"[]"}}]}
        with self.assertRaises(ValueError):
            parse_completion(response)
        response["choices"][0]["message"]["content"] = '{"candidates":[]}'
        self.assertEqual(parse_completion(response), {"candidates":[]})


    def test_citations_resolve_to_original_input_and_reject_document_ids(self):
        from ai.assessment_authoring.live_text_check import resolve_input_citations
        context = {"media": [{"id": "TEXT", "kind": "text", "text": "튀김 작업을 합니다. 기름은 식힌 후 뺍니다."}]}
        control = dict(control_id="FRY-C2", state="supported", input_ref="S2")
        candidate = dict(scenario_id="FRY", work_ref="S1", controls=[control, dict(control, control_id="FRY-C1")])
        resolved = resolve_input_citations({"candidates": [candidate]}, context)["candidates"][0]
        self.assertEqual(len(resolved["control_evidence"]), 1)
        self.assertEqual(resolved["control_evidence"][0]["statement"], "기름은 식힌 후 뺍니다.")
        self.assertEqual(resolved["evidence"][0]["statement"], "튀김 작업을 합니다.")
        with self.assertRaises(KeyError):
            resolve_input_citations({"candidates": [dict(candidate, work_ref="N02-p012")]}, context)
