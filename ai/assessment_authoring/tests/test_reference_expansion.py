import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from ai.assessment_authoring.reference_expansion import expand
from ai.assessment_authoring.document_evidence import evidence_by_scenario
from ai.assessment_authoring.explanations import document_summaries

class ReferenceExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.rows=[dict(doc_id=d,hazard_code=h,pdf_pages=[p],source_id=d,source_file=d+'.pdf',review_status='pdf_verified',hazard_text='합성 위험 '+d,prevention_text='합성 예방 '+d) for d,h,p in [('N02','burn',12),('N08','slip',7)]]
        self.response=dict(candidates=[dict(equipment_ids=['EQ_FRYER'],hazard_code=h,source_ids=['OLD'],hazard_texts=['기존 위험']) for h in ['burn','slip','gas']])
        self.write()
    def write(self):
        raw=json.dumps(self.rows).encode();(self.root/'contexts.json').write_bytes(raw)
        (self.root/'manifest.json').write_text(json.dumps(dict(version='N02-N08-context-1',file='contexts.json',sha256=hashlib.sha256(raw).hexdigest())))
    def test_preserves_old_index_and_maps_only_reviewed_hazards(self):
        original=copy.deepcopy(self.response);out=expand(self.response,self.root)
        self.assertEqual(self.response,original)
        self.assertEqual(out['candidates'][0]['source_ids'],['OLD','N02'])
        self.assertEqual(out['candidates'][1]['source_ids'],['OLD','N08'])
        self.assertEqual(out['candidates'][2],original['candidates'][2])
        docs=evidence_by_scenario(out,{'EQ_FRYER:burn':['FRY'],'EQ_FRYER:slip':['ENV']},['FRY','ENV'],['EQ_FRYER'])
        summary=document_summaries(docs['FRY'])[0]
        self.assertEqual(summary['prevention_summary'],'합성 예방 N02')
        self.assertEqual(summary['pdf_pages'],[12])
    def test_corrupt_file_rejected(self):
        (self.root/'contexts.json').write_text('[]')
        with self.assertRaises(ValueError):expand(self.response,self.root)
    def test_hood_fall_page_cannot_be_slip_evidence(self):
        self.rows[1]['pdf_pages']=[21];self.write()
        with self.assertRaises(ValueError):expand(self.response,self.root)
    def test_optional_expansion_off_retains_original_behavior(self):
        self.assertEqual(expand(self.response,None),self.response)

    def test_unused_fryer_does_not_match_but_knife_work_does(self):
        from ai.assessment_authoring.contracts import load_catalog
        from ai.assessment_authoring.retrieval_adapter import retrieve_with_evidence
        context=dict(contract_version='assessment-authoring-1',catalog_version='CATALOG-MVP-1.1',equipment_ids=[],media=[dict(id='TEXT',kind='text',text='튀김기는 사용하지 않습니다. 칼로 채소를 자릅니다.')])
        bundle,trace=retrieve_with_evidence(context,load_catalog())
        self.assertEqual([c['scenario_id'] for c in bundle['candidates']],['KNIFE'])
        self.assertEqual(trace['scenario_evidence'],{'KNIFE':[]})
