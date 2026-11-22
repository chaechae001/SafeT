import copy
import unittest
from itertools import product
from ai.assessment_authoring.contracts import read, load_catalog
from ai.assessment_authoring.analysis_validator import validate_analysis
from ai.assessment_authoring.assessment_composer import compose_assessment, render_assessment
from ai.assessment_authoring.retrieval_adapter import retrieve_evidence, retrieve_with_evidence, candidate_batches
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
                    self.assertIn("FRY", [c["scenario_id"] for c in batch["candidates"]])
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
        ]
        for kind, (observation, rows, pending, excluded) in product(("text", "voice_transcript"), cases):
            with self.subTest(kind=kind, observation=observation):
                context = read("examples/input_variants/photo.json")
                context["media"].append(dict(id="WORK", kind=kind, text=observation))
                extracted = []
                def extract(_, batch, catalog):
                    extracted.append(True)
                    analysis = read("examples/unknown/analysis.json")
                    analysis["candidates"][0]["evidence"] = [dict(media_id="WORK", statement=observation)]
                    return analysis
                result = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=extract,
                                      catalog_snapshot=self.catalog)
                self.assertEqual([row["scenario_id"] for row in result["assessment"]["rows"]], rows)
                if excluded:
                    self.assertFalse(extracted)
                self.assertEqual(result["retrieval_trace"]["work_review_candidates"], pending)
                self.assertEqual(result["retrieval_trace"]["not_applicable_candidates"], excluded)
                self.assertEqual(result["assessment"]["core"]["review_candidates"],
                                 [{"scenario_id": sid, "reason": "work_unconfirmed"} for sid in pending]
                                 + [{"scenario_id": sid, "reason": "input_denies_work"} for sid in excluded])

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

