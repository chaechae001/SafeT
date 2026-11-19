"""카드·법령 색인을 만들고 키워드로 조회한다.

방식(mode)
- hybrid(기본): e5 임베딩 의미 점수 + 키워드(TF-IDF) 점수를 섞는다. 저장은 LangChain Chroma.
- keyword: 키워드 점수만 쓴다. 모델·추가 패키지가 없는 환경용.

점수(관련도 0~1)
- 의미 점수는 검색어마다 '중앙값 → 0, 최고값 → 1'로 맞춘다. 키워드 점수는 최고값으로 나눈다.
- 혼합 = W·의미 + (1−W)·키워드. 벌칙·과태료·양벌규정 조문은 의무 근거가 아니어서 ×0.7.
- 관련도는 검색 순위용이다. 위험도나 법령 적용 판단이 아니다.

규칙
- 카드(위험) 검색: check·case 카드만. reference 카드는 대책 출처로만 보존한다.
- 법령 검색: 파일명 앞 번호 순서(01 → … → 08)로 문서를 보고, 관련 조문이 있는 첫 문서에서 멈춘다.
  관련 조문 = 혼합 점수가 기준 이상이고 키워드도 일부 겹치는 조문(모델만으로 고른 조문은 인정하지 않음).
- 카드–법령 연결: 카드 고유 내용(기기·사고 유형·제목·본문)과 가장 가까운 관련 조문 상위 LINK_K개.
  카드 laws의 법령은 'card_cited'로 따로.
- 플랫폼 입력 분석(analyze): 글·음성은 문장, 등록 기기는 기기마다 한 단위. 단위마다 위험요인 1~3개,
  위험요인마다 법령 1개(가장 가까운 조문 1순위 → 카드 기재 법령 → 없음).
"""
import datetime
import json
import re
import statistics
import time
from pathlib import Path

from .cards import card_context_text, card_law_text, card_search_text, load_cards
from .laws import load_laws
from .textindex import TextIndex, make_tokenizer

HERE = Path(__file__).resolve().parent
LINK_K = 3
MAX_RISKS = 3   # 분석 단위당 위험요인 최대 개수(최소 1개)
OPTION_N = 3    # 현재 조치 사항·개선 조치 사항 각각 제시 개수(항상 이 개수로 채움)
SIMILAR_K = 15  # 조치 항목을 채울 때 볼 비슷한 카드 수
MAX_UNITS = 60  # 한 번에 분석하는 단위 수 상한
# 문장 경계: 마침표·물음표·느낌표(소수점 제외), 줄바꿈, 세미콜론
SENTENCE = re.compile(r"(?<=[.!?。？！])(?!\d)\s*|[\r\n;]+")
CONTEXT_W = 0.3  # 구역 공통 문구(구역명·대상 작업·예시 작업)의 키워드 비중
PENALTY_TITLES = ("벌칙", "과태료", "양벌규정")
PENALTY = 0.7
RULES = {
    "keyword": dict(card_min=0.10, law_min=0.12, law_ratio=0.6, link_min=0.12),
    # 혼합: 법령은 혼합 0.6 이상 + 키워드 원점수 0.2 이상, 카드는 혼합 0.45 이상(의미만으로도 인정).
    # 키워드 기준 0.2는 형태소 토큰화(kiwi) 기준이다. 예시 키워드에서 바른 조문 0.26~0.71, 엉뚱한 조문 0.14~0.18.
    "hybrid": dict(law_w=0.5, card_w=0.6, law_min=0.6, law_kw_min=0.2, card_min=0.45, link_min=0.6,
                   # 카드 기준 통과에는 절대 근거가 하나 더 필요하다: 키워드가 겹치거나(원점수 0.1 이상)
                   # 모델 원점수(코사인)가 0.83 이상. 의미 없는 입력은 원점수 0.81~0.82·키워드 0이었다.
                   card_kw_abs=0.1, card_sem_abs=0.83),
}
NEGATION = re.compile(r"(없[다어습고음]|않[다아습는고음]|안\s*(?:해|함|합니다|씁니다|써요|쓴다|씀)|아니[다요에]|미사용|하지\s*않)")
NOTICE = ("검색 결과는 확인용 후보입니다. 위험 확정·위험도 계산·법령 적용 확정이 아닙니다. "
          "법령은 보유 원문 기준이며 현행성·적용 조건은 담당자가 확인해야 합니다.")


def _law_text(u):
    return " ".join(x for x in (u["law_name"], u["article_title"], u["heading"].split(" > ")[-1], u["search_text"]) if x)


def _relative(values):
    """의미 점수를 검색어별로 0~1로 맞춘다(중앙값 0, 최고값 1)."""
    if not values:
        return []
    mid, best = statistics.median(values), max(values)
    span = best - mid
    return [0.0 if span <= 1e-9 else min(1.0, max(0.0, (v - mid) / span)) for v in values]


class Engine:
    def __init__(self, data_dir, card_file=None, as_of=None, synonyms=None, mode="hybrid",
                 model=None, index_dir=None, log=print, tokenizer="kiwi"):
        t0 = time.time()
        if mode not in RULES:
            raise ValueError(f"mode는 {', '.join(RULES)} 중 하나입니다.")
        self.mode, self.rule = mode, RULES[mode]
        data_dir = Path(data_dir)
        self.as_of = as_of or datetime.date.today().isoformat()
        self.docs, self.units = load_laws(data_dir)
        self.cards, self.card_meta = load_cards(card_file or data_dir / "risk_card_data.md")
        self.synonyms = {k: v for k, v in json.loads(
            Path(synonyms or HERE / "synonyms.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
        actions = json.loads((HERE / "measure_actions.json").read_text(encoding="utf-8"))
        self.actions_version = actions["version"]
        self.actions = {v["original"]: v["action"] for v in actions["items"].values()}
        self.unit_by_id = {u["id"]: u for u in self.units}
        self.card_by_id = {c["id"]: c for c in self.cards}
        # 평가일 기준 시행 중인 조각만 검색한다(시행 예정 판은 보존만).
        self.law_pos = [i for i, u in enumerate(self.units)
                        if not (u["effective_from"] and u["effective_from"] > self.as_of)]
        self.law_allowed = set(self.law_pos)
        self.tokenizer = make_tokenizer(tokenizer)
        self.law_index = TextIndex([_law_text(u) for u in self.units], self.tokenizer)
        self.penalty = [PENALTY if self.units[i]["article_title"] in PENALTY_TITLES else 1.0 for i in self.law_pos]
        self.search_cards = [c for c in self.cards if c["kind"] in ("checklist", "case")]
        self.card_index = TextIndex([card_search_text(c) for c in self.search_cards], self.tokenizer)
        self.card_context_index = TextIndex([card_context_text(c) for c in self.search_cards], self.tokenizer)
        self.model_info = None
        if mode == "hybrid":
            self._load_semantic(model, index_dir or HERE / ".index", log)
        self.links = self._link_all()
        self.similar = self._similar_cards()
        self.build_seconds = round(time.time() - t0, 2)

    def _similar_cards(self):
        """검색 대상 카드마다 비슷한 카드 순서(자기 제외). 조치 항목을 3개로 채울 때 쓴다."""
        ids = [c["id"] for c in self.search_cards]
        if self.mode == "hybrid":
            rows = self.card_sem.scores(self.card_sem.matrix)
        else:
            rows = []
            for c in self.search_cards:
                s = self.card_index.scores(card_search_text(c))
                rows.append([s.get(i, 0.0) for i in range(len(ids))])
        out = {}
        for i, cid in enumerate(ids):
            order = sorted((j for j in range(len(ids)) if j != i), key=lambda j: (-rows[i][j], j))
            out[cid] = [ids[j] for j in order[:SIMILAR_K]]
        return out

    # ---------- 의미 색인 ----------
    def _load_semantic(self, model, index_dir, log):
        from .semantic import DEFAULT_MODEL, E5Embeddings, SemanticIndex
        self.embedder = E5Embeddings(model or DEFAULT_MODEL)
        units = [self.units[i] for i in self.law_pos]
        self.law_sem = SemanticIndex(
            "laws", [u["id"] for u in units], [_law_text(u) for u in units],
            [dict(doc_no=u["doc_no"], doc_order=u["order"][0] * 100 + u["order"][1], locator=u["locator"],
                  law_name=u["law_name"], effective_from=u["effective_from"] or "") for u in units],
            self.embedder, index_dir, log)
        self.card_sem = SemanticIndex(
            "cards", [c["id"] for c in self.search_cards], [card_search_text(c) for c in self.search_cards],
            [dict(kind=c["kind"], risk_type=c["risk_type"], section=c["section"] or "") for c in self.search_cards],
            self.embedder, index_dir, log)
        self.model_info = dict(model=self.embedder.model_name, store="langchain_chroma", index_dir=str(index_dir),
                               law_collection=self.law_sem.name, card_collection=self.card_sem.name)

    # ---------- 점수 ----------
    def _law_scores(self, text, qvec=None):
        """시행 중 법령 조각별 (혼합 점수, 의미 0~1, 키워드 원점수). 키 = units 번호."""
        kw = self.law_index.scores(text, self.law_allowed)
        if self.mode == "keyword":
            return {i: (s, None, s) for i, s in kw.items()}
        sem = _relative(self.law_sem.scores([qvec])[0])
        kwv = [kw.get(i, 0.0) for i in self.law_pos]
        top = max(kwv, default=0.0) or 1.0
        w = self.rule["law_w"]
        return {i: ((w * s + (1 - w) * k / top) * p, s, k)
                for i, s, k, p in zip(self.law_pos, sem, kwv, self.penalty)}

    def _law_relevant(self, scores):
        """관련 조문 판정 기준과 통과 목록."""
        if self.mode == "keyword":
            best = max((v[0] for v in scores.values()), default=0.0)
            cut = max(self.rule["law_min"], self.rule["law_ratio"] * best)
            ok = {i: v for i, v in scores.items() if v[0] >= cut}
        else:
            best = max((v[0] for v in scores.values()), default=0.0)
            cut = self.rule["law_min"]
            ok = {i: v for i, v in scores.items() if v[0] >= cut and v[2] >= self.rule["law_kw_min"]}
        return ok, cut, best

    def _card_hits(self, text, qvec, k):
        return [r for r in self._card_rank(text, qvec) if self._card_ok(r)][:k]

    def _card_ok(self, row):
        """카드 기준 통과: 관련도 기준 이상 + (혼합 방식은) 키워드 겹침 또는 모델 원점수 절대 기준."""
        _, score, _, kw, sem_raw = row
        if score < self.rule["card_min"]:
            return False
        return self.mode == "keyword" or kw >= self.rule["card_kw_abs"] or sem_raw >= self.rule["card_sem_abs"]

    def _card_rank(self, text, qvec):
        """모든 검색 대상 카드의 (번호, 관련도, 의미 0~1, 키워드 원점수, 의미 원점수)를 관련도 순으로."""
        own = self.card_index.scores(text)
        ctx = self.card_context_index.scores(text)
        if self.mode == "keyword":
            kw = {i: own.get(i, 0.0) + CONTEXT_W * ctx.get(i, 0.0) for i in set(own) | set(ctx)}
            return sorted(((i, s, None, s, None) for i, s in kw.items() if s > 0), key=lambda x: (-x[1], x[0]))
        sem_raw = self.card_sem.scores([qvec])[0]
        sem = _relative(sem_raw)
        n = len(self.search_cards)
        # 고유 문구와 구역 공통 문구를 따로 0~1로 맞춘 뒤 합친다. 함께 나누면 고유 문구가 하나도 안 겹칠 때
        # 공통 문구 점수가 최고값 1로 커져 카드 고유 위험보다 앞서게 된다.
        own_top = max(own.values(), default=0.0) or 1.0
        ctx_top = max(ctx.values(), default=0.0) or 1.0
        kwn = [(own.get(i, 0.0) / own_top + CONTEXT_W * ctx.get(i, 0.0) / ctx_top) / (1 + CONTEXT_W) for i in range(n)]
        raw = [own.get(i, 0.0) + CONTEXT_W * ctx.get(i, 0.0) for i in range(n)]
        w = self.rule["card_w"]
        rows = [(i, w * s + (1 - w) * kwn[i], s, raw[i], sem_raw[i]) for i, s in enumerate(sem)]
        return sorted(rows, key=lambda x: (-x[1], x[0]))

    # ---------- 카드–법령 연결 ----------
    def _cited(self, card):
        out = []
        for text in card["laws"]:
            # 법령명이 같아도 뒤에 시행령·시행규칙이 붙으면 다른 법령이다(보유하지 않음).
            doc = next((d for d in self.docs if text.startswith(d["law_name"])
                        and not text[len(d["law_name"]):].lstrip().startswith(("시행령", "시행규칙"))), None)
            if not doc:
                out.append(dict(text=text, status="보유 법령 원문에 없음", unit_ids=[]))
                continue
            m = re.search(r"제(\d+)조(?:의(\d+))?", text[len(doc["law_name"]):])
            ids = []
            if m:
                key = f"art{m[1]}" + (f"-{m[2]}" if m[2] else "")
                ids = [u["id"] for i, u in enumerate(self.units)
                       if u["doc_id"] == doc["doc_id"] and f":{key}:" in u["id"] and i in self.law_allowed]
            out.append(dict(text=text, doc_id=doc["doc_id"], unit_ids=ids,
                            status="조문 연결" if ids else ("조문 번호 없음" if not m else "조문을 찾지 못함")))
        return out

    def _link_all(self):
        # 카드 고유 내용으로 연결한다. 대책 문장을 넣으면 '용기·장갑' 같은 낱말이 엉뚱한 조문과 겹쳤다(README 참고).
        texts = [self.expand(card_search_text(c))[0] for c in self.cards]
        qvecs = self.embedder.embed_queries(texts) if self.mode == "hybrid" else [None] * len(texts)
        links = {}
        for c, text, qv in zip(self.cards, texts, qvecs):
            scores = self._law_scores(text, qv)
            if self.mode == "keyword":
                ok = {i: v for i, v in scores.items() if v[0] >= self.rule["link_min"]}
            else:
                ok = {i: v for i, v in scores.items() if v[0] >= self.rule["link_min"] and v[2] >= self.rule["law_kw_min"]}
            top = sorted(ok.items(), key=lambda x: (-x[1][0], x[0]))[:LINK_K]
            links[c["id"]] = dict(nearest=[dict(unit_id=self.units[i]["id"], score=round(v[0], 3),
                                                semantic=None if v[1] is None else round(v[1], 3), keyword=round(v[2], 3))
                                           for i, v in top],
                                  card_cited=self._cited(c))
        return links

    # ---------- 조회 ----------
    def expand(self, query):
        added = []
        for key, values in self.synonyms.items():
            if key.lower() in query.lower():
                added += [v for v in values if v not in added and v.lower() not in query.lower()]
        return (query + " " + " ".join(added)).strip(), added

    def law_view(self, unit_id, score=None, detail=None):
        u = self.unit_by_id[unit_id]
        return dict(id=u["id"], doc_id=u["doc_id"], doc_no=u["doc_no"], law_name=u["law_name"], locator=u["locator"],
                    article_title=u["article_title"], heading=u["heading"], quote=u["quote"],
                    effective_from=u["effective_from"], future_version=u["future_version"],
                    future_note=u["future_note"], table_review_required=u["table_review_required"],
                    score=None if score is None else round(score, 3), score_detail=detail,
                    status="원문 대조 전 후보 · 적용 조건 미확인")

    def card_view(self, c, score=None, detail=None):
        link = self.links[c["id"]]
        current, improve = self.options(c)
        return dict(
            id=c["id"], kind=c["kind"], section=c["section"], target=c["target"], risk_type=c["risk_type"],
            title=c["title"], text=c["text"], machine_names=c["machine_names"], example_jobs=c["example_jobs"],
            current_options=current, improvement_options=improve,
            measures=c["measures"], measures_extra=c["measures_extra"],
            laws_recorded=c["laws_recorded"], source=c["source"], deaths_3y=c["deaths_3y"],
            score=None if score is None else round(score, 3), score_detail=detail,
            nearest_laws=[self.law_view(x["unit_id"], x["score"], dict(semantic=x["semantic"], keyword=x["keyword"]))
                          for x in link["nearest"]],
            card_cited_laws=[dict(x, units=[self.law_view(i) for i in x["unit_ids"]]) for x in link["card_cited"]])

    def _measure_relevance(self, text, query_tokens, title_tokens=frozenset()):
        """조치 문장과 입력의 낱말 겹침(드문 낱말일수록 큼). 입력 문장 낱말은 2배, 카드 제목 낱말은 1배.
        같은 단계 안에서 3개를 고를 때만 쓴다."""
        idf = self.card_index.idf
        toks = set(self.tokenizer(text))
        return (2 * sum(idf.get(t, 1.0) for t in toks & query_tokens)
                + sum(idf.get(t, 1.0) for t in toks & title_tokens))

    def options(self, c, query=""):
        """화면에서 고를 항목. 현재 조치 사항·개선 조치 사항을 각각 OPTION_N개로 채운다.

        문구: measure_actions.json의 간결한 방법 문구(text)를 보여 주고 원문은 original에 남긴다.
        정리표에 없는 원문은 원문 그대로 쓰고 action_reviewed=False로 표시한다.

        현재 조치 사항: ① 이 카드 직접 대책 → ② 비슷한 카드들의 직접 대책
        개선 조치 사항: ① 이 카드 보강 대책 → ② 비슷한 카드들의 보강 대책 → ③ 비슷한 카드들의 직접 대책
        같은 단계에서 넘치면 입력과 낱말이 많이 겹치는 순서로 고른다. 두 목록에 같은 문장은 넣지 않는다.
        문장을 새로 만들지 않고 카드 자료의 대책만 쓰며, 항목마다 출처를 남긴다.
        처음에는 아무것도 선택하지 않는다. 고르지 않은 항목을 '미실시'로 해석하지 않는다.
        """
        q = set(self.tokenizer(query)) if query else set()
        title = set(self.tokenizer(c["title"]))
        sims = [self.card_by_id[x] for x in self.similar.get(c["id"], [])]

        def item(mid, original, origin, origin_card, **extra_fields):
            key = re.sub(r"\s+", " ", original).strip()
            action = self.actions.get(key)
            return dict(id=mid, text=action or key, original=key, action_reviewed=bool(action),
                        origin=origin, origin_card=origin_card, **extra_fields)

        def direct(card, origin):
            return [item(f"{card['id']}:M{n}", t, origin, card["id"]) for n, t in enumerate(card["measures"], 1)]

        def extra(card, origin):
            return [item(f"{card['id']}:X{n}", m["text"], origin, m["from_card"] or card["id"], via_card=card["id"])
                    for n, m in enumerate(card["measures_extra"], 1)]

        def pick(tiers, used):
            out = []
            for tier in tiers:
                fresh = []
                for o in tier:
                    key = re.sub(r"\s+", "", o["text"])  # 정리 문구 기준으로 중복 제거
                    if key not in used:
                        used.add(key)
                        fresh.append(o)
                fresh.sort(key=lambda o: -self._measure_relevance(o["original"], q, title))  # 같은 점수는 원래 순서 유지
                out += fresh[:OPTION_N - len(out)]
                if len(out) >= OPTION_N:
                    break
            return out

        used = set()
        current = pick([direct(c, "이 카드 직접 대책")] + [direct(s, "유사 카드 직접 대책") for s in sims], used)
        improve = pick([extra(c, "이 카드 보강 대책")] + [extra(s, "유사 카드 보강 대책") for s in sims]
                       + [direct(s, "유사 카드 직접 대책") for s in sims], used)
        for o in current + improve:
            o["selected"] = False
        return current, improve

    @staticmethod
    def _detail(sem, kw):
        return dict(semantic=None if sem is None else round(sem, 3), keyword=round(kw, 3))

    def search(self, query, card_k=8, law_docs=1, law_k=5, law_start=None):
        query = (query or "").strip()
        if not query:
            raise ValueError("검색어를 입력해 주세요.")
        if len(query) > 500:
            raise ValueError("검색어는 500자 이하로 입력해 주세요.")
        expanded, added = self.expand(query)
        neg = NEGATION.search(query)
        qvec = self.embedder.embed_query(expanded) if self.mode == "hybrid" else None
        cards = [self.card_view(self.search_cards[i], s, self._detail(sem, kw))
                 for i, s, sem, kw, _ in self._card_hits(expanded, qvec, card_k)]

        relevant, cut, best = self._law_relevant(self._law_scores(expanded, qvec))
        trail, laws, found = [], [], 0
        start = not law_start
        for d in self.docs:
            row = dict(doc_id=d["doc_id"], doc_no=d["doc_no"], law_name=d["law_name"])
            if not start:
                start = d["doc_no"] == law_start
                trail.append(dict(row, status="이전 검색"))
                continue
            if found >= law_docs:
                trail.append(dict(row, status="미검색"))
                continue
            hits = sorted(((i, v) for i, v in relevant.items() if self.units[i]["doc_id"] == d["doc_id"]),
                          key=lambda x: (-x[1][0], x[0]))
            if hits:
                found += 1
                laws += [self.law_view(self.units[i]["id"], v[0], self._detail(v[1], v[2])) for i, v in hits[:law_k]]
            trail.append(dict(row, status=f"관련 조문 {len(hits)}개" if hits else "관련 조문 없음"))
        hit_docs = [t["doc_no"] for t in trail if re.match(r"관련 조문 \d", t["status"])]
        more = bool(hit_docs) and any(t["status"] == "미검색" for t in trail)
        return dict(query=query, expanded_terms=added, as_of=self.as_of, mode=self.mode, notice=NOTICE,
                    negation=dict(found=bool(neg), phrase=neg.group(0) if neg else None,
                                  message="부정 표현이 있습니다. '없다·하지 않는다' 내용도 같은 단어로 검색되므로 결과를 직접 확인해 주세요." if neg else None),
                    cards=cards, cards_status="ok" if cards else "no_evidence",
                    laws=laws, laws_status="ok" if laws else "no_evidence",
                    law_rule=dict(order="파일명 앞 번호 순", mode=self.mode, cut=round(cut, 3), best=round(best, 3), docs=law_docs),
                    law_trail=trail, law_next_start=hit_docs[-1] if more else None)

    # ---------- 플랫폼 입력 분석(새 평가표 만들기 형식) ----------
    def split_units(self, text="", voice_text="", machines=()):
        """글·음성 전사문은 문장 단위, 등록 기기는 기기마다 한 단위로 나눈다. 같은 문장은 한 번만."""
        units, seen = [], set()
        for source, label, content in (("TEXT", "작업 설명", text), ("VOICE", "음성 전사문", voice_text)):
            parts = [p.strip(" \t·-•") for p in SENTENCE.split(content or "")]
            for n, p in enumerate([p for p in parts if len(p) >= 2], 1):
                key = re.sub(r"\s+", " ", p)
                if key in seen:
                    continue
                seen.add(key)
                units.append(dict(unit_id=f"{source}:{n}", source=source, source_label=label, text=p))
        for n, m in enumerate(machines or (), 1):
            name = (m.get("machine_nm") if isinstance(m, dict) else str(m) if m is not None else "") or ""
            name = name.strip()
            if len(name) < 1 or ("M:" + name) in seen:
                continue
            seen.add("M:" + name)
            code = m.get("machine_code") if isinstance(m, dict) else None
            units.append(dict(unit_id=f"MACHINE:{code or n}", source="MACHINE", source_label="등록 기기", text=name,
                              note="보유 기기이며 실제 사용·노출이 확인된 것은 아닙니다."))
        return units

    def _one_law(self, card_id):
        """위험요인 하나에 붙일 법령 하나: 가장 가까운 조문 1순위 → 없으면 카드에 적힌 법령 → 없으면 없음."""
        link = self.links[card_id]
        if link["nearest"]:
            x = link["nearest"][0]
            return self.law_view(x["unit_id"], x["score"], dict(semantic=x["semantic"], keyword=x["keyword"])), \
                "카드와 가장 가까운 조문(자동 연결 · 적용 미확인)"
        for cited in link["card_cited"]:
            if cited["unit_ids"]:
                return self.law_view(cited["unit_ids"][0]), "카드에 적힌 법령(원문 대조 전)"
        return None, "기준 이상 조문 없음" + (" · 카드 기재 법령은 보유 원문에 없음" if link["card_cited"] else "")

    def analyze(self, text="", voice_text="", machines=(), photos=0):
        if not ((text or "").strip() or (voice_text or "").strip() or machines):
            raise ValueError("작업 설명, 음성 전사문, 등록 기기 중 하나 이상이 필요합니다.")
        if len(text or "") > 10000 or len(voice_text or "") > 10000:
            raise ValueError("작업 설명과 음성 전사문은 각각 10,000자 이하로 입력해 주세요.")
        units = self.split_units(text, voice_text, machines)
        if len(units) > MAX_UNITS:
            raise ValueError(f"분석 단위가 {MAX_UNITS}개를 넘습니다. 입력을 나눠 주세요.")
        queries = [self.expand(u["text"]) for u in units]
        qvecs = self.embedder.embed_queries([q for q, _ in queries]) if self.mode == "hybrid" else [None] * len(units)
        out, seen_cards = [], set()
        for u, (q, added), qv in zip(units, queries, qvecs):
            rows = self._card_rank(q, qv)
            chosen = [r for r in rows if self._card_ok(r)][:MAX_RISKS]
            low = not chosen and bool(rows)
            if low:
                chosen = rows[:1]  # 위험요인은 최소 1개. 기준 미달이면 확인 필요로 표시한다.
            risks = []
            for i, s, sem, kw, _ in chosen:
                c = self.search_cards[i]
                seen_cards.add(c["id"])
                law, basis = self._one_law(c["id"])
                current, improve = self.options(c, u["text"])
                risks.append(dict(
                    card_id=c["id"], kind=c["kind"], title=c["title"], text=c["text"], risk_type=c["risk_type"],
                    section=c["section"], current_options=current, improvement_options=improve,
                    measures=c["measures"], measures_extra=c["measures_extra"],
                    laws_recorded=c["laws_recorded"], source=c["source"],
                    score=round(s, 3), score_detail=self._detail(sem, kw),
                    low_confidence=low, status="기준 미달 · 확인 필요" if low else "위험 후보 · 현장 적용 확인 필요",
                    law=law, law_basis=basis))
            neg = NEGATION.search(u["text"])
            out.append(dict(u, expanded_terms=added, risks=risks,
                            status="ok" if risks and not low else ("low_confidence" if low else "no_evidence"),
                            negation=dict(found=bool(neg), phrase=neg.group(0) if neg else None)))
        warnings = []
        if photos:
            warnings.append(f"사진 {photos}장은 분석하지 않았습니다. 이 조회 모듈에는 사진 기기 탐지가 연결되어 있지 않습니다.")
        if any(x["negation"]["found"] for x in out):
            warnings.append("부정 표현(없다·하지 않는다 등)이 있는 문장이 있습니다. 해당 문장의 결과는 직접 확인해 주세요.")
        return dict(as_of=self.as_of, mode=self.mode, notice=NOTICE, warnings=warnings,
                    rule=dict(risks_per_unit=f"1~{MAX_RISKS}", law_per_risk=1, card_min=self.rule["card_min"]),
                    summary=dict(units=len(out), risks=sum(len(x["risks"]) for x in out), unique_cards=len(seen_cards),
                                 low_confidence_units=sum(1 for x in out if x["status"] == "low_confidence"),
                                 risks_without_law=sum(1 for x in out for r in x["risks"] if not r["law"])),
                    units=out)

    def health(self):
        return dict(status="ok", mode=self.mode, model=self.model_info, tokenizer=self.tokenizer.name, as_of=self.as_of,
                    measure_actions=dict(version=self.actions_version, count=len(self.actions)),
                    build_seconds=self.build_seconds, cards=self.card_meta, searchable_cards=len(self.search_cards),
                    laws=[{k: d[k] for k in ("doc_id", "law_name", "effective_from", "file", "sha256", "articles")}
                          for d in self.docs],
                    law_units=len(self.units), law_units_in_force=len(self.law_allowed))

    def export_links(self):
        """카드–법령 연결 전체(검토용)."""
        return dict(as_of=self.as_of, mode=self.mode, model=self.model_info,
                    rule=dict(k=LINK_K, **self.rule), cards=self.card_meta,
                    links={cid: dict(nearest=[dict(x, locator=self.unit_by_id[x["unit_id"]]["locator"],
                                                   law_name=self.unit_by_id[x["unit_id"]]["law_name"]) for x in v["nearest"]],
                                     card_cited=v["card_cited"]) for cid, v in self.links.items()})
