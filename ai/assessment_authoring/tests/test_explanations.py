import copy
import unittest
from ai.assessment_authoring.explanations import rationale, document_summaries, control_details

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
        scenario=dict(title='합성 위험',task='합성 작업',controls=[dict(id='X',current_text='합성 방호조치',critical=True)])
        candidate=dict(evidence=[dict(statement='합성 작업')],control_evidence=[dict(control_id='X',state='unknown')])
        text=rationale(candidate,scenario,dict(control_band=3,grade='상'),[])
        self.assertIn('“합성 작업” 작업을 확인',text)
        self.assertIn('합성 방호조치의 실시 여부',text)
        self.assertIn('‘상’',text)
        candidate['control_evidence'][0]['state']='supported'
        text=rationale(candidate,scenario,dict(control_band=1,grade='하'),[])
        self.assertIn('실시가 확인된 조치는 합성 방호조치',text)
        self.assertIn('모든 기준 조치',text);self.assertNotIn('미확인은',text)
        candidate['control_evidence'][0]['state']='not_effective'
        text=rationale(candidate,scenario,dict(control_band=3,grade='상'),[])
        self.assertIn('고장·미실시 또는 효과 부족이 확인',text)

    def test_rationale_excludes_document_text(self):
        # 문헌 위험 설명·예방대책은 문헌 근거 영역에만 표시하고 판단 이유에 반복하지 않는다.
        c=dict(evidence=[dict(statement='조리를 합니다.')],control_evidence=[])
        s=dict(title='합성 위험',task='합성 조리',controls=[])
        text=rationale(c,s,dict(control_band=1,grade='중'),[dict(hazard_texts=['합성 문헌 위험'])])
        self.assertNotIn('합성 문헌 위험',text);self.assertNotIn('문헌',text)
        self.assertIn('“조리를 합니다.”',text);self.assertIn('‘중’',text)

    def test_control_details_attach_quotes_only_to_stated_controls(self):
        s=dict(controls=[dict(id='A',current_text='충분한 냉각 후 배유',critical=True),
                         dict(id='B',current_text='온도 제어',critical=True),
                         dict(id='C',current_text='환기',critical=False)])
        c=dict(control_evidence=[
            dict(control_id='A',state='supported',evidence_refs=['TEXT'],statement='기름은 충분히 식힌 후 배유합니다.'),
            dict(control_id='B',state='not_effective',evidence_refs=['TEXT'],statement='온도조절 장치가 고장났습니다.'),
            dict(control_id='C',state='unknown',evidence_refs=[],statement='입력에서 확인되지 않음')])
        rows={r['control_id']:r for r in control_details(c,s)}
        self.assertEqual(rows['A']['statement'],'기름은 충분히 식힌 후 배유합니다.')
        self.assertEqual((rows['B']['state'],rows['B']['statement']),('not_effective','온도조절 장치가 고장났습니다.'))
        self.assertEqual((rows['C']['state'],rows['C']['statement']),('unknown',''))
        self.assertEqual([r['control_id'] for r in control_details(dict(control_evidence=[]),s)],['A','B','C'])
