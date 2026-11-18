"""extract_analysis mock 검사. 표준 라이브러리만 사용하며 실제 모델을 호출하지 않는다.

실행(저장소 루트): python -m unittest discover -s ai/assessment_authoring/tests -v
"""
import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from ai.assessment_authoring import extraction_adapter as ea
from ai.assessment_authoring.pipeline import run_pipeline
from contracts.assessment_authoring.v1.validate import validate as CONTRACT_VALIDATE

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures/extraction"
CONTRACT = ea.CONTRACT
CATALOG = json.loads((CONTRACT / "reference/catalog.json").read_text(encoding="utf-8-sig"))
CASES = ["normal", "unknown", "detection_only", "negation", "conflict", "composite_partial", "no_match"]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_case(name):
    d = FIXTURES / name
    mock = d / "model_response.json"
    return read(d / "input.json"), read(d / "retrieval.json"), (read(mock) if mock.exists() else None)


class Mock:
    """배치 순서대로 고정 응답을 돌려주고 받은 메시지를 기록한다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("unexpected model call")
        return dict(self.responses.pop(0), model="mock", max_tokens=1024)


def response(candidates, unmatched=(), finish="stop"):
    return {"finish_reason": finish,
            "content": json.dumps({"candidates": candidates, "unmatched_risks": list(unmatched)}, ensure_ascii=False)}


class FixtureCases(unittest.TestCase):
    def test_fixture_outputs_match_and_pass_contract(self):
        for name in CASES:
            with self.subTest(case=name):
                i, r, m = load_case(name)
                mock = Mock(*([m] if m else []))
                result = ea.run_extraction(i, r, CATALOG, call_model=mock)
                self.assertEqual(result.analysis, read(FIXTURES / name / "analysis.json"))
                self.assertEqual(len(mock.calls), 1 if m else 0)
                # compose_assessment 경계: 공통 계약 검사기를 통과해야 한다.
                CONTRACT_VALIDATE(i, r, result.analysis)
                for c in result.analysis["candidates"]:
                    self.assertEqual(c["questions"], [])
                    self.assertFalse({"grade", "severity", "signal", "checked"} & c.keys())

    def states(self, name):
        i, r, m = load_case(name)
        a = ea.extract_analysis(i, r, CATALOG, call_model=Mock(m))
        return {e["control_id"]: e["state"] for e in a["candidates"][0]["control_evidence"]}, a

    def test_normal_supported_only_with_quotes(self):
        states, _ = self.states("normal")
        self.assertEqual(states, {"FRY-C1": "supported", "FRY-C2": "supported", "FRY-C7": "supported"})

    def test_negation_is_not_effective(self):
        states, _ = self.states("negation")
        self.assertEqual(states, {"FRY-C1": "not_effective", "FRY-C5": "not_effective"})

    def test_conflict_and_composite_partial_are_unknown(self):
        for name in ("conflict", "composite_partial"):
            states, _ = self.states(name)
            self.assertEqual(states, {"FRY-C7": "unknown"})

    def test_photo_only_keeps_candidates_without_model_call(self):
        # 사진·기기 목록만: 모델을 부르지 않고 분석 행은 비우며 검색 후보는 작업 확인 대상으로 남긴다.
        i, r, _ = load_case("detection_only")
        mock_model = Mock()
        result = ea.run_extraction(i, r, CATALOG, call_model=mock_model)
        self.assertEqual(mock_model.calls, [])
        self.assertEqual(result.analysis["candidates"], [])
        self.assertEqual(result.work_review_candidates, ["FRY"])

    def test_mixed_input_keeps_unconfirmed_detection(self):
        # 사진에 튀김기, 글에는 다른 작업만 있으면 FRY는 행이 아니라 작업 확인 대상으로 남는다.
        i, r, _ = load_case("detection_only")
        i["media"].append({"id": "TEXT", "kind": "text", "text": "칼로 채소를 썹니다."})
        mock_model = Mock(response([]))
        result = ea.run_extraction(i, r, CATALOG, call_model=mock_model)
        self.assertEqual(len(mock_model.calls), 1)
        self.assertEqual(result.work_review_candidates, ["FRY"])
        CONTRACT_VALIDATE(i, r, result.analysis)

    def test_pipeline_with_retrieval_and_composer(self):
        # 검색·검증·계산(#32) run_pipeline에 이 어댑터를 그대로 넣어 연결을 확인한다.
        i, _, m = load_case("negation")
        extract = lambda c, b, k: ea.extract_analysis(c, b, k, call_model=Mock(m))  # noqa: E731
        out = run_pipeline(i, build_context=copy.deepcopy, extract_analysis=extract, catalog_snapshot=CATALOG)
        core = out["assessment"]["core"]
        self.assertEqual([(x["scenario_id"], x["control_band"], x["grade"]) for x in core["items"]], [("FRY", 3, "상")])
        self.assertEqual(core["result_status"], "complete")
        self.assertEqual(core["review_candidates"], [])

    def test_pipeline_review_candidates_with_adapter(self):
        # 사진 단독·사진+글 혼합에서 이 어댑터를 넣어도 공통 결과 core.review_candidates로 검토 대상이 남는다.
        i, _, _ = load_case("detection_only")
        mixed = copy.deepcopy(i)
        mixed["media"].append({"id": "TEXT", "kind": "text", "text": "칼로 채소를 썹니다."})
        for context, model in ((i, Mock()), (mixed, Mock(response([])))):
            with self.subTest(media=[m["kind"] for m in context["media"]]):
                extract = lambda c, b, k: ea.extract_analysis(c, b, k, call_model=model)  # noqa: E731
                out = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=extract,
                                   catalog_snapshot=CATALOG)
                core = out["assessment"]["core"]
                self.assertEqual(core["items"], [])
                self.assertEqual(core["review_candidates"], [{"scenario_id": "FRY", "reason": "work_unconfirmed"}])

    def test_no_match_keeps_unmatched_without_model_call(self):
        i, r, _ = load_case("no_match")
        a = ea.extract_analysis(i, r, CATALOG, call_model=Mock())
        self.assertEqual(a, {"contract_version": "assessment-authoring-1", "candidates": [],
                             "unmatched_risks": ["매장 외부 간판 교체 작업"]})


class Messages(unittest.TestCase):
    def test_prompt_and_payload(self):
        i, r, m = load_case("normal")
        mock = Mock(m)
        ea.extract_analysis(i, r, CATALOG, call_model=mock)
        system, user = mock.calls[0]
        self.assertEqual(system["content"], ea.load_system_prompt()[0])
        payload = json.loads(user["content"])
        self.assertEqual(payload["input"]["media"], i["media"])
        scenario = payload["candidate_scenarios"][0]
        self.assertEqual([c["control_id"] for c in scenario["controls"]],
                         [c["id"] for c in next(s for s in CATALOG["scenarios"] if s["id"] == "FRY")["controls"]])
        for banned in ("severity", "initial_grade", "plan_text", "grade"):
            self.assertNotIn('"' + banned + '"', user["content"])

    def test_batches_of_three_and_merge(self):
        i, _, _ = load_case("unknown")
        ids = ["FRY", "GAS", "KNIFE", "CUT"]
        cat = {s["id"]: s for s in CATALOG["scenarios"]}
        r = {"contract_version": "assessment-authoring-1", "unmatched": ["검색 미매칭"],
             "candidates": [{"scenario_id": s, "source_refs": cat[s]["source_refs"][:2], "legal_refs": [],
                             "retrieval_status": "matched"} for s in ids]}
        fry = {"scenario_id": "FRY", "rationale": "튀김 조리 위험",
               "evidence": [{"media_id": "TEXT", "statement": "주방에서 튀김 조리를 합니다."}],
               "control_evidence": [], "assumptions": [], "questions": []}
        mock = Mock(response([fry], ["모델 미매칭"]), response([], ["검색 미매칭"]))
        result = ea.run_extraction(i, r, CATALOG, call_model=mock)
        self.assertEqual([run["scenario_ids"] for run in result.runs], [["FRY", "GAS", "KNIFE"], ["CUT"]])
        self.assertEqual([c["scenario_id"] for c in result.analysis["candidates"]], ["FRY"])
        self.assertEqual(result.analysis["unmatched_risks"], ["검색 미매칭", "모델 미매칭"])
        self.assertEqual(result.work_review_candidates, ["GAS", "KNIFE", "CUT"])
        CONTRACT_VALIDATE(i, r, result.analysis)


class Failures(unittest.TestCase):
    """응답 중단·잘못된 JSON·근거 위반은 성공 Bundle 없이 오류로 반환한다."""

    def setUp(self):
        self.i, self.r, self.m = load_case("normal")
        self.good = json.loads(self.m["content"])

    def expect(self, code, resp):
        with self.assertRaises(ea.ExtractionError) as ctx:
            ea.extract_analysis(self.i, self.r, CATALOG, call_model=Mock(resp))
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def mutated(self, fn):
        data = copy.deepcopy(self.good)
        fn(data)
        return {"finish_reason": "stop", "content": json.dumps(data, ensure_ascii=False)}

    def test_truncated(self):
        e = self.expect("MODEL_OUTPUT_TRUNCATED", {"finish_reason": "length", "content": self.m["content"][:80]})
        self.assertEqual(e.batch, ["FRY"])

    def test_incomplete(self):
        self.expect("MODEL_OUTPUT_INCOMPLETE", {"finish_reason": "content_filter", "content": self.m["content"]})

    def test_invalid_json(self):
        for content in ('{"candidates": [', "", "[]", "결과: {}", '{"candidates": []} 추가 설명', "```json\n{}"):
            with self.subTest(content=content):
                self.expect("MODEL_OUTPUT_INVALID_JSON", {"finish_reason": "stop", "content": content})

    def test_code_fence_is_accepted(self):
        fenced = {"finish_reason": "stop", "content": "```json\n" + self.m["content"] + "\n```"}
        a = ea.extract_analysis(self.i, self.r, CATALOG, call_model=Mock(fenced))
        self.assertEqual(a, read(FIXTURES / "normal/analysis.json"))

    def test_schema_violations(self):
        cases = {
            "grade": lambda d: d["candidates"][0].update(grade="하"),
            "severity": lambda d: d["candidates"][0].update(severity=2),
            "question": lambda d: d["candidates"][0].update(questions=["보안경을 쓰나요?"]),
            "bad_state": lambda d: d["candidates"][0]["control_evidence"][0].update(state="partial"),
            "no_evidence": lambda d: d["candidates"][0].update(evidence=[]),
            "extra_top": lambda d: d.update(note="x"),
            "bad_version": lambda d: d.update(contract_version="v0"),
            "missing_rationale": lambda d: d["candidates"][0].pop("rationale"),
        }
        for name, fn in cases.items():
            with self.subTest(name=name):
                self.expect("MODEL_OUTPUT_SCHEMA", self.mutated(fn))

    def test_reference_violations(self):
        ce = lambda d: d["candidates"][0]["control_evidence"]  # noqa: E731
        cases = {
            "fake_scenario_quote": lambda d: d["candidates"][0]["evidence"][0].update(statement="주방에서 튀김을 합니다."),
            "fake_control_quote": lambda d: ce(d)[0].update(statement="과열 방지 장치가 정상입니다."),
            "partial_control_quote": lambda d: ce(d)[1].update(statement="기름은 완전히 식힌 뒤"),
            "partial_scenario_quote": lambda d: d["candidates"][0]["evidence"][0].update(statement="튀김 조리를 합니다."),
            "unknown_media": lambda d: ce(d)[0].update(evidence_refs=["VOICE"]),
            "missing_refs": lambda d: ce(d)[0].update(evidence_refs=[]),
            "duplicate_refs": lambda d: ce(d)[0].update(evidence_refs=["TEXT", "TEXT"]),
            "unknown_control": lambda d: ce(d)[0].update(control_id="FRY-C99"),
            "other_scenario_control": lambda d: ce(d)[0].update(control_id="GAS-C1"),
            "duplicate_control": lambda d: ce(d).append(copy.deepcopy(ce(d)[0])),
            "scenario_outside_batch": lambda d: d["candidates"][0].update(scenario_id="GAS"),
            "duplicate_scenario": lambda d: d["candidates"].append(copy.deepcopy(d["candidates"][0])),
            "duplicate_evidence": lambda d: d["candidates"][0]["evidence"].append(dict(d["candidates"][0]["evidence"][0])),
        }
        for name, fn in cases.items():
            with self.subTest(name=name):
                self.expect("MODEL_OUTPUT_REFERENCE", self.mutated(fn))

    def test_detection_cannot_establish_work_or_control(self):
        i, r, _ = load_case("detection_only")
        i["media"].append({"id": "TEXT", "kind": "text", "text": "튀김 조리를 합니다."})
        photo = "튀김기 후보가 탐지되었습니다. 작동 상태는 알 수 없습니다."
        cand = {"scenario_id": "FRY", "rationale": "튀김기 탐지",
                "evidence": [{"media_id": "PHOTO1", "statement": photo}],
                "control_evidence": [], "assumptions": [], "questions": []}
        # 글이 있어도 작업 근거를 탐지 요약만으로 만들면 거절한다.
        with self.assertRaises(ea.ExtractionError) as ctx:
            ea.extract_analysis(i, r, CATALOG, call_model=Mock(response([cand])))
        self.assertEqual(ctx.exception.code, "MODEL_OUTPUT_REFERENCE")
        # 작업 문장이 있어도 탐지 media로 조치를 판정하지 못한다.
        cand["evidence"].append({"media_id": "TEXT", "statement": "튀김 조리를 합니다."})
        cand["control_evidence"] = [{"control_id": "FRY-C1", "state": "supported",
                                     "evidence_refs": ["TEXT", "PHOTO1"], "statement": "튀김 조리를 합니다."}]
        with self.assertRaises(ea.ExtractionError) as ctx:
            ea.extract_analysis(i, r, CATALOG, call_model=Mock(response([cand])))
        self.assertEqual(ctx.exception.code, "MODEL_OUTPUT_REFERENCE")

    def test_error_does_not_leak_model_text(self):
        secret = "원문노출금지"
        e = self.expect("MODEL_OUTPUT_INVALID_JSON", {"finish_reason": "stop", "content": secret + " {"})
        self.assertNotIn(secret, str(e))

    def test_invalid_inputs(self):
        bad_r = copy.deepcopy(self.r)
        bad_r["candidates"][0]["scenario_id"] = "NOPE"
        bad_cat = dict(CATALOG, policy_version="OLD")
        bad_i = copy.deepcopy(self.i)
        bad_i["media"] = []
        for args in ((self.i, bad_r, CATALOG), (self.i, self.r, bad_cat), (bad_i, self.r, CATALOG)):
            with self.subTest(), self.assertRaises(ea.ExtractionError) as ctx:
                ea.extract_analysis(*args, call_model=Mock())
            self.assertEqual(ctx.exception.code, "INPUT_INVALID")


class SetupErrors(unittest.TestCase):
    """클라우드 연결 전 설정·계수 오류가 문서의 ExtractionError로 전달되는지 확인한다(네트워크 없음)."""

    class AuthError(Exception):
        def __init__(self, status, code, message):
            super().__init__(message)
            self.status, self.code, self.message = status, code, message

    def fake_backend(self, fail_at, code):
        def raiser(*args, **kwargs):
            raise self.AuthError(503, code, "안내 문구")
        svc = types.ModuleType("services.catalog_ai")
        svc.configuration = raiser if fail_at == "configuration" else (lambda: ("http://model.invalid/v1", "m", 1024))
        svc.model_headers = lambda: {}
        svc.output_budget = raiser if fail_at == "output_budget" else (lambda *a: 1024)
        auth = types.ModuleType("services.auth")
        auth.AuthError = self.AuthError
        pkg = types.ModuleType("services")
        pkg.catalog_ai, pkg.auth = svc, auth
        httpx = types.ModuleType("httpx")
        return {"services": pkg, "services.catalog_ai": svc, "services.auth": auth, "httpx": httpx}

    def run_default(self):
        i, r, _ = load_case("normal")
        with self.assertRaises(ea.ExtractionError) as ctx:
            ea.extract_analysis(i, r, CATALOG)  # call_model 생략 → exaone_chat
        return ctx.exception

    def test_backend_setup_errors_map_to_extraction_error(self):
        cases = [("configuration", "AI_UNCONFIGURED", "MODEL_UNCONFIGURED"),
                 ("output_budget", "AI_TOKENIZE_FAILED", "MODEL_TOKENIZE_FAILED"),
                 ("output_budget", "AI_INPUT_TOO_LONG", "INPUT_TOO_LONG")]
        for fail_at, backend_code, expected in cases:
            with self.subTest(backend_code), mock.patch.dict(sys.modules, self.fake_backend(fail_at, backend_code)):
                e = self.run_default()
                self.assertEqual(e.code, expected)
                self.assertNotIn("안내 문구", str(e))

    def test_missing_backend_client_is_unconfigured(self):
        with mock.patch.dict(sys.modules, {"services": None, "services.catalog_ai": None}):
            self.assertEqual(self.run_default().code, "MODEL_UNCONFIGURED")


if __name__ == "__main__":
    unittest.main()
