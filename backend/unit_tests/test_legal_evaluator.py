import json
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ai/legal_review"))
from evaluator import CHECKS, legal_groundedness_v1


class GroundednessTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{"chunk_id": "A1", "law": "검수 법령", "locator": "제3조제1항", "text": "바닥을 안전하고 청결하게 유지한다."}]
        self.answer = {"status": "answered", "evidence": [{"chunk": "A1", "law": "검수 법령",
            "locator": "제3조제1항", "quotation": "바닥을 안전하고 청결하게 유지한다."}]}

    def invoke(self, messages):
        inputs = json.loads(messages[1]["content"])
        self.assertEqual(inputs["context"], self.sources)
        return {"model": "검수 모델", "choices": [{"message": {"content": json.dumps({
            "checks": {key: True for key in CHECKS}, "reason": "바닥 청결에 관한 검색 원문과 인용문이 서로 일치합니다."})}}]}

    def test_valid_evidence(self):
        result = legal_groundedness_v1("바닥 위험", self.sources, self.answer, self.invoke)
        self.assertEqual(result["score"], 1)

    def test_unknown_id_overrides_judge(self):
        self.answer["evidence"][0]["chunk"] = "없는 청크"
        result = legal_groundedness_v1("바닥 위험", self.sources, self.answer, self.invoke)
        self.assertEqual(result["score"], 0)

    def test_manual_citation_overrides_judge(self):
        self.answer["status"] = "manual_review"
        self.assertEqual(legal_groundedness_v1("바닥 위험", self.sources, self.answer, self.invoke)["score"], 0)

    def test_invalid_judge_is_not_a_score(self):
        with self.assertRaises(ValueError):
            legal_groundedness_v1("바닥 위험", self.sources, self.answer,
                lambda _: {"choices": [{"message": {"content": "{}"}}]})

    def test_complete_local_trace(self):
        import worker
        source = {"chunk_id": "A1", "law": "산업안전보건기준에 관한 규칙", "locator": "제3조제1항",
            "text": "사업주는 근로자가 미끄러지는 등의 위험이 없도록 작업장 바닥 등을 안전하고 청결하게 유지하여야 한다."}
        completion = {"id": "fixture-generation", "model": "fixture", "choices": [{"message": {
            "content": json.dumps({"evidence": [{"chunk": "A1"}]})}}]}
        judged = {"id": "fixture-judge", "model": "fixture", "choices": [{"message": {"content": json.dumps({
            "checks": {key: True for key in CHECKS}, "reason": "검색된 바닥 관리 원문과 인용한 근거가 일치합니다."})}}]}
        with TemporaryDirectory() as folder, patch.dict('os.environ', {
                'LANGSMITH_TRACING': 'false', 'SAFET_LEGAL_EVALUATOR_ENABLED': 'true',
                'SAFET_LEGAL_TRACE_DIR': folder}), patch.object(worker, 'candidates', return_value=[source]), \
                patch.object(worker, 'generate', return_value=completion), \
                patch.object(worker, 'request_completion', return_value=judged):
            answer = worker.evaluate(None, None, None, '주방 바닥에서 발을 헛디뎠다.')
            trace = json.loads(next(Path(folder).glob('*.json')).read_text(encoding='utf8'))
            root = trace['steps'][0]
            self.assertEqual(len(trace['steps']), 6)
            self.assertEqual(root['inputs']['question'], '주방 바닥에서 발을 헛디뎠다.')
            self.assertEqual(root['outputs']['source_documents'], [source])
            self.assertEqual(root['outputs']['answer'], answer)
            self.assertEqual(root['outputs']['evaluation']['score'], 1)


if __name__ == "__main__":
    unittest.main()
