"""혼합(e5 임베딩 + 키워드) 방식 검사. 로컬 모델로 CPU 임베딩을 한다(외부 API 호출 없음).

sentence-transformers·langchain-chroma가 없거나 모델을 불러올 수 없으면 건너뛴다.
처음 실행하면 Chroma 색인을 만든다(CPU 약 3분). 이후에는 ai/risk_law_search/.index를 재사용한다.
"""
import importlib.util
import os
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "docs" / "chroma"
READY = all(importlib.util.find_spec(m) for m in ("sentence_transformers", "langchain_chroma", "numpy", "kiwipiepy"))
ENGINE = None


def engine():
    global ENGINE
    if ENGINE is None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from ai.risk_law_search.engine import Engine
        ENGINE = Engine(DATA, as_of="2026-11-19", mode="hybrid", log=lambda m: None)
    return ENGINE


def top_locators(result):
    return [(l["doc_no"], l["locator"]) for l in result["laws"]]


@unittest.skipUnless(READY and (DATA / "risk_card_data.md").exists(), "임베딩 패키지 또는 docs/chroma 자료 없음")
class HybridTest(unittest.TestCase):
    def test_model_and_store_are_reported(self):
        h = engine().health()
        self.assertEqual(h["mode"], "hybrid")
        self.assertEqual(h["model"]["store"], "langchain_chroma")
        self.assertIn("e5", h["model"]["model"])

    def test_semantic_card_search_finds_paraphrase(self):
        r = engine().search("차량과 부딪힘")
        self.assertTrue({c["id"] for c in r["cards"][:3]} & {"EDU-C4", "FOOD-02-C1", "FOOD-01-C2"})
        self.assertIsNotNone(r["cards"][0]["score_detail"]["semantic"])

    def test_law_ranking_examples(self):
        cases = {"덤웨이터": ("02", "제86조제6항"), "바닥 물기 미끄러짐": ("02", "제3조제1항"),
                 "식품 가공 기계에 손이 말려 들어감": ("02", "제130조제1항"), "냉동고 갇힘": ("02", "제632조")}
        for q, (doc, loc) in cases.items():
            with self.subTest(q=q):
                first = top_locators(engine().search(q))[0]
                self.assertEqual(first[0], doc)
                self.assertTrue(first[1].startswith(loc))

    def test_model_only_matches_are_not_accepted_as_laws(self):
        r = engine().search("칼로 채소 썰기")
        self.assertTrue(r["cards"])
        self.assertTrue(all(l["score_detail"]["keyword"] >= 0.08 for l in r["laws"]))

    def test_stop_at_first_document_with_relevant_law(self):
        r = engine().search("가스통 보관")
        hits = [t["doc_no"] for t in r["law_trail"] if t["status"].startswith("관련 조문 ") and t["status"] != "관련 조문 없음"]
        self.assertEqual(len(hits), 1)
        self.assertTrue(all(l["doc_no"] == hits[0] for l in r["laws"]))

    def test_every_card_link_keeps_keyword_overlap(self):
        e = engine()
        self.assertIn("제32조제1항", [e.unit_by_id[x["unit_id"]]["locator"] for x in e.links["FOOD-01-H4"]["nearest"]])
        self.assertTrue(all(x["keyword"] >= 0.2 for v in e.links.values() for x in v["nearest"]))

    def test_analyze_platform_input(self):
        r = engine().analyze("주방에서 튀김기로 닭을 튀깁니다. 바닥에 기름이 묻어 미끄럽습니다.\n야채를 썰어요.",
                             "오토바이로 배달도 나가요.", [{"machine_code": "M3", "machine_nm": "덤웨이터"}], photos=1)
        units = {u["text"]: u for u in r["units"]}
        self.assertEqual(len(units), 5)
        for u in r["units"]:
            self.assertTrue(1 <= len(u["risks"]) <= 3)
        slip = units["바닥에 기름이 묻어 미끄럽습니다."]["risks"][0]
        self.assertEqual(slip["law"]["locator"], "제3조제1항")
        self.assertIn(units["덤웨이터"]["risks"][0]["law"]["locator"], ("제86조제6항",))
        self.assertTrue(r["warnings"])

    def test_meaningless_input_is_low_confidence_not_ok(self):
        for q in ("ㅁㄴㅇㄹ 아무말", "오늘 날씨가 좋네요", "회의를 합니다"):
            with self.subTest(q=q):
                u = engine().analyze(q)["units"][0]
                self.assertEqual(u["status"], "low_confidence")
                self.assertEqual(len(u["risks"]), 1)
                self.assertTrue(u["risks"][0]["low_confidence"])

    def test_korean_morphemes_match_inflected_forms(self):
        tok = engine().tokenizer
        self.assertEqual(tok.name, "kiwi")
        self.assertIn("v:썰", set(tok("야채를 썰어요")) & set(tok("재료 썰기 작업")))
        self.assertIn("v:넘어지", set(tok("미끄러지거나 넘어짐")) & set(tok("작업장에서 넘어지거나")))

    def test_section_text_does_not_outrank_card_hazard(self):
        # 식재료 전처리 구역 공통 문구('야채 절단')가 제면기 카드를 1위로 올리던 문제
        knife = {"FOOD-09-C1", "FOOD-09-H1", "FOOD-09-H2", "OPS-11-C1", "OPS-04-H2", "EDU-C2", "EDU-H08"}
        r = engine().search("야채를 썰어요")
        ids = [c["id"] for c in r["cards"]]
        self.assertIn(ids[0], knife)
        self.assertTrue(set(ids[:3]) <= knife)
        self.assertNotIn("OPS-04-H3", ids[:3])
        from ai.risk_law_search.cards import card_search_text
        self.assertNotIn("야채 절단", card_search_text(engine().card_by_id["OPS-04-H3"]))


if __name__ == "__main__":
    unittest.main()
