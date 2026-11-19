import copy
import unittest
from ai.assessment_authoring.explanations import rationale, document_summaries

class ExplanationTests(unittest.TestCase):
    def test_groups_spacing_duplicates_without_losing_provenance(self):
        docs=[dict(source_evidence=[dict(source_file='synthetic.pdf',hazard_text=t,source_id=s,link_id=s,pdf_pages=[p])
              for t,s,p in [('합성 바닥 위험','S1',1),('합성 바닥위험','S2',2)]])]
        before=copy.deepcopy(docs); groups=document_summaries(docs)
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['summary'],'문헌에서 제시한 위험: 합성 바닥 위험')
        self.assertEqual(groups[0]['source_ids'],['S1','S2'])
        self.assertEqual(groups[0]['pdf_pages'],[1,2]);self.assertEqual(docs,before)

    def test_unknown_and_confirmed_states_explain_different_decisions(self):
        scenario=dict(title='합성 위험',controls=[dict(id='X',current_text='합성 방호조치',critical=True)])
        candidate=dict(evidence=[dict(statement='합성 작업')],control_evidence=[dict(control_id='X',state='unknown')])
        text=rationale(candidate,scenario,dict(control_band=3,grade='상'),[])
        self.assertIn('직접 연결된 검색 문헌은 없습니다',text)
        self.assertIn('합성 방호조치의 실시 여부',text)
        self.assertIn('‘상’',text)
        candidate['control_evidence'][0]['state']='supported'
        text=rationale(candidate,scenario,dict(control_band=1,grade='하'),[])
        self.assertIn('모든 기준 조치',text);self.assertNotIn('미확인은',text)
        candidate['control_evidence'][0]['state']='not_effective'
        text=rationale(candidate,scenario,dict(control_band=3,grade='상'),[])
        self.assertIn('미실시 또는 효과 부족이 확인',text)

    def test_document_is_candidate_evidence_not_observed_condition(self):
        c=dict(evidence=[dict(statement='조리를 합니다')],control_evidence=[])
        s=dict(title='합성 위험',controls=[])
        text=rationale(c,s,dict(control_band=1,grade='중'),[dict(hazard_texts=['합성 문헌 위험'])])
        self.assertIn('문헌에 제시된',text);self.assertIn('후보에 포함',text)
        self.assertNotIn('직접 연결된 검색 문헌은 없습니다',text)
