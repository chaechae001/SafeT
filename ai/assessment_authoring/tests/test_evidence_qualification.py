import unittest
from ai.assessment_authoring.evidence_qualification import qualify_direct_evidence
from ai.assessment_authoring.document_evidence import evidence_by_scenario

class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.response={"candidates":[{"equipment_ids":["EQ_FRYER"],"hazard_code":"burn",
          "source_ids":["S-A","S-B"],"hazard_texts":["합성 튀김기 위험","합성 다른 기기 점검"],"measures":[]}]}
        self.rows=[
          dict(equipment_id="EQ_FRYER",standard_name="튀김기",hazard_code="burn",evidence_tier="A",
               equipment_match={"where":"위험요인 문장"},hazard_text="합성 튀김기 위험",source_id="S-A",
               source_file="synthetic.pdf",pdf_pages=[1],link_id="TEST-A"),
          dict(equipment_id="EQ_FRYER",standard_name="튀김기",hazard_code="burn",evidence_tier="B",
               equipment_match={"where":"작업명·섹션명·점검질문"},hazard_text="합성 다른 기기 점검",source_id="S-B",
               source_file="synthetic.pdf",pdf_pages=[2],link_id="TEST-B")]

    def test_section_only_contamination_is_removed_with_audit(self):
        cleaned, excluded=qualify_direct_evidence(self.response,self.rows)
        self.assertEqual(cleaned["candidates"][0]["source_ids"],["S-A"])
        self.assertEqual(cleaned["candidates"][0]["hazard_texts"],["합성 튀김기 위험"])
        self.assertEqual(excluded,[dict(link_id="TEST-B",reason="기기 직접 언급 근거 아님")])
        self.assertEqual(len(self.response["candidates"][0]["source_ids"]),2)

    def test_exact_link_provenance_survives(self):
        cleaned,_=qualify_direct_evidence(self.response,self.rows)
        ev=evidence_by_scenario(cleaned,{"EQ_FRYER:burn":["FRY"]},["FRY"],["EQ_FRYER"])["FRY"][0]
        self.assertEqual(ev["provenance_granularity"],"source_link_row")
        self.assertEqual(ev["source_evidence"][0]["pdf_pages"],[1])
        self.assertEqual(ev["source_evidence"][0]["link_id"],"TEST-A")

    def test_source_not_in_search_is_rejected(self):
        self.rows[0]["source_id"]="INVENTED"
        with self.assertRaises(ValueError):qualify_direct_evidence(self.response,self.rows)

    def test_detail_text_mismatch_is_rejected(self):
        cleaned,_=qualify_direct_evidence(self.response,self.rows)
        cleaned["candidates"][0]["source_evidence"][0]["hazard_text"]="INVENTED"
        with self.assertRaises(ValueError):
            evidence_by_scenario(cleaned,{"EQ_FRYER:burn":["FRY"]},["FRY"],["EQ_FRYER"])

if __name__=="__main__":unittest.main()

