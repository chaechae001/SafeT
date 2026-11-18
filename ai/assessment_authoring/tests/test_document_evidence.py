import copy
import json
import unittest
from ai.assessment_authoring.contracts import load_catalog, read
from ai.assessment_authoring.pipeline import run_pipeline
from ai.assessment_authoring.retrieval_adapter import retrieve_evidence
from ai.assessment_authoring.live_text_check import build_messages

class DocumentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.i = read("examples/unknown/input.json")
        self.i["equipment_ids"] = ["EQ_FRYER"]
        self.a = read("examples/unknown/analysis.json")
        self.response = dict(enabled=True, data_version="SYNTHETIC", index_sha256="test",
            candidates=[dict(equipment_ids=["EQ_FRYER"], hazard_code="synthetic_burn",
                             hazard_texts=["합성 문헌: 뜨거운 기름 접촉 시 화상 위험"],
                             source_ids=["SYNTHETIC-DOC-A","SYNTHETIC-DOC-B"])])
        self.links = {"EQ_FRYER:synthetic_burn":["FRY"]}

    def run_case(self, callback):
        return run_pipeline(self.i, build_context=copy.deepcopy, extract_analysis=lambda *args:self.a,
                            catalog_snapshot=self.catalog, rag_provider=lambda *args,**kw:self.response,
                            rag_links=self.links, extract_with_evidence=callback)

    def test_evidence_reaches_model_and_final_row_unchanged(self):
        captured = {}
        def extract(i,r,c,evidence):
            messages=build_messages(i,r,c,evidence)
            captured.update(json.loads(messages[-1]["content"])["reference_documents"])
            return copy.deepcopy(self.a)
        out=self.run_case(extract)
        self.assertEqual(captured["FRY"],out["assessment"]["rows"][0]["document_evidence"])
        self.assertEqual(captured["FRY"][0]["source_ids"],["SYNTHETIC-DOC-A","SYNTHETIC-DOC-B"])
        self.assertEqual(captured["FRY"][0]["provenance_granularity"],"hazard_group")
        self.assertEqual(out["assessment"]["core"]["items"][0]["grade"],"상")
        self.assertTrue(all(e["state"]=="unknown" for e in out["analysis"]["candidates"][0]["control_evidence"]))

    def test_document_id_cannot_be_field_evidence(self):
        def extract(i,r,c,evidence):
            a=copy.deepcopy(self.a)
            a["candidates"][0]["control_evidence"]=[dict(control_id="FRY-C1",state="supported",
                statement="합성 문헌",evidence_refs=[evidence["FRY"][0]["evidence_id"]])]
            return a
        with self.assertRaises(ValueError):self.run_case(extract)

    def test_disabled_is_not_valid_empty_search(self):
        self.response.update(enabled=False,candidates=[])
        with self.assertRaisesRegex(ValueError,"disabled"):
            retrieve_evidence(self.i,self.catalog,rag_provider=lambda *args,**kw:self.response)

    def test_unmapped_evidence_is_not_attached(self):
        self.links={}
        out=self.run_case(lambda *args:copy.deepcopy(self.a))
        self.assertEqual(out["assessment"]["rows"][0]["document_evidence"],[])
        self.assertEqual(out["assessment"]["core"]["result_status"],"complete")
        self.assertTrue(any("RAG 시나리오 매핑 없음" in d for d in out["retrieval_trace"]["diagnostics"]))

    def test_evaluation_case_source_rejected(self):
        self.response["candidates"][0]["source_ids"]=["CASE-TEST"]
        with self.assertRaises(ValueError):self.run_case(lambda *args:copy.deepcopy(self.a))

    def test_callback_mutation_cannot_change_final_source(self):
        def extract(i,r,c,evidence):
            evidence["FRY"][0]["source_ids"]=["FAKE"]
            return copy.deepcopy(self.a)
        out=self.run_case(extract)
        self.assertNotIn("FAKE",str(out["assessment"]["rows"][0]["document_evidence"]))

if __name__=="__main__":unittest.main()
