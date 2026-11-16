import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from ai.risk_rules.engine import evaluate_case

CASES = json.loads((Path(__file__).parents[1] / 'examples.json').read_text(encoding='utf-8'))

class RiskRulesTests(unittest.TestCase):
    def case(self, number=0): return copy.deepcopy(CASES[number])
    def test_synthetic_regression(self):
        for case in CASES:
            with self.subTest(case=case['case_id']):
                result = evaluate_case(case)
                self.assertEqual(case['expected'], {k:result[k]['grade'] for k in ('current','projected')})
    def test_does_not_mutate_input(self):
        case=self.case(); original=copy.deepcopy(case); evaluate_case(case)
        self.assertEqual(case,original)
    def test_known_severe_not_hidden_by_missing(self):
        case=self.case(); case['current']['facts']=[]; case['current']['complete']=False
        r=evaluate_case(case)['current']; self.assertEqual(r['grade'],'R'); self.assertTrue(r['missing_information'])
    def test_string_boolean_rejected(self):
        for key in ('complete','severe_residual','treatment_residual','unresolved_near_miss'):
            case=self.case(); case['current'][key]='false'
            with self.subTest(key=key), self.assertRaises(ValueError): evaluate_case(case)
    def test_bad_enum_rejected(self):
        for key in ('controls','legal_status'):
            case=self.case(); case['current'][key]='yes'
            with self.subTest(key=key), self.assertRaises(ValueError): evaluate_case(case)
    def test_missing_field_rejected(self):
        case=self.case(); del case['current']['controls']
        with self.assertRaises(ValueError): evaluate_case(case)
    def test_unknown_field_rejected(self):
        case=self.case(); case['current']['score']=1
        with self.assertRaises(ValueError): evaluate_case(case)
    def test_plan_needs_all_evidence(self):
        for key in ('measures','assumptions','verification_steps','effect_reason'):
            case=self.case(); case['projection'][key]='' if key=='effect_reason' else []
            with self.subTest(key=key): self.assertEqual(evaluate_case(case)['projected']['grade'],'N')
    def test_unreviewed_effect_blocks_projection(self):
        case=self.case(); case['projection']['effect_reviewed']=False
        self.assertEqual(evaluate_case(case)['projected']['grade'],'N')
    def test_removed_flag_requires_link(self):
        case=self.case(); case['projection']['addressed_flags']=[]
        self.assertEqual(evaluate_case(case)['projected']['grade'],'N')
    def test_more_measures_do_not_reduce_grade(self):
        case=self.case(1); case['projection']['measures']=['보호구 추가']*20
        self.assertEqual(evaluate_case(case)['projected']['grade'],'R')
    def test_projection_never_actual_or_approved(self):
        result=evaluate_case(self.case(2))
        self.assertFalse(result['projected']['is_actual_result'])
        self.assertIsNone(result['acceptable_after_execution'])
        self.assertTrue(result['current']['requires_human_review'])
    def test_trace_hashes_deterministic(self):
        case=self.case(); a=evaluate_case(case); b=evaluate_case(case)
        self.assertEqual(a,b)
        case['current']['facts'].append('새 관찰'); c=evaluate_case(case)
        self.assertNotEqual(a['input_sha256'],c['input_sha256'])
        self.assertEqual(a['engine_sha256'],c['engine_sha256'])
    def test_cli_mismatch_fails(self):
        case=self.case(); case['expected']['current']='G'
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'cases.json'; path.write_text(json.dumps([case]),encoding='utf-8')
            run=subprocess.run([sys.executable,'-m','ai.risk_rules','--cases',str(path),'--check','--json'],capture_output=True,text=True)
        self.assertEqual(run.returncode,1); self.assertTrue(json.loads(run.stdout)['check_failures'])
    def test_cli_missing_id_fails(self):
        run=subprocess.run([sys.executable,'-m','ai.risk_rules','--case-id','missing'],capture_output=True,text=True)
        self.assertEqual(run.returncode,2)

if __name__=='__main__': unittest.main()
