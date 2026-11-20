"""9개 문서 검색과 우선순위, 기존 자동 인용 경계를 함께 확인한다."""
import json
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ai/legal_review"))
from rules import review
from worker import candidates, open_index


class FullCorpusTests(unittest.TestCase):
    def search(self, distances):
        def query(**kwargs):
            priority = kwargs["where"]["$and"][0]["priority"]
            self.assertEqual(kwargs["where"]["$and"][1], {"deleted": False})
            meta = dict(section="제1조", law=f"법령{priority}", part="본문",
                        chunk_id=f"D{priority}", source_file=f"{priority}.hwpx", source_sha256="source")
            return dict(distances=[[distances[priority-1]]], documents=[["검색 원문"]], metadatas=[[meta]])

        db = MagicMock()
        db.query.side_effect = query
        model = MagicMock()
        model.return_value.last_hidden_state = torch.ones(1, 1, 2)
        result = candidates(db, lambda *args, **kwargs: {}, model, "질문")
        self.assertEqual(db.query.call_count, 9)
        return result

    def test_priority_breaks_near_ties(self):
        self.assertEqual([r["priority"] for r in self.search([0.2]*9)], list(range(1, 7)))

    def test_relevance_can_put_last_law_first(self):
        self.assertEqual(self.search([0.5]*8 + [0.1])[0]["priority"], 9)

    def test_new_law_is_a_traceable_review_candidate(self):
        rows = self.search([0.2]*9)
        result = review("새로운 주제", rows, {"selection": {"citations": [{"chunk": "D1"}, {"chunk": "없는 ID"}]}})
        self.assertEqual(result["status"], "manual_review")
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["review_candidates"], rows[:1])

    def test_index_checks_inventory_even_if_count_matches(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            manifest = [dict(priority=i, chunks=1) for i in range(1, 10)]
            rows = [dict(chunk_id=f"D{i}", source_sha256="expected") for i in range(1, 10)]
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf8")
            (folder / "chunks.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows), encoding="utf8")
            database = MagicMock()
            database.count.return_value = len(rows)
            database.get.return_value = dict(ids=[r["chunk_id"] for r in rows], metadatas=rows)
            with patch("worker.chromadb.PersistentClient") as client:
                client.return_value.get_collection.return_value = database
                self.assertIs(open_index(folder), database)
                database.get.return_value["metadatas"] = [dict(rows[0], source_sha256="wrong"), *rows[1:]]
                with self.assertRaisesRegex(ValueError, "청크 ID"):
                    open_index(folder)
