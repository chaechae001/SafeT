"""C 법령 인덱스(KURE) 재사용 조건과 위험도 시나리오 정책 선택. 모델·torch 없이 검사한다."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


def fake_engine(quote):
    unit = dict(id="law:1@20260101:a1:p1", law_name="산업안전보건기준에 관한 규칙", doc_no=1, article="제1조",
                locator="제1조 제1항", article_title="목적", quote=quote)
    return SimpleNamespace(units=[unit], law_pos=[0], as_of="2026-11-21")


class LawIndexTest(unittest.TestCase):
    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy 없음")

    def write_index(self, engine, *, legacy=False):
        import numpy as np
        from ai.risk_law_search.law_kure import MODEL, content_hash, current_rows
        d = Path(tempfile.mkdtemp())
        rows = current_rows(engine)
        np.save(d / "vectors.npy", np.ones((len(rows), 2), dtype="float32"))
        (d / "chunks.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        meta = dict(model=MODEL, chunks=len(rows), as_of=engine.as_of)
        if not legacy:
            meta["content_sha256"] = content_hash(rows)
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return d

    def test_same_ids_changed_body_rejects_old_index(self):
        from ai.risk_law_search.law_kure import KureLawFinder
        d = self.write_index(fake_engine("사업주는 보호구를 지급해야 한다."))
        KureLawFinder(fake_engine("사업주는 보호구를 지급해야 한다."), d, encoder=object())  # 같은 본문 → 사용
        with self.assertRaises(ValueError) as e:  # 조문 번호·시행일(ID) 같고 본문만 바뀜
            KureLawFinder(fake_engine("사업주는 보호구를 지급하고 착용하게 해야 한다."), d, encoder=object())
        self.assertIn("다시 만드세요", str(e.exception))
        self.assertIn("본문", str(e.exception))

    def test_legacy_index_without_hash_is_checked_by_body(self):
        from ai.risk_law_search.law_kure import KureLawFinder
        d = self.write_index(fake_engine("원문"), legacy=True)
        KureLawFinder(fake_engine("원문"), d, encoder=object())
        with self.assertRaises(ValueError):
            KureLawFinder(fake_engine("바뀐 원문"), d, encoder=object())


class ScenarioPolicyTest(unittest.TestCase):
    def test_module_uses_service_catalog_file(self):
        """내부 검토 화면·검색 모듈은 서비스 DB에 적재하는 1.2 카탈로그 파일을 그대로 쓴다."""
        from backend.domain.risk_policy import ACTIVE_POLICY
        from ai.risk_law_search.scenario_map import load_catalog
        base = load_catalog()
        raw = json.loads((Path(__file__).resolve().parents[3] / "contracts/catalog_risk/catalog-food-3level-1.2.json").read_text(encoding="utf-8"))
        self.assertEqual({s["policy_version"] for s in base["scenarios"]}, {ACTIVE_POLICY})
        self.assertEqual(base["scenarios"], raw["scenarios"])


if __name__ == "__main__":
    unittest.main()
