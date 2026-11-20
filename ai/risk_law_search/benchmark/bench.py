"""위험요인·법령 검색 모델 비교 측정(PR #44 엔진 그대로 사용, 엔진 코드는 고치지 않고 의미 색인만 메모리로 바꿈).

- nolaw_attached: 맞는 조문이 불분명한 입력(gold laws null)에 위험요인 법령을 붙인 비율(낮을수록 좋음).
- risk_law_given: 법령 정답이 있는 입력에서 위험요인 법령을 하나라도 붙인 비율(빈칸 표시가 늘었는지 확인용).

  python ai/risk_law_search/benchmark/bench.py --config C1 --out <결과 폴더>

- Chroma 대신 메모리 색인을 끼운다. 점수는 원래와 같다(저장된 벡터 × 검색어 벡터 내적).
- 모델별 앞 문구: e5는 query:/passage:, 그 외는 없음. 최대 길이는 모두 512 토큰.
- 판정 기준점(card_sem_abs 0.83 등)은 e5-small 기준 그대로 둔다. 그래서 기준과 무관한 순위 지표도 함께 낸다.
- 결과 파일은 새 파일로만 만든다(있으면 오류).
"""
import argparse
import ctypes
import json
import statistics
import sys
import time
import types
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

CONFIGS = {
    "K0": dict(label="키워드만(참고)", mode="keyword", model=None, reranker=None),
    "C1": dict(label="e5-small (현재)", mode="hybrid", model="intfloat/multilingual-e5-small", reranker=None),
    "C2": dict(label="e5-large", mode="hybrid", model="intfloat/multilingual-e5-large", reranker=None),
    "C3": dict(label="bge-m3", mode="hybrid", model="BAAI/bge-m3", reranker=None),
    "C4": dict(label="KURE-v1", mode="hybrid", model="nlpai-lab/KURE-v1", reranker=None),
    "C5": dict(label="bge-m3 + bge-reranker-v2-m3", mode="hybrid", model="BAAI/bge-m3",
               reranker="BAAI/bge-reranker-v2-m3"),
}
PREFIX = {"intfloat/multilingual-e5-small": ("query: ", "passage: "),
          "intfloat/multilingual-e5-large": ("query: ", "passage: ")}
MAX_LEN = 512
RERANK_N = 20
AS_OF = "2026-11-20"


def peak_mb():
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    c = PMC()
    c.cb = ctypes.sizeof(c)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        return None
    return round(c.PeakWorkingSetSize / 2**20)


def install_memory_semantic():
    import numpy as np

    class Emb:
        def __init__(self, name):
            from sentence_transformers import SentenceTransformer
            self.model_name = name
            self.model = SentenceTransformer(name, device="cpu")
            self.model.max_seq_length = MAX_LEN
            self.q, self.p = PREFIX.get(name, ("", ""))

        def _enc(self, texts):
            return self.model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)

        def embed_documents(self, texts):
            return self._enc([self.p + t for t in texts])

        def embed_queries(self, texts):
            return self._enc([self.q + t for t in texts])

        def embed_query(self, text):
            return self.embed_queries([text])[0]

    class SemIndex:
        def __init__(self, prefix, ids, texts, metadatas, embeddings, persist_dir, log=print):
            self.name = f"{prefix}_memory"
            self.ids = list(ids)
            self.matrix = np.asarray(embeddings.embed_documents(texts), dtype="float32")

        def scores(self, query_vectors):
            return (np.asarray(query_vectors, dtype="float32") @ self.matrix.T).tolist()

    mod = types.ModuleType("ai.risk_law_search.semantic")
    mod.DEFAULT_MODEL, mod.E5Embeddings, mod.SemanticIndex = "intfloat/multilingual-e5-small", Emb, SemIndex
    sys.modules["ai.risk_law_search.semantic"] = mod


def law_key(u):
    return f"{u['doc_no']}:{u['article']}"


def law_hit(u, gold):
    return bool(u) and any(g == law_key(u) or (g.endswith(":*") and g[:-2] == u["doc_no"]) for g in gold)


class Runner:
    def __init__(self, cfg):
        from ai.risk_law_search import engine as E
        from ai.risk_law_search.cards import card_search_text
        self.E, self.card_text = E, card_search_text
        self.cfg = cfg
        t0 = time.perf_counter()
        self.eng = E.Engine(ROOT / "docs" / "chroma", as_of=AS_OF, mode=cfg["mode"], model=cfg["model"],
                            log=lambda m: None)
        self.engine_s = time.perf_counter() - t0
        self.ce = None
        self.rerank_links_s = 0.0
        if cfg["reranker"]:
            from sentence_transformers import CrossEncoder
            t1 = time.perf_counter()
            self.ce = CrossEncoder(cfg["reranker"], max_length=MAX_LEN, device="cpu")
            self._rerank_links()
            self.rerank_links_s = time.perf_counter() - t1
        self.build_s = time.perf_counter() - t0

    def _ce_order(self, query, items, text_of):
        """items 앞쪽 RERANK_N개를 교차 인코더 점수로 다시 정렬, 나머지는 뒤에 그대로."""
        head, tail = items[:RERANK_N], items[RERANK_N:]
        if not head:
            return items
        s = self.ce.predict([(query, text_of(x)) for x in head], batch_size=16, show_progress_bar=False)
        order = sorted(range(len(head)), key=lambda k: -float(s[k]))
        return [head[k] for k in order] + tail

    def _rerank_links(self):
        """카드–법령 1순위 연결도 같은 방식으로 재정렬(검색 대상 카드만)."""
        eng, rule = self.eng, self.eng.rule
        for c in eng.search_cards:
            text = eng.expand(self.card_text(c))[0]
            scores = eng._law_scores(text, eng.embedder.embed_query(text))
            ok = sorted(((i, v) for i, v in scores.items()
                         if v[0] >= rule["link_min"] and v[2] >= rule["law_kw_min"] and eng.topic_ok(c, i)),
                        key=lambda x: (-x[1][0], x[0]))
            if not ok:
                continue
            ok = self._ce_order(self.card_text(c), ok, lambda x: self.E._law_text(eng.units[x[0]]))[:self.E.LINK_K]
            eng.links[c["id"]]["nearest"] = [dict(unit_id=eng.units[i]["id"], score=round(v[0], 3),
                                                  semantic=None if v[1] is None else round(v[1], 3),
                                                  keyword=round(v[2], 3)) for i, v in ok]

    def query(self, text):
        """한 입력 = analyze 한 단위 + search 법령 경로. 시간은 이 함수 전체."""
        eng = self.eng
        expanded, _ = eng.expand(text)
        qv = eng.embedder.embed_query(expanded) if eng.mode == "hybrid" else None
        rows = eng._card_rank(expanded, qv)
        if self.ce:
            rows = self._ce_order(text, rows, lambda r: self.card_text(eng.search_cards[r[0]]))
        chosen = [r for r in rows if eng._card_ok(r)][:self.E.MAX_RISKS]
        low = not chosen and bool(rows)
        if low:
            chosen = rows[:1]
        risks = []
        for r in chosen:
            c = eng.search_cards[r[0]]
            law, _ = eng._one_law(c["id"])
            eng.options(c, text)
            risks.append(dict(card=c["id"], law=eng.unit_by_id[law["id"]] if law else None))
        # 법령 순위(기준점 무관): 시행 중 조각 전체를 혼합 점수로 정렬
        scores = eng._law_scores(expanded, qv)
        law_rank = sorted(scores.items(), key=lambda x: (-x[1][0], x[0]))
        if self.ce:
            law_rank = self._ce_order(text, law_rank, lambda x: self.E._law_text(eng.units[x[0]]))
        # search 경로(문서 번호 순서 + 관련 조문 기준)
        relevant, _, _ = eng._law_relevant(scores)
        search_top = None
        for d in eng.docs:
            hits = sorted(((i, v) for i, v in relevant.items() if eng.units[i]["doc_id"] == d["doc_id"]),
                          key=lambda x: (-x[1][0], x[0]))
            if hits:
                if self.ce:
                    hits = self._ce_order(text, hits, lambda x: self.E._law_text(eng.units[x[0]]))
                search_top = eng.units[hits[0][0]]
                break
        return dict(card_rank=[eng.search_cards[r[0]]["id"] for r in rows],
                    chosen=[x["card"] for x in risks], low=low, risk_law=risks[0]["law"] if risks else None,
                    law_rank=[eng.units[i] for i, _ in law_rank[:3]], search_law=search_top)


def evaluate(runner, gold):
    per, times = [], []
    for it in gold["items"]:
        runner.query(it["text"])  # 캐시 영향 없이 같은 조건으로: 한 번 돌린 뒤 측정
        t0 = time.perf_counter()
        r = runner.query(it["text"])
        times.append((time.perf_counter() - t0) * 1000)
        g = set(it["cards"])
        row = dict(id=it["id"], text=it["text"], negative=not g, ms=round(times[-1], 1),
                   top3=r["card_rank"][:3], chosen=r["chosen"], low=r["low"],
                   risk_law=law_key(r["risk_law"]) if r["risk_law"] else None,
                   search_law=law_key(r["search_law"]) if r["search_law"] else None,
                   law_top3=[law_key(u) for u in r["law_rank"]])
        if g:
            rank = next((k + 1 for k, cid in enumerate(r["card_rank"]) if cid in g), None)
            row.update(card_top1=r["card_rank"][:1][0] in g if r["card_rank"] else False,
                       card_top3=any(c in g for c in r["card_rank"][:3]), card_rr=1 / rank if rank else 0.0,
                       chosen_hit=any(c in g for c in r["chosen"]) and not r["low"],
                       chosen_precision=(sum(c in g for c in r["chosen"]) / len(r["chosen"])) if r["chosen"] and not r["low"] else 0.0)
        else:
            row.update(false_pass=not r["low"] and bool(r["chosen"]), false_law=r["search_law"] is not None)
        if g and not it["laws"]:
            # 맞는 조문이 불분명한 입력(laws null): 위험요인에 법령을 붙였으면 엉뚱한 연결일 가능성이 크다.
            row.update(nolaw_attached=r["risk_law"] is not None)
        if it["laws"]:
            row.update(risk_law_hit=law_hit(r["risk_law"], it["laws"]), search_law_hit=law_hit(r["search_law"], it["laws"]),
                       law_top1=law_hit(r["law_rank"][0] if r["law_rank"] else None, it["laws"]),
                       law_top3=any(law_hit(u, it["laws"]) for u in r["law_rank"]))
        per.append(row)
    return per, times


def summarize(per, times):
    pos = [p for p in per if not p["negative"]]
    neg = [p for p in per if p["negative"]]
    law = [p for p in per if "risk_law_hit" in p]
    nolaw = [p for p in per if "nolaw_attached" in p]
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    st = sorted(times)
    return dict(
        n_pos=len(pos), n_neg=len(neg), n_law=len(law), n_nolaw=len(nolaw),
        nolaw_attached=mean([p["nolaw_attached"] for p in nolaw]),
        risk_law_given=mean([p["risk_law"] is not None for p in law]),
        card_top1=mean([p["card_top1"] for p in pos]), card_top3=mean([p["card_top3"] for p in pos]),
        card_mrr=mean([p["card_rr"] for p in pos]),
        chosen_hit=mean([p["chosen_hit"] for p in pos]), chosen_precision=mean([p["chosen_precision"] for p in pos]),
        pos_low_confidence=mean([p["low"] for p in pos]),
        neg_false_pass=mean([p["false_pass"] for p in neg]), neg_false_law=mean([p["false_law"] for p in neg]),
        risk_law_hit=mean([p["risk_law_hit"] for p in law]), search_law_hit=mean([p["search_law_hit"] for p in law]),
        law_top1=mean([p["law_top1"] for p in law]), law_top3=mean([p["law_top3"] for p in law]),
        ms_mean=round(statistics.mean(times), 1), ms_p50=round(statistics.median(times), 1),
        ms_p95=round(st[min(len(st) - 1, int(round(0.95 * (len(st) - 1))))], 1), ms_max=round(st[-1], 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, choices=CONFIGS)
    ap.add_argument("--gold", default=str(Path(__file__).with_name("gold_v0.json")))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cfg = CONFIGS[a.config]
    out = Path(a.out) / f"{a.config}.json"
    if out.exists():
        raise SystemExit(f"{out} 이미 있음(덮어쓰지 않음)")
    import torch
    if cfg["mode"] == "hybrid":
        install_memory_semantic()
    gold = json.loads(Path(a.gold).read_text(encoding="utf-8"))
    runner = Runner(cfg)
    per, times = evaluate(runner, gold)
    res = dict(config=a.config, **cfg, device="cpu", torch=torch.__version__, threads=torch.get_num_threads(),
               max_len=MAX_LEN, rerank_n=RERANK_N if cfg["reranker"] else None, as_of=AS_OF, gold=gold["version"],
               tokenizer=runner.eng.tokenizer.name, law_units=len(runner.eng.law_allowed),
               build_s=round(runner.build_s, 1), engine_s=round(runner.engine_s, 1),
               rerank_links_s=round(runner.rerank_links_s, 1), peak_mb=peak_mb(),
               summary=summarize(per, times), items=per)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(dict(config=a.config, build_s=res["build_s"], peak_mb=res["peak_mb"], **res["summary"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
