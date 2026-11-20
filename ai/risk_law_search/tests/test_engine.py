"""docs/chroma 자료로 조회 모듈을 검사한다(키워드 방식). 모델·DB·네트워크(로컬 서버 제외) 호출 없음.
혼합(e5) 방식 검사는 test_hybrid.py에 있다.

  python -m unittest discover -s ai/risk_law_search/tests -t .
"""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from ai.risk_law_search.engine import Engine
from ai.risk_law_search.laws import doc_order
from ai.risk_law_search.server import make_handler

DATA = Path(__file__).resolve().parents[3] / "docs" / "chroma"
AS_OF = "2026-11-19"
ENGINE = None


def engine():
    global ENGINE
    if ENGINE is None:
        ENGINE = Engine(DATA, as_of=AS_OF, mode="keyword")
    return ENGINE


@unittest.skipUnless((DATA / "risk_card_data.md").exists() and list(DATA.glob("*.hwpx")), "docs/chroma 자료 없음")
class EngineTest(unittest.TestCase):
    def test_doc_order_uses_file_number(self):
        names = ["08_a.hwpx", "06-02_b.hwpx", "06_c.hwpx", "01_d.hwpx"]
        self.assertEqual(sorted(names, key=doc_order), ["01_d.hwpx", "06_c.hwpx", "06-02_b.hwpx", "08_a.hwpx"])
        self.assertEqual([d["doc_no"] for d in engine().docs], ["01", "02", "03", "04", "05", "06", "06-02", "07", "08"])

    def test_law_units_have_stable_unique_ids_and_dates(self):
        e = engine()
        ids = [u["id"] for u in e.units]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(d["effective_from"] and len(d["sha256"]) == 64 for d in e.docs))
        u = e.unit_by_id["law:02@20260302:art3:p1"]
        self.assertEqual((u["locator"], u["article_title"]), ("제3조제1항", "전도의 방지"))
        self.assertIn("미끄러지는", u["quote"])

    def test_future_versions_are_kept_but_not_searched(self):
        e = engine()
        future = [i for i, u in enumerate(e.units) if u["future_version"]]
        self.assertTrue(future)
        self.assertTrue(all(e.units[i]["effective_from"] > AS_OF for i in future))
        self.assertFalse(set(future) & e.law_allowed)

    def test_cards_keep_direct_and_supplemental_measures_apart(self):
        e = engine()
        self.assertEqual(len(e.cards), 116)
        self.assertTrue(all(m["from_known"] for c in e.cards for m in c["measures_extra"]))
        self.assertNotIn("reference", {c["kind"] for c in e.search_cards})
        self.assertEqual(e.card_by_id["FOOD-05-H1"]["raw"]["id"], "FOOD-05-H1")

    def test_keyword_finds_delivery_cards_and_stops_at_first_law_document(self):
        r = engine().search("오토바이 배달")
        self.assertIn("이륜차", r["expanded_terms"])
        self.assertTrue({c["id"] for c in r["cards"][:3]} & {"EDU-C4", "FOOD-01-H1", "EDU-H05"})
        hit_docs = [t["doc_no"] for t in r["law_trail"] if t["status"].startswith("관련 조문 ") and t["status"] != "관련 조문 없음"]
        self.assertEqual(len(hit_docs), 1)
        first = hit_docs[0]
        self.assertTrue(all(l["doc_no"] == first for l in r["laws"]))
        after = [t["status"] for t in r["law_trail"] if doc_order(t["doc_no"] + "_") > doc_order(first + "_")]
        self.assertTrue(after and all(s == "미검색" for s in after))
        self.assertEqual(r["law_next_start"], first)

    def test_continue_search_from_next_document(self):
        r = engine().search("오토바이 배달", law_start="02")
        self.assertTrue(all(doc_order(l["doc_no"] + "_") > (2, 0) for l in r["laws"]))
        self.assertTrue(all(t["status"] == "이전 검색" for t in r["law_trail"][:2]))

    def test_card_links_nearest_and_cited_laws(self):
        e = engine()
        nearest = [e.unit_by_id[x["unit_id"]]["locator"] for x in e.links["FOOD-01-H4"]["nearest"]]
        self.assertIn("제32조제1항", nearest)
        cited = e.links["FOOD-05-H1"]["card_cited"]
        self.assertTrue(cited and cited[0]["status"] == "조문 연결")
        self.assertTrue(all(":art3:" in i for i in cited[0]["unit_ids"]))
        self.assertEqual(e.links["FOOD-06-H1"]["card_cited"], [])
        # '도로교통법 시행규칙'은 보유한 '도로교통법'(법률)에 연결하지 않는다.
        rules = [x for x in e.links["FOOD-01-H1"]["card_cited"] if "시행규칙" in x["text"]]
        self.assertTrue(rules and all(x["status"] == "보유 법령 원문에 없음" for x in rules))

    def test_card_links_need_matching_risk_topic(self):
        e = engine()
        locs = lambda cid: [(e.unit_by_id[x["unit_id"]]["article_title"]) for x in e.links[cid]["nearest"]]
        # 식칼이 떨어짐(베임)은 사람의 추락이 아니다. 주제가 맞는 조문이 없으면 연결하지 않고 확인 필요로 둔다.
        self.assertNotIn("추락의 방지", locs("OPS-04-H2"))
        law, basis = e._one_law("OPS-04-H2")
        self.assertIsNone(law)
        self.assertIn("담당자 확인 필요", basis)
        # 칼 작업이 냉장실 등의 작업에 붙지 않는다.
        self.assertNotIn("냉장실 등의 작업", locs("OPS-11-C1"))
        # 사람이 떨어지는 카드는 그대로 추락의 방지에 연결된다.
        self.assertEqual(locs("FOOD-06-C1")[0], "추락의 방지")
        self.assertTrue(all(e.topic_ok(e.card_by_id[cid], e.units.index(e.unit_by_id[x["unit_id"]]))
                            for cid, v in e.links.items() for x in v["nearest"]))

    def test_falling_object_query_is_not_expanded_to_fall_from_height(self):
        r = engine().search("식칼이 떨어짐")
        self.assertNotIn("추락", r["expanded_terms"])
        self.assertNotIn("추락의 방지", [l["article_title"] for l in r["laws"]])
        self.assertIn("추락", engine().search("높은 곳에서 떨어짐")["expanded_terms"])

    def test_keyword_list_is_split_into_one_unit_per_word(self):
        e = engine()
        if not hasattr(e.tokenizer, "bare_noun"):
            self.skipTest("형태소 분석기(kiwipiepy) 없음")
        a = e.analyze("칼 튀김기 선반 바닥")
        self.assertEqual([u["text"] for u in a["units"]], ["칼", "튀김기", "선반", "바닥"])
        self.assertTrue(all(u["keyword"] and u["from_text"] == "칼 튀김기 선반 바닥" for u in a["units"]))
        cards = {u["text"]: [r["card_id"] for r in u["risks"]] for u in a["units"]}
        self.assertIn("FOOD-11-H3", cards["선반"])  # 선반 등으로 운반 시 불안전한 작업
        self.assertIn("FOOD-05-H2", cards["바닥"])  # 바닥에 물이 고이는 구조
        ids = [c for v in cards.values() for c in v]
        self.assertEqual(len(ids), len(set(ids)))  # 낱말 단위끼리 같은 카드를 겹쳐 내지 않는다
        # 조사·어미가 있는 문장은 나누지 않는다.
        self.assertEqual(len(e.split_units("바닥에 물기가 있어요")), 1)
        self.assertEqual([u["text"] for u in e.split_units("칼, 바닥")], ["칼", "바닥"])

    def test_listed_clauses_are_split_into_units(self):
        e = engine()
        if not hasattr(e.tokenizer, "clause_cuts"):
            self.skipTest("형태소 분석기(kiwipiepy) 없음")
        t = "칼로 재료를 손질하고 튀김기로 튀기고 선반에서 물건을 꺼내는데 바닥이 미끄러워요"
        a = e.analyze(t)
        self.assertEqual([u["text"] for u in a["units"]],
                         ["칼로 재료를 손질하고", "튀김기로 튀기고", "선반에서 물건을 꺼내는데", "바닥이 미끄러워요"])
        self.assertTrue(all(u["clause"] and u["from_text"] == t for u in a["units"]))
        cards = [r["card_id"] for u in a["units"] for r in u["risks"]]
        self.assertTrue({"FOOD-11-H3", "FOOD-05-H2"} <= set(cards))  # 선반·바닥 위험이 빠지지 않는다
        # 원인·순서로 이어진 한 사건('~다가')과 보조 용언('닦고 있어요')은 나누지 않는다.
        self.assertEqual(len(e.split_units("칼로 자르다가 칼이 미끄러졌어요")), 1)
        self.assertEqual([u["text"] for u in e.split_units("칼을 쓰며 바닥을 닦고 있어요")], ["칼을 쓰며", "바닥을 닦고 있어요"])

    def test_alt_law_path_is_added_without_changing_default(self):
        e = engine()
        before = e.analyze("식칼이 떨어짐")
        self.assertTrue(all("law_alt" not in r for u in before["units"] for r in u["risks"]))

        class Stub:  # B 경로 자리만 확인한다(KURE 모델 없이).
            def find(self, text, card):
                return dict(method="stub", text=text, card=card["id"], candidates=[])

            def info(self):
                return dict(method="stub")

        e.alt_law = Stub()
        try:
            after = e.analyze("식칼이 떨어짐")
            self.assertEqual(e.health()["alt_law"], {"method": "stub"})
        finally:
            e.alt_law = None
        for u0, u1 in zip(before["units"], after["units"]):
            for r0, r1 in zip(u0["risks"], u1["risks"]):
                self.assertEqual(r1["law_alt"], dict(method="stub", text=u1["text"], card=r1["card_id"], candidates=[]))
                self.assertEqual(r1["law_alt_topic"]["candidates"], [])
                self.assertIn("담당자 확인 필요", r1["law_alt_topic"]["note"])
                self.assertEqual({k: v for k, v in r1.items() if k not in ("law_alt", "law_alt_topic")}, r0)  # A 결과는 그대로

    def test_alt_topic_keeps_only_candidates_matching_risk_type(self):
        e = engine()
        card = e.card_by_id["OPS-04-H2"]  # [베임] 식칼
        view = lambda title: e.law_view(next(u["id"] for i, u in enumerate(e.units)
                                             if u["article_title"] == title and i in e.law_allowed))
        alt = dict(method="kure45", candidates=[view("와이어로프의 절단방법 등"), view("추락의 방지"), view("보호구의 지급 등")])
        r = e._alt_topic(alt, card)
        self.assertEqual([x["article_title"] for x in r["candidates"]], ["보호구의 지급 등"])
        self.assertEqual(r["dropped"], 2)

    def test_c_skips_generic_and_other_cause_articles(self):
        e = engine()
        card = e.card_by_id["FOOD-04-C1"]  # [화재] 조리 작업 중 식용유에 착화되어 화재 발생
        view = lambda title: e.law_view(next(u["id"] for i, u in enumerate(e.units)
                                             if u["article_title"] == title and i in e.law_allowed))
        alt = dict(method="kure45", candidates=[view("정전기로 인한 화재 폭발 등 방지"),
                                                view("국가와 지방자치단체 등의 책무"),
                                                view("화재 위험이 있는 작업의 장소 등")])
        r = e._alt_topic(alt, card, "조리 중 식용유에 불이 붙었어요")
        self.assertEqual([x["article_title"] for x in r["candidates"]], ["화재 위험이 있는 작업의 장소 등"])
        self.assertEqual([x["reason"] for x in r["excluded"]], ["원인 불일치(정전기)", "일반 조항"])
        # 입력에 원인 낱말이 있으면 특정 원인 조문도 쓴다.
        r2 = e._alt_topic(alt, card, "정전기 불꽃으로 식용유에 불이 붙었어요")
        self.assertEqual(r2["candidates"][0]["article_title"], "정전기로 인한 화재 폭발 등 방지")

    def test_topic_policy_uses_c_and_keeps_a_for_comparison(self):
        e = engine()
        view = lambda title: e.law_view(next(u["id"] for i, u in enumerate(e.units)
                                             if u["article_title"] == title and i in e.law_allowed))

        class Stub:
            def find(self, text, card):
                return dict(method="stub", candidates=[view("와이어로프의 절단방법 등"), view("보호구의 지급 등")])

            def info(self):
                return dict(method="stub")

        before = e.analyze("식칼이 떨어짐")["units"][0]["risks"][0]
        e.alt_law, e.law_policy = Stub(), "topic_kure"
        try:
            r = e.analyze("식칼이 떨어짐")["units"][0]["risks"][0]
        finally:
            e.alt_law, e.law_policy = None, "card"
        self.assertEqual(r["card_id"], "OPS-04-H2")
        self.assertEqual(r["law"]["article_title"], "보호구의 지급 등")  # 베임 주제가 아닌 '와이어로프 절단'은 건너뜀
        self.assertEqual((r["law_card"], r["law_card_basis"]), (before["law"], before["law_basis"]))

    def test_risks_carry_scenario_for_risk_grading(self):
        from ai.risk_law_search.scenario_map import MAP, ScenarioLinker
        if not MAP.exists():
            self.skipTest("card_scenario_map.json 없음")
        e = engine()
        e.scenarios = ScenarioLinker()
        try:
            r = e.analyze("식칼이 떨어짐")["units"][0]["risks"][0]
        finally:
            e.scenarios = None
        s = r["scenario"]
        self.assertEqual((s["scenario_id"], s["status"], s["policy_version"]), ("KNIFE", "auto", "CATALOG-MVP-1.1"))
        self.assertIn("검토 전", s["message"])
        self.assertTrue(any(c["critical"] for c in s["controls"]))
        # 공통 계산 모듈이 이 형식을 그대로 받는다(등급 계산은 여기서 하지 않음).
        import importlib.util
        path = Path(__file__).resolve().parents[3] / "backend" / "domain" / "risk_policy.py"
        spec = importlib.util.spec_from_file_location("risk_policy", path)
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        critical = [c["id"] for c in s["controls"] if c["critical"]]
        self.assertEqual(policy.evaluate(s, [], answered=False)["signal"], "N")  # 확인 전은 판단 필요
        self.assertEqual(policy.evaluate(s, critical, answered=True)["status"], "calculated")

    def test_options_carry_control_links_and_analyze_writes_nothing(self):
        """서비스 연결: 추천 대책마다 기준 조치 연결을 붙이고, 분석은 위험도 기록 DB에 쓰지 않는다."""
        import os
        import tempfile
        from ai.risk_law_search.control_map import MAP as CMAP, ControlMapper
        from ai.risk_law_search.scenario_map import MAP, ScenarioLinker
        if not (MAP.exists() and CMAP.exists()):
            self.skipTest("연결표 없음")
        e = engine()
        e.scenarios, e.controls = ScenarioLinker(), ControlMapper()
        db = Path(tempfile.mkdtemp()) / "audit.sqlite3"
        old = os.environ.get("SAFET_RISK_AUDIT_DB")
        os.environ["SAFET_RISK_AUDIT_DB"] = str(db)
        try:
            r = e.analyze("튀김기에서 기름이 튀어요")["units"][0]["risks"][0]
        finally:
            e.scenarios = e.controls = None
            if old is None:
                os.environ.pop("SAFET_RISK_AUDIT_DB", None)
            else:
                os.environ["SAFET_RISK_AUDIT_DB"] = old
        self.assertFalse(db.exists())
        links = [o["control"] for o in r["current_options"] + r["improvement_options"]]
        self.assertEqual(len(links), 6)
        # 기본값: 검토 전 자동 연결은 위험도 계산용 ID를 내보내지 않는다.
        for c in links:
            if c["status"] != "confirmed":
                self.assertIsNone(c["control_id"])
        auto = ControlMapper(count_auto=True)
        k, v = next((k, v) for k, v in auto.links.items() if v.get("control_id"))
        sid, text = k.split("|", 1)
        self.assertEqual(auto.link(sid, text)["control_id"], v["control_id"])
        self.assertIsNone(ControlMapper().link(sid, text)["control_id"])

    def test_negation_is_flagged_not_hidden(self):
        r = engine().search("바닥에 물기가 없습니다")
        self.assertTrue(r["negation"]["found"])
        self.assertTrue(r["cards"])

    def test_platform_input_is_split_into_units(self):
        units = engine().split_units("튀김기로 조리합니다. 바닥에 물기가 있어요.\n사다리로 후드를 청소해요; 바닥에 물기가 있어요.",
                                     "오토바이로 배달해요", [{"machine_code": "M01", "machine_nm": "튀김기"}, "덤웨이터", ""])
        self.assertEqual([u["unit_id"] for u in units],
                         ["TEXT:1", "TEXT:2", "TEXT:3", "VOICE:1", "MACHINE:M01", "MACHINE:2"])
        self.assertTrue(all(u["note"] for u in units if u["source"] == "MACHINE"))

    def test_analyze_gives_at_most_three_risks_and_one_law_each(self):
        r = engine().analyze("바닥 물기 미끄러짐. 덤웨이터 탑승.", machines=["사다리"])
        self.assertEqual(r["summary"]["units"], 3)
        for u in r["units"]:
            self.assertLessEqual(len(u["risks"]), 3)
            for risk in u["risks"]:
                self.assertIn("law", risk)
                self.assertTrue(risk["law"] is None or isinstance(risk["law"], dict))
        self.assertTrue(all(u["risks"] for u in r["units"]))
        # 현재 조치 사항·개선 조치 사항은 항상 3개씩, 선택 안 된 상태, 두 목록에 같은 문장 없음, 출처 표시.
        e = engine()
        for u in r["units"]:
            for risk in u["risks"]:
                cur, imp = risk["current_options"], risk["improvement_options"]
                self.assertEqual((len(cur), len(imp)), (3, 3), risk["card_id"])
                texts = [o["text"] for o in cur + imp]
                self.assertEqual(len(set(texts)), 6)
                self.assertTrue(all(not o["selected"] and o["origin"] and o["origin_card"] for o in cur + imp))
                card = e.card_by_id[risk["card_id"]]
                import re as _re
                originals = [_re.sub(r"\s+", " ", t).strip() for t in card["measures"]]
                distinct = {e.actions[t] for t in originals}
                own = [o for o in cur if o["origin"] == "이 카드 직접 대책"]
                self.assertEqual(len(own), min(3, len(distinct)))  # 이 카드 직접 대책이 먼저 들어간다
                self.assertTrue({o["original"] for o in own} <= set(originals))
                self.assertTrue(all(o["text"] == e.actions[o["original"]] for o in cur + imp))

    def test_every_searchable_card_gets_three_and_three(self):
        e = engine()
        for c in e.search_cards:
            cur, imp = e.options(c, "")
            self.assertEqual((len(cur), len(imp)), (3, 3), c["id"])
            self.assertTrue(all(o["action_reviewed"] for o in cur + imp), c["id"])

    def test_measure_actions_are_short_methods(self):
        import re as _re
        e = engine()
        originals = {_re.sub(r"\s+", " ", t).strip() for c in e.cards
                     for t in c["measures"] + [m["text"] for m in c["measures_extra"]]}
        self.assertEqual(originals - set(e.actions), set())  # 모든 원문에 정리 문구가 있다
        for original, action in e.actions.items():
            self.assertTrue(0 < len(action) <= 32, action)
            self.assertFalse(action.endswith(("금지", "않음", "행위", "한다", "함")), action)
        self.assertEqual(e.actions["떨어지는 칼을 잡는 행위 금지"], "떨어지는 칼을 잡지 않도록 교육")
        with self.assertRaises(ValueError):
            engine().analyze("", "", [])

    def test_invalid_query(self):
        with self.assertRaises(ValueError):
            engine().search("  ")
        with self.assertRaises(ValueError):
            engine().search("가" * 501)

    def test_server_endpoints(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine()))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            def get(path):
                try:
                    with opener.open(base + path, timeout=10) as res:
                        return res.status, res.read()
                except urllib.error.HTTPError as err:
                    return err.code, err.read()
            status, body = get("/")
            self.assertEqual(status, 200)
            self.assertIn("위험·법령 분석".encode("utf-8"), body)
            status, body = get("/api/health")
            self.assertEqual((status, json.loads(body)["status"]), (200, "ok"))
            status, body = get("/api/search?q=%EB%8D%A4%EC%9B%A8%EC%9D%B4%ED%84%B0")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["cards"])
            self.assertEqual(get("/api/search?q=a&law_start=99")[0], 400)
            self.assertEqual(get("/api/search?q=")[0], 400)
            self.assertEqual(get("/api/card?id=NONE")[0], 404)
            status, body = get("/api/card?id=FOOD-01-H4")
            self.assertEqual((status, json.loads(body)["id"]), (200, "FOOD-01-H4"))

            def post(payload, raw=None):
                data = raw if raw is not None else json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(base + "/api/analyze", data=data, method="POST",
                                             headers={"Content-Type": "application/json"})
                try:
                    with opener.open(req, timeout=10) as res:
                        return res.status, json.loads(res.read())
                except urllib.error.HTTPError as err:
                    return err.code, json.loads(err.read())
            status, body = post(dict(text="덤웨이터에 음식을 싣습니다.", machines=[{"machine_code": "M1", "machine_nm": "사다리"}],
                                     photos=[{"name": "a.jpg"}]))
            self.assertEqual(status, 200)
            self.assertEqual([u["source"] for u in body["units"]], ["TEXT", "MACHINE"])
            self.assertTrue(any("사진 1장" in w for w in body["warnings"]))
            self.assertEqual(post(dict())[0], 400)
            self.assertEqual(post(None, raw=b"{bad json")[0], 400)
            self.assertEqual(post(dict(text="가" * 10001))[0], 400)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
