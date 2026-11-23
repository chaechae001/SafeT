import copy
import json
import unittest
from itertools import product
from ai.assessment_authoring.contracts import ROOT, read, load_catalog
from ai.assessment_authoring.analysis_validator import validate_analysis
from ai.assessment_authoring.assessment_composer import compose_assessment, render_assessment
from ai.assessment_authoring.retrieval_adapter import (retrieve_evidence, retrieve_with_evidence, candidate_batches,
                                                       text_candidates, work_supported)
from ai.assessment_authoring.pipeline import run_pipeline

class AuthoringTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.i, self.r, self.a = [read("examples/all_supported/"+n+".json") for n in ("input","retrieval","analysis")]

    def test_five_contract_goldens(self):
        for name in ("unknown","critical_supported","all_supported","partial","no_match"):
            with self.subTest(name=name):
                i,r,a=[read("examples/"+name+"/"+n+".json") for n in ("input","retrieval","analysis")]
                self.assertEqual(compose_assessment(i,r,a,self.catalog),read("examples/"+name+"/assessment.json"))

    def test_invalid_model_fields_and_references(self):
        edits=[("grade","하"),("questions",["질문"]),("scenario_id","BAD"),("evidence",[])]
        for field,value in edits:
            with self.subTest(field=field):
                a=copy.deepcopy(self.a); a["candidates"][0][field]=value
                with self.assertRaises(ValueError): compose_assessment(self.i,self.r,a,self.catalog)
        for field,value in [("control_id","ENV-C1"),("statement","원문에 없는 인용"),
                            ("evidence_refs",[]),("evidence_refs",["MISSING"])]:
            with self.subTest(field=field):
                a=copy.deepcopy(self.a); a["candidates"][0]["control_evidence"][0][field]=value
                with self.assertRaises(ValueError): compose_assessment(self.i,self.r,a,self.catalog)

    def test_no_mutation_and_missing_controls(self):
        a=read("examples/unknown/analysis.json"); before=copy.deepcopy(a)
        normalized=validate_analysis(self.i,self.r,a,self.catalog)
        self.assertEqual(a,before)
        self.assertTrue(all(e["state"]=="unknown" for e in normalized["candidates"][0]["control_evidence"]))

    def test_detection_cannot_support_controls(self):
        self.i["media"][0]["kind"]="equipment_detection"
        with self.assertRaises(ValueError): compose_assessment(self.i,self.r,self.a,self.catalog)

    def test_duplicates_rejected(self):
        self.a["candidates"].append(copy.deepcopy(self.a["candidates"][0]))
        with self.assertRaises(ValueError): compose_assessment(self.i,self.r,self.a,self.catalog)

    def test_forged_document_rejected(self):
        self.r["candidates"][0]["source_refs"][0]["document_id"]="BAD"
        with self.assertRaises(ValueError): compose_assessment(self.i,self.r,self.a,self.catalog)

    def test_legal_registry_required(self):
        ref=dict(legal_id="SYNTHETIC",url="https://example.invalid/test")
        self.r["candidates"][0]["legal_refs"]=[ref]
        with self.assertRaises(ValueError): compose_assessment(self.i,self.r,self.a,self.catalog)
        compose_assessment(self.i,self.r,self.a,self.catalog,legal_registry=[dict(ref,scenario_ids=["FRY"])])
        with self.assertRaises(ValueError):
            compose_assessment(self.i,self.r,self.a,self.catalog,legal_registry=[dict(ref,scenario_ids=["ENV"])])

    def test_nine_policy_cells(self):
        expected={1:["하","중","중"],2:["중","중","상"],3:["상","상","상"]}
        for severity,grades in expected.items():
            for case,grade in zip(("all_supported","critical_supported","unknown"),grades):
                catalog=copy.deepcopy(self.catalog)
                next(s for s in catalog["scenarios"] if s["id"]=="FRY")["severity"]=severity
                a=read("examples/"+case+"/analysis.json"); i=read("examples/"+case+"/input.json")
                self.assertEqual(compose_assessment(i,self.r,a,catalog)["items"][0]["grade"],grade)

    def test_catalog_version_rejected(self):
        self.catalog["policy_version"]="BAD"
        with self.assertRaises(ValueError): compose_assessment(self.i,self.r,self.a,self.catalog)

    def test_equipment_and_text_retrieval(self):
        i=read("examples/input_variants/photo.json")
        self.assertEqual([c["scenario_id"] for c in retrieve_evidence(i,self.catalog)["candidates"]],["FRY"])
        self.i["media"][0]["text"]="젖은 바닥에서 통로 이동"
        self.assertIn("ENV",[c["scenario_id"] for c in retrieve_evidence(self.i,self.catalog)["candidates"]])

    def test_specific_equipment_does_not_overmap(self):
        self.i["equipment_ids"]=["EQ_REFRIGERATOR"]
        self.i["media"][0].update(kind="equipment_inventory",text="일반 냉장고")
        r,trace=retrieve_with_evidence(self.i,self.catalog)
        self.assertEqual(r["candidates"],[])
        self.assertEqual(r["unmatched"], [])
        self.assertTrue(trace["diagnostics"])

    def test_negative_text(self):
        self.i["media"][0]["text"]="가스레인지는 없고 전기 튀김기를 사용합니다."
        ids={c["scenario_id"] for c in retrieve_evidence(self.i,self.catalog)["candidates"]}
        self.assertNotIn("GAS",ids);self.assertIn("FRY",ids)

    def test_negation_targets_without_equipment(self):
        for observation, sid, applies in [
            ("튀김 중 온도 조절기가 없다.", "FRY", True),
            ("튀김기 사용 후 기름이 없는지 확인합니다.", "FRY", True),
            ("가스레인지 사용, 가스 누출 없음 매일 확인", "GAS", True),
            ("튀김은 안 합니다.", "FRY", False),
            ("튀김 작업을 하지 않습니다.", "FRY", False),
            ("튀김은 안 합니다. 다른 곳에서는 튀김 조리를 합니다.", "FRY", True),
        ]:
            with self.subTest(observation=observation):
                self.i["equipment_ids"] = []
                self.i["media"][0]["text"] = observation
                r = retrieve_evidence(self.i, self.catalog)
                self.assertEqual(sid in [c["scenario_id"] for c in r["candidates"]], applies)

    def test_missing_device_control_keeps_fry_through_pipeline(self):
        context = read("examples/input_variants/text.json")
        observation = "튀김 중 온도 조절기가 없다."
        context["media"][0]["text"] = observation
        analysis = read("examples/unknown/analysis.json")
        analysis["candidates"][0]["evidence"][0]["statement"] = observation
        result = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=lambda *args: analysis,
                              catalog_snapshot=self.catalog)
        self.assertEqual([row["scenario_id"] for row in result["assessment"]["rows"]], ["FRY"])

    def test_photo_only_waits_for_work_review(self):
        context = read("examples/input_variants/photo.json")
        def unexpected(*args):
            self.fail("detection alone cannot establish work")
        result = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=unexpected,
                              catalog_snapshot=self.catalog)
        self.assertEqual(result["retrieval_trace"]["work_review_candidates"], ["FRY"])
        self.assertEqual(result["assessment"]["rows"], [])
        self.assertEqual(result["assessment"]["core"]["review_candidates"],
                         [{"scenario_id": "FRY", "reason": "work_unconfirmed"}])

    def test_photo_with_text_preserves_work_status(self):
        for observation, rows, pending, excluded in [
            ("칼로 채소를 썹니다.", [], ["FRY"], []),
            ("주방에서 튀김 조리를 합니다.", ["FRY"], [], []),
            ("튀김은 안 합니다.", [], [], ["FRY"]),
            ("튀김 작업을 하지 않습니다.", [], [], ["FRY"]),
            ("튀김 조리를 하지 않습니다.", [], [], ["FRY"]),
            ("튀김기는 안 씁니다.", [], [], ["FRY"]),
            ("튀김기 온도 조절기가 없다.", [], ["FRY"], []),
            ("튀김은 안 합니다. 다른 곳에서는 튀김 조리를 합니다.", [], ["FRY"], []),
        ]:
            with self.subTest(observation=observation):
                context = read("examples/input_variants/photo.json")
                context["media"].append(dict(id="TEXT", kind="text", text=observation))
                def extract(_, batch, catalog):
                    self.assertFalse(excluded, "explicitly inapplicable work sent to extraction")
                    if rows:
                        return read("examples/unknown/analysis.json")
                    return dict(contract_version="assessment-authoring-1", candidates=[], unmatched_risks=[])

                result = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=extract,
                                      catalog_snapshot=self.catalog)
                self.assertEqual([row["scenario_id"] for row in result["assessment"]["rows"]], rows)
                self.assertEqual(result["retrieval_trace"]["work_review_candidates"], pending)
                self.assertEqual(result["retrieval_trace"]["not_applicable_candidates"], excluded)
                self.assertEqual(result["assessment"]["core"]["review_candidates"],
                                 [{"scenario_id": sid, "reason": "work_unconfirmed"} for sid in pending]
                                 + [{"scenario_id": sid, "reason": "input_denies_work"} for sid in excluded])

    def test_photo_equipment_needs_work_statement(self):
        # 2026-11-22 실제 EXAONE이 무관한 작업 문장을 사진 기기(FRY)의 근거로 인용한 사례.
        cases = [
            ("칼로 채소를 손질합니다.", [], ["FRY"], []),
            ("전자레인지로 음식을 가열합니다.", [], ["FRY"], []),
            ("오늘은 튀김기를 사용하지 않습니다.", [], [], ["FRY"]),
            ("지금은 튀김기를 가동하지 않습니다.", [], [], ["FRY"]),
            ("오늘은 주방에서 튀김기를 가동하지 않습니다.", [], [], ["FRY"]),
            ("오늘은 1층 주방에서 튀김기를 가동하지 않습니다.", [], [], ["FRY"]),
            ("오늘은 주방에서 전기 튀김기를 가동하지 않습니다.", [], [], ["FRY"]),
            ("오늘은 1층 주방에서 전기튀김기를 가동하지 않습니다.", [], [], ["FRY"]),
            ("오늘은 1층 주방에서 전기 튀김기를 가동합니다.", ["FRY"], [], []),
            ("튀김기는 2층에서 가동하지만 1층 주방에서는 전기 튀김기를 가동하지 않습니다.", ["FRY"], [], []),
            ("주방에서 튀김 조리를 합니다.", ["FRY"], [], []),
            # "튀기 시작"은 소스가 튀는 것(튀다)이지 튀김 작업(튀기다)이 아니다.
            ("오븐에서 소스가 튀기 시작합니다.", [], ["FRY"], []),
            # "튀기도·튀기만·튀기는"도 튀다 + 명사형 어미다(PR #51 재리뷰).
            ("오븐에서 소스가 튀기도 합니다.", [], ["FRY"], []),
            ("소스가 튀기만 해요.", [], ["FRY"], []),
            ("냉동 감자를 기름에 튀깁니다.", ["FRY"], [], []),
            # 미사용 절 뒤에 주어 없는 사용 절이 이어지면 제외하지 않고 확인 후보로 둔다.
            ("튀김기는 평일에는 안 쓰고 주말에만 돌려요.", [], ["FRY"], []),
            ("튀김기는 평일에는 안 쓰고 볶음만 해요.", [], [], ["FRY"]),
        ]
        for kind, (observation, rows, pending, excluded) in product(("text", "voice_transcript"), cases):
            with self.subTest(kind=kind, observation=observation):
                context = read("examples/input_variants/photo.json")
                context["media"].append(dict(id="WORK", kind=kind, text=observation))
                extracted = []
                def extract(_, batch, catalog):
                    extracted.append([c["scenario_id"] for c in batch["candidates"]])
                    analysis = read("examples/unknown/analysis.json")
                    if "FRY" not in extracted[-1]:
                        return dict(contract_version="assessment-authoring-1", candidates=[], unmatched_risks=[])
                    analysis["candidates"][0]["evidence"] = [dict(media_id="WORK", statement=observation)]
                    return analysis
                result = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=extract,
                                      catalog_snapshot=self.catalog)
                self.assertEqual([row["scenario_id"] for row in result["assessment"]["rows"]], rows)
                if excluded:
                    self.assertFalse(extracted)
                # 모델에 보낸 후보와 호출을 생략한 후보가 겹치지 않고, 생략한 후보는 행이 되지 않는다.
                skipped = result["retrieval_trace"]["extraction_skipped"]
                self.assertEqual(any("FRY" in batch for batch in extracted), "FRY" not in skipped and not excluded)
                if "FRY" in skipped:
                    self.assertNotIn("FRY", rows)
                self.assertEqual(result["retrieval_trace"]["work_review_candidates"], pending)
                self.assertEqual(result["retrieval_trace"]["not_applicable_candidates"], excluded)
                self.assertEqual(result["assessment"]["core"]["review_candidates"],
                                 [{"scenario_id": sid, "reason": "work_unconfirmed"} for sid in pending]
                                 + [{"scenario_id": sid, "reason": "input_denies_work"} for sid in excluded])

    def test_work_support_ignores_broad_hazard_words(self):
        # 카탈로그 keywords의 위험·조치 단어("가열", "세척")만으로는 사진 기기의 작업 근거가 되지 않는다.
        scenarios = {s["id"]: s for s in self.catalog["scenarios"]}
        for sid, statement, supported in [
            ("FRY", "큰 냄비에 물을 가열해서 육수를 끓입니다.", False),
            ("MIX", "식기를 세척하고 행주를 삶습니다.", False),
            ("MIX", "반죽기 날을 분리해 세척합니다.", True),
            ("FRY", "냉동 감자를 기름에 튀깁니다.", True),
            ("GRIDDLE", "그리들에 버터를 두르고 고기를 굽습니다.", True),
            ("FRY", "칼로 채소를 손질합니다.", False),
            ("FRY", "튀김기는 사용하지 않고 기름 교체만 합니다.", True),
            ("MIX", "반죽기는 고장 나서 쓰지 않습니다.", False),
        ]:
            with self.subTest(statement=statement):
                self.assertEqual(work_supported(scenarios[sid], statement), supported)

    def test_fryer_denial_variants(self):
        # 부사가 끼거나 다음 절로 이어지는 미사용 진술도 미사용으로 인식한다.
        for observation, rows, pending, excluded in [
            ("튀김기를 요즘 사용하지 않습니다.", [], [], ["FRY"]),
            ("튀김기는 현재 가동하지 않습니다.", [], [], ["FRY"]),
            ("요즘은 튀기지 않습니다.", [], [], ["FRY"]),
            ("튀김기는 사용하지 않고 반죽기만 사용합니다.", [], [], ["FRY"]),
            ("튀김기는 사용하지 않지만 기름 교체는 제가 합니다.", ["FRY"], [], []),
        ]:
            with self.subTest(observation=observation):
                context = read("examples/input_variants/photo.json")
                context["media"].append(dict(id="TEXT", kind="text", text=observation))
                def extract(_, batch, catalog):
                    analysis = read("examples/unknown/analysis.json")
                    analysis["candidates"] = [c for c in analysis["candidates"]
                                              if c["scenario_id"] in [b["scenario_id"] for b in batch["candidates"]]]
                    for c in analysis["candidates"]:
                        c["evidence"] = [dict(media_id="TEXT", statement=observation)]
                    return analysis
                result = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=extract,
                                      catalog_snapshot=self.catalog)
                self.assertEqual([row["scenario_id"] for row in result["assessment"]["rows"]], rows)
                self.assertEqual(result["retrieval_trace"]["work_review_candidates"], pending)
                self.assertEqual(result["retrieval_trace"]["not_applicable_candidates"], excluded)

    def test_negation_variant_set(self):
        # 합성 변형 회귀셋(장소·수식어·시점·이유·구어·부호 없는 음성 전사·연결 절, 위험·조치 부정 포함).
        data = json.loads((ROOT / "ai/experiments/261123_미사용판정_형태소_DR/261123_미사용판정_변형셋_v1_DR.json")
                          .read_text(encoding="utf-8"))
        for item in data["items"]:
            with self.subTest(id=item["id"], text=item["text"]):
                hits, denied = text_candidates(dict(id=item["id"], text=item["text"]), [])
                got = dict(FRY=["FRY" in hits, denied],
                           **{sid: sid in hits for sid in item["expected"] if sid != "FRY"})
                self.assertEqual(got, item["expected"])

    def test_uncertain_denial_without_photo_stays_for_review(self):
        # 사진이 없어도 불확실한 미사용 진술은 사라지지 않고 작업 미확인 후보로 남는다.
        for observation, uncertain, excluded in [
            ("튀김기는 평일에는 안 쓰고 주말에만 돌려요.", ["FRY"], []),
            ("음 튀김기는 오전엔 안 돌리고 오후에 돌려요", ["FRY"], []),
            ("튀김기는 평일에는 안 쓰고 볶음만 해요.", [], ["FRY"]),
        ]:
            with self.subTest(observation=observation):
                self.i["equipment_ids"] = []
                self.i["media"][0]["text"] = observation
                bundle, trace = retrieve_with_evidence(self.i, self.catalog)
                self.assertEqual(trace["uncertain_work_candidates"], uncertain)
                self.assertEqual(trace["not_applicable_candidates"], excluded)
                self.assertEqual("FRY" in [c["scenario_id"] for c in bundle["candidates"]], bool(uncertain))

    def test_fry_verb_terms_follow_morphemes(self):
        # 튀김 동사 기준어는 형태소 분석이 튀기다(VV "튀기")라고 할 때만 인정한다.
        # 모의 토큰은 kiwipiepy 0.25.1의 실제 출력과 같다. 판정이 글자 일치가 아닌 형태소를 따르는지 확인한다.
        from unittest import mock
        from ai.assessment_authoring import negation
        splash = (("오븐", "NNG", 0, 2), ("에서", "JKB", 2, 4), ("소스", "NNG", 5, 7), ("가", "JKS", 7, 8),
                  ("튀", "VV", 9, 10), ("기", "ETN", 10, 11), ("도", "JX", 11, 12), ("하", "VX", 13, 14),
                  ("ᆸ니다", "EF", 13, 16), (".", "SF", 16, 17))
        fry = (("감자", "NNG", 0, 2), ("를", "JKO", 2, 3), ("튀기", "VV", 4, 6), ("기", "ETN", 6, 7),
               ("도", "JX", 7, 8), ("하", "VX", 9, 10), ("ᆸ니다", "EF", 9, 12), (".", "SF", 12, 13))
        for text, tokens, expected in [("오븐에서 소스가 튀기도 합니다.", splash, False),
                                       ("감자를 튀기기도 합니다.", fry, True)]:
            with self.subTest(text=text), mock.patch.object(negation, "_tokens", lambda _t, tokens=tokens: tokens):
                self.assertEqual("FRY" in text_candidates(dict(id="TEXT", text=text), [])[0], expected)

    def test_fry_verb_terms_with_kiwi(self):
        # 실제 kiwipiepy(requirements 고정 버전)로 튀다·튀기다를 구분한다.
        import kiwipiepy
        self.assertEqual(kiwipiepy.__version__, "0.25.1")
        for observation, hits, fry_denied in [
            ("오븐에서 소스가 튀기도 합니다.", {"OVEN"}, False),
            ("감자를 튀기기도 합니다.", {"FRY"}, False),
            ("기름이 튀기도 하고 닭도 튀겨요.", {"FRY"}, False),
            ("오븐에서 소스가 튀기 시작합니다.", {"OVEN"}, False),
            ("요즘은 튀기지 않습니다.", set(), True),
            ("튀김기는 안 씁니다.", set(), True),
        ]:
            with self.subTest(observation=observation):
                self.assertEqual(text_candidates(dict(id="TEXT", text=observation), []), (hits, fry_denied))

    def test_equipment_candidate_without_work_sentence_skips_model(self):
        # 다기기 사진 502(2026-11-23): 작업 문장이 그리들을 언급하지 않는데 GRIDDLE을 모델에 보내
        # 공백 반복으로 출력이 잘렸다. 어느 문장도 작업 근거가 되지 않는 사진 후보는 결과가 같으므로 보내지 않는다.
        context = read("examples/input_variants/photo.json")
        context["equipment_ids"] = ["EQ_FRYER", "EQ_GRIDDLE"]
        context["media"].append(dict(id="WORK", kind="text", text="튀김기로 조리합니다. 기름은 식힌 뒤 배유합니다."))
        sent = []
        def extract(_, batch, catalog):
            sent.extend(c["scenario_id"] for c in batch["candidates"])
            return dict(contract_version="assessment-authoring-1", candidates=[], unmatched_risks=[])
        result = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=extract,
                              catalog_snapshot=self.catalog, batch_size=1)
        trace = result["retrieval_trace"]
        self.assertIn("GRIDDLE", trace["extraction_skipped"])
        self.assertNotIn("GRIDDLE", sent)
        self.assertIn("FRY", sent)
        # 생략한 후보도 사람이 확인할 작업 미확인 후보로 남는다.
        self.assertIn({"scenario_id": "GRIDDLE", "reason": "work_unconfirmed"},
                      result["assessment"]["core"]["review_candidates"])

    def test_judge_marks_uncertain_unused_statements(self):
        # 문맥이 필요한 미사용 진술은 잠정 미사용·불확실로, 위험·조치 부정은 확실한 사용으로 둔다.
        from ai.assessment_authoring.negation import judge
        for observation, verdict, certain in [
            ("튀김기는 안 돌려요.", "unused", True),
            ("튀김기 스위치를 안 켜요.", "unused", False),
            ("튀김기는 지난주에 치웠어요.", "unused", False),
            ("튀김 메뉴는 없앴어요.", "unused", False),
            ("튀김기 말고 그리들만 써요.", "unused", False),
            ("튀김기가 있긴 하지만 안 돌려요.", "unused", False),
            ("튀김기는 아침엔 안 쓰고 저녁에만 돌려요.", "used", False),
            ("튀김기는 오전엔 안 쓰고 오후 장사 때만 켜요.", "used", False),
            ("튀김은 안 합니다. 철판 조리만 합니다.", "unused", True),
            ("튀김기 기름을 안 갈아요.", "used", True),
            ("튀김기 스위치를 안 끄고 퇴근해요.", "used", True),
            ("튀김기 전원 코드가 낡았는데 수리를 안 했어요.", "used", True),
        ]:
            with self.subTest(observation=observation):
                start = observation.index("튀김")
                self.assertEqual(judge(observation, start, start + 2)[:2], (verdict, certain))

    def test_negation_judge_confirms_only_when_rule_agrees(self):
        # 모델 판정은 규칙의 잠정 판정과 같을 때만 확정한다. 다르거나 검증에 실패하면 작업 미확인이다.
        def fake(status, quote=None, fail=False):
            def judge(text, targets):
                if fail:
                    raise RuntimeError("관문 오류")
                return {sid: dict(status=status, quote=quote or text) for sid in targets}
            return judge
        cases = [
            ("튀김기 스위치를 안 켜요.", fake("unused"), [], ["FRY"], "unused"),
            ("튀김기 스위치를 안 켜요.", fake("used"), ["FRY"], [], "review"),
            ("튀김기 스위치를 안 켜요.", fake("unknown"), ["FRY"], [], "review"),
            ("튀김기 스위치를 안 켜요.", fake("unused", quote="튀김기는 없어요"), ["FRY"], [], "review"),
            ("튀김기 스위치를 안 켜요.", fake("unused", quote="스위치를 안 켜요"), ["FRY"], [], "review"),
            ("튀김기 스위치를 안 켜요.", fake("unused", fail=True), ["FRY"], [], "review"),
            # 생략 주어 사용 절은 모델이 미사용이라 해도 제외하지 않는다.
            ("튀김기는 아침엔 안 쓰고 저녁에만 돌려요.", fake("unused"), ["FRY"], [], "review"),
            ("튀김기는 아침엔 안 쓰고 저녁에만 돌려요.", fake("used"), [], [], "used"),
        ]
        for observation, judge, uncertain, excluded, decision in cases:
            with self.subTest(observation=observation, decision=decision):
                self.i["equipment_ids"] = ["EQ_FRYER"]
                self.i["media"][0]["text"] = observation
                _, trace = retrieve_with_evidence(self.i, self.catalog, negation_judge=judge)
                self.assertEqual(trace["uncertain_work_candidates"], uncertain)
                self.assertEqual(trace["not_applicable_candidates"], excluded)
                self.assertEqual([j["decision"] for j in trace["negation_judgements"]], [decision])
                self.assertEqual("FRY" in trace["text_candidates"], decision == "used")

    def test_negation_targets_other_noun(self):
        # 다른 명사가 부정의 대상이면 기기 미사용이 아니다.
        for observation, sid, applies in [
            ("튀김기의 온도 제어 장치가 작동하지 않습니다.", "FRY", True),
            ("가스레인지 사용, 가스 누출 없음 매일 확인", "GAS", True),
            ("튀김기 기름을 자주 갈지 않습니다.", "FRY", True),
            ("음 튀김기는 요즘 고장 나서 쓸 일 없어요", "FRY", False),
            ("튀김기는 손님이 없어서 안 돌려요.", "FRY", False),
        ]:
            with self.subTest(observation=observation):
                hits, _ = text_candidates(dict(id="TEXT", text=observation), [])
                self.assertEqual(sid in hits, applies)

    def test_text_terms_cover_verb_forms_and_device_names(self):
        for observation, expected in [
            ("돈가스를 튀기고 철판에서 전을 부칩니다.", {"FRY", "GRIDDLE"}),
            ("칼로 고기를 썰고 반죽기로 면 반죽을 합니다.", {"KNIFE", "MIX"}),
            ("믹서기로 소스를 갈아 만듭니다.", {"MIX"}),
            ("튀김기 옆 바닥에 기름이 떨어져 미끄럽습니다.", {"FRY", "ENV"}),
            ("칼로리 표시를 확인합니다.", set()),
            ("오븐에서 소스가 튀기 시작합니다.", {"OVEN"}),
            ("오븐에서 소스가 튀기도 합니다.", {"OVEN"}),
            ("소스가 튀기는 해요.", set()),
            ("돈가스를 튀겨요.", {"FRY"}),
            ("감자를 튀기기 시작합니다.", {"FRY"}),
            ("돈가스를 튀기는 중입니다.", {"FRY"}),
            ("요즘은 튀기지 않습니다.", set()),
        ]:
            with self.subTest(observation=observation):
                hits, _ = text_candidates(dict(id="TEXT", text=observation), [])
                self.assertEqual(hits, expected)

    def test_irrelevant_note_does_not_make_draft_partial(self):
        self.i["media"].append(dict(id="NOTE", kind="text", text="주방 정리"))
        r, trace = retrieve_with_evidence(self.i, self.catalog)
        self.assertTrue(trace["diagnostics"])
        self.assertEqual(compose_assessment(self.i, r, self.a, self.catalog)["result_status"], "complete")

    def test_negated_fragment_and_mixed_evidence_rejected(self):
        self.i["media"].append(dict(id="NEG", kind="text", text="보호구를 착용하지 않습니다."))
        self.i["media"].append(dict(id="PHOTO", kind="equipment_detection", text="보호구"))
        control = self.a["candidates"][0]["control_evidence"][0]
        for quote, refs in [("보호구를 착용", ["NEG"]), (control["statement"], ["TEXT", "PHOTO"])]:
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                control.update(statement=quote, evidence_refs=refs)
                validate_analysis(self.i, self.r, self.a, self.catalog)

    def test_batches_preserve_all_candidates(self):
        self.i["equipment_ids"]=["EQ_FRYER","EQ_OVEN","EQ_LADDER","EQ_GAS_RANGE"]
        r=retrieve_evidence(self.i,self.catalog)
        batches=candidate_batches(r)
        self.assertGreater(len(batches),1)
        self.assertEqual(sum(len(b["candidates"]) for b in batches),len(r["candidates"]))
        self.assertTrue(all(len(c["source_refs"])<=2 for c in r["candidates"]))

    def test_rag_injection_preserves_provenance(self):
        self.i["equipment_ids"]=["EQ_FRYER"]
        response={"data_version":"synthetic","index_sha256":"test",
                  "candidates":[{"equipment_ids":["EQ_FRYER"],"hazard_code":"burn",
                                 "hazard_texts":["합성 근거"],"source_ids":["SYNTHETIC"]}]}
        def provider(ids,k):
            self.assertEqual(ids,["EQ_FRYER"]); self.assertIsNone(k)
            return response
        r,trace=retrieve_with_evidence(self.i,self.catalog,rag_provider=provider,rag_links={"EQ_FRYER:burn":["FRY"]})
        self.assertEqual(trace["rag_response"],response)
        self.assertEqual(r["candidates"][0]["scenario_id"],"FRY")
        self.assertNotIn("SYNTHETIC",str(r["candidates"][0]["source_refs"]))

    def test_unmapped_rag_hazard_preserved(self):
        self.i["equipment_ids"]=["EQ_FRYER"]
        r,trace=retrieve_with_evidence(self.i,self.catalog,rag_provider=lambda *a,**kw:dict(candidates=[
            dict(equipment_ids=["EQ_FRYER"],hazard_code="unknown")]))
        self.assertEqual(r["unmatched"], [])
        self.assertTrue(any("unknown" in s for s in trace["diagnostics"]))

    def test_rag_failure_not_empty_success(self):
        self.i["equipment_ids"]=["EQ_FRYER"]
        def fail(*a,**kw): raise RuntimeError("offline")
        with self.assertRaises(RuntimeError):retrieve_evidence(self.i,self.catalog,rag_provider=fail)

    def test_no_evidence_does_not_remove_valid_row(self):
        self.r["candidates"][0].update(source_refs=[],retrieval_status="no_evidence")
        self.assertEqual(compose_assessment(self.i,self.r,self.a,self.catalog)["items"][0]["grade"],"중")

    def test_recommendations_do_not_change_current_grade(self):
        a=read("examples/unknown/analysis.json")
        rendered=render_assessment(self.i,self.r,a,self.catalog)
        self.assertEqual(rendered["core"]["items"][0]["grade"],"상")
        self.assertTrue(rendered["rows"][0]["improvement_candidates"])
        self.assertEqual(rendered["rows"][0]["current_controls"],[])

    def test_fixed_input_and_extraction_pipeline(self):
        i=read("examples/unknown/input.json");a=read("examples/unknown/analysis.json")
        result=run_pipeline(i,build_context=copy.deepcopy,extract_analysis=lambda *args:copy.deepcopy(a),catalog_snapshot=self.catalog)
        self.assertEqual(result["assessment"]["core"],read("examples/unknown/assessment.json"))

    def test_empty_search_skips_model(self):
        self.i["media"][0]["text"]="카탈로그 밖 합성 작업"
        def fail(*args):raise AssertionError("must not call model")
        result=run_pipeline(self.i,build_context=copy.deepcopy,extract_analysis=fail,catalog_snapshot=self.catalog)
        self.assertEqual(result["assessment"]["core"]["result_status"],"no_supported_result")

    def test_empty_input_rejected(self):
        self.i["media"]=[]
        with self.assertRaises(ValueError):retrieve_evidence(self.i,self.catalog)

if __name__=="__main__":
    unittest.main()

