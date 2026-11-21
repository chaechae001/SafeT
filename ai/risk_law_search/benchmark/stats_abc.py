"""A·B·C 법령 찾기 비교 통계와 발표용 차트.

  python ai/risk_law_search/benchmark/stats_abc.py --out ai/risk_law_search/benchmark/stats_20261120

입력(읽기만): results_20261120_45cmp_c/compare_45.json, gold_v0.json, results_20261120/*.json, results_20261120_topic/*.json
출력(새 폴더만): stats.json, fig1~fig4 PNG

- 정답률 95% 신뢰구간: Wilson 구간.
- 짝비교: 같은 문항에서 한쪽만 맞은 수로 McNemar 정확 검정(양측, 이항분포).
- 위험유형: 정답 세트 문항의 정답 카드들의 위험유형(첫 유형) 중 가장 많은 것.
- 처리 시간: 같은 입력을 A만 켠 엔진과 A+B+C 엔진으로 각각 3회 돌린 중앙값(CPU).
- 정답 세트는 AI 보조·검토 전 초안이다. 수치는 그 기준이다.
"""
import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

# 차트 색: 기본 팔레트 범주 1~3번(모든 쌍 조합 검증 완료, references/palette.md). 청록은 대비가 낮아 값을 직접 표기한다.
COLOR = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
NAME = {"A": "A. 현재(카드 연결)", "B": "B. #45 방식(KURE 검색)", "C": "C. B+주제 확인"}


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 3), round(c + h, 3)


def mcnemar(x, y):
    """x만 맞은 수, y만 맞은 수 → 양측 정확 p값."""
    n = x + y
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(x, y) + 1)) / 2 ** n
    return round(min(1.0, 2 * tail), 3)


def rate(flags):
    k, n = sum(flags), len(flags)
    lo, hi = wilson(k, n)
    return dict(k=k, n=n, rate=round(k / n, 3) if n else None, ci95=[lo, hi])


def timing(texts):
    from ai.risk_law_search.engine import Engine
    from ai.risk_law_search.law_kure import KureLawFinder
    eng = Engine(ROOT / "docs" / "chroma", as_of="2026-11-20", mode="keyword", log=lambda m: None)

    def run():
        out = []
        for t in texts:
            eng.analyze(t)  # 캐시 영향 없이 같은 조건으로 한 번 돌린 뒤 측정
            ms = []
            for _ in range(3):
                t0 = time.perf_counter()
                eng.analyze(t)
                ms.append((time.perf_counter() - t0) * 1000)
            out.append(statistics.median(ms))
        return out
    a = run()
    t0 = time.perf_counter()
    eng.alt_law = KureLawFinder(eng)
    load_s = time.perf_counter() - t0
    abc = run()
    q = lambda xs: dict(mean=round(statistics.mean(xs), 1), p50=round(statistics.median(xs), 1), max=round(max(xs), 1))
    return dict(a_only_ms=q(a), abc_ms=q(abc), kure_load_s=round(load_s, 1),
                index_build_s=json.loads((ROOT / "ai/risk_law_search/.index/l01_kure/meta.json").read_text())["seconds"])


def charts(st, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 11,
                         "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
                         "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                         "text.color": INK})

    def frame(ax):
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.yaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(length=0)

    # 1) 1순위 정답률 + 95% 신뢰구간
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
    keys = ["A", "B", "C"]
    vals = [st["accuracy"][k]["rate"] for k in keys]
    for i, k in enumerate(keys):
        r = st["accuracy"][k]
        ax.bar(i, r["rate"], width=0.5, color=COLOR[k], edgecolor=SURFACE, linewidth=2, zorder=2)
        ax.errorbar(i, r["rate"], yerr=[[r["rate"] - r["ci95"][0]], [r["ci95"][1] - r["rate"]]],
                    fmt="none", ecolor=INK2, elinewidth=1.2, capsize=5, zorder=3)
        ax.text(i, r["ci95"][1] + 0.03, f"{r['rate']:.2f}  ({r['k']}/{r['n']})", ha="center", va="bottom",
                fontsize=11, color=INK, fontweight="bold")
    ax.set_xticks(range(3), [NAME[k] for k in keys])
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("1순위 법령 정답률")
    frame(ax)
    ax.set_title("위험요인 1순위 법령 정답률 (오차 막대: 95% 신뢰구간)", loc="left", fontsize=12.5, color=INK, pad=12)
    fig.text(0.01, 0.01, f"정답 세트 gold_v0 {st['accuracy']['A']['n']}문항(AI 보조·검토 전) · 위험요인은 세 방식 모두 같은 keyword 모드 결과",
             fontsize=8.5, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig1_accuracy.png")
    plt.close(fig)

    # 2) 문항별 정답 여부 표(점)
    items = st["per_item"]
    fig, ax = plt.subplots(figsize=(7.2, 0.28 * len(items) + 1.2), dpi=200)
    for row, it in enumerate(items):
        y = len(items) - 1 - row
        for col, k in enumerate(keys):
            ok = it[k]
            ax.scatter(col, y, s=70, marker="o", color=COLOR[k] if ok else SURFACE,
                       edgecolors=COLOR[k], linewidths=1.6, zorder=3)
        ax.text(-0.45, y, f"{it['id']} {it['text'][:18]}", ha="right", va="center", fontsize=8.5, color=INK2)
    ax.set_xticks(range(3), ["A", "B", "C"])
    ax.xaxis.tick_top()
    ax.set_xlim(-0.5, 2.5)
    ax.set_ylim(-0.8, len(items) - 0.2)
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    fig.tight_layout()
    fig.subplots_adjust(left=0.45, top=1 - 0.9 / fig.get_figheight())
    fig.text(0.02, 1 - 0.25 / fig.get_figheight(), "문항별 1순위 법령 정답 (● 정답 · ○ 오답)", ha="left", va="top",
             fontsize=12, color=INK)
    fig.savefig(out / "fig2_per_item.png")
    plt.close(fig)

    # 3) 위험유형별 정답률(묶음 막대, 문항 수 표기)
    big = [t for t in st["by_type"] if t["n"] >= 2]
    small = [t for t in st["by_type"] if t["n"] < 2]
    types = big
    if small:
        n = sum(t["n"] for t in small)
        types = big + [dict(type="기타", n=n, **{k: round(sum(t[k] * t["n"] for t in small) / n, 2) for k in ("A", "B", "C")})]
    names = [t["type"] for t in types]
    fig, ax = plt.subplots(figsize=(8.4, 4.4), dpi=200)
    w = 0.26
    for j, k in enumerate(keys):
        xs = [i + (j - 1) * w for i in range(len(names))]
        ys = [t[k] for t in types]
        ax.bar(xs, ys, width=w, color=COLOR[k], edgecolor=SURFACE, linewidth=2, label=NAME[k], zorder=2)
        for x, y in zip(xs, ys):
            if y == 0:
                ax.text(x, 0.01, "0", ha="center", va="bottom", fontsize=8.5, color=INK2)
    ax.set_xticks(range(len(names)), [f"{t['type']}\n(n={t['n']})" for t in types], fontsize=9.5)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("1순위 법령 정답률")
    frame(ax)
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.13), fontsize=9.5)
    ax.set_title("위험유형별 정답률 (문항 수가 적어 참고용 · 1문항 유형은 '기타')", loc="left", fontsize=12.5, color=INK, pad=30)
    fig.tight_layout()
    fig.savefig(out / "fig3_by_type.png")
    plt.close(fig)

    # 4) 임베딩 모델 비교(A 방식, 주제 확인 도입 전) — 단일 계열
    ms = st["models"]
    fig, ax = plt.subplots(figsize=(7.6, 4.0), dpi=200)
    for i, m in enumerate(ms):
        ax.bar(i, m["risk_law_hit"], width=0.55, color=COLOR["A"], edgecolor=SURFACE, linewidth=2, zorder=2)
        ax.text(i, m["risk_law_hit"] + 0.02, f"{m['risk_law_hit']:.2f}", ha="center", va="bottom", fontsize=10, color=INK)
    ax.set_xticks(range(len(ms)), [f"{m['config']}\n{m['label']}" for m in ms], fontsize=8.5)
    ax.set_ylim(0, 1)
    ax.set_ylabel("위험요인 법령 정답률")
    frame(ax)
    ax.set_title("A 방식에서 임베딩 모델만 바꾼 결과 (주제 확인 도입 전)", loc="left", fontsize=12.5, color=INK, pad=12)
    fig.tight_layout()
    fig.savefig(out / "fig4_models.png")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-timing", action="store_true")
    ap.add_argument("--charts-only", action="store_true", help="기존 stats.json으로 차트만 다시 그린다")
    ap.add_argument("--cmp", default=str(HERE / "results_20261120_45cmp_c" / "compare_45.json"), help="compare_45.py 결과 파일")
    a = ap.parse_args()
    out = Path(a.out)
    if a.charts_only:
        charts(json.loads((out / "stats.json").read_text(encoding="utf-8")), out)
        return
    if out.exists():
        raise SystemExit(f"{out} 이미 있음(덮어쓰지 않음)")
    cmp = json.loads(Path(a.cmp).read_text(encoding="utf-8"))
    gold = {it["id"]: it for it in json.loads((HERE / "gold_v0.json").read_text(encoding="utf-8"))["items"]}
    from ai.risk_law_search.engine import Engine
    eng = Engine(ROOT / "docs" / "chroma", as_of="2026-11-20", mode="keyword", log=lambda m: None)

    law = [r for r in cmp["items"] if "a_hit" in r]
    nolaw = [r for r in cmp["items"] if "a_attached" in r]
    flags = {k: [r[f] for r in law] for k, f in (("A", "a_hit"), ("B", "b_top1"), ("C", "c_hit"))}
    accuracy = {k: rate(v) for k, v in flags.items()}
    accuracy["B_top6"] = rate([r["b_top6"] for r in law])

    pairs = {}
    for x, y in (("C", "A"), ("B", "A"), ("C", "B")):
        only_x = sum(1 for p, q in zip(flags[x], flags[y]) if p and not q)
        only_y = sum(1 for p, q in zip(flags[x], flags[y]) if q and not p)
        pairs[f"{x}_vs_{y}"] = dict(only_first=only_x, only_second=only_y, both=sum(p and q for p, q in zip(flags[x], flags[y])),
                                    neither=sum(not p and not q for p, q in zip(flags[x], flags[y])), p_mcnemar=mcnemar(only_x, only_y))

    def gtype(gid):
        ts = [eng.card_by_id[c]["risk_type"].split("·")[0] for c in gold[gid]["cards"] if c in eng.card_by_id]
        return Counter(ts).most_common(1)[0][0] if ts else "기타"
    groups = defaultdict(list)
    for r in law:
        groups[gtype(r["id"])].append(r)
    by_type = sorted([dict(type=t, n=len(rs), A=round(sum(r["a_hit"] for r in rs) / len(rs), 2),
                           B=round(sum(r["b_top1"] for r in rs) / len(rs), 2), C=round(sum(r["c_hit"] for r in rs) / len(rs), 2),
                           ids=[r["id"] for r in rs]) for t, rs in groups.items()], key=lambda d: (-d["n"], d["type"]))

    hazard_ok = [r["risks"][0]["card"] in gold[r["id"]]["cards"] for r in law]
    cond = {k: rate([f for f, h in zip(flags[k], hazard_ok) if h]) for k in flags}

    abstain = dict(A=rate([r["a_attached"] for r in nolaw]), B=rate([True for _ in nolaw]), C=rate([r["c_attached"] for r in nolaw]),
                   ids=[r["id"] for r in nolaw])
    regress = []
    for r in cmp["items"]:
        if r["id"].startswith("X"):
            f = r["risks"][0]
            regress.append(dict(id=r["id"], text=r["text"], card=f["title"], A=f["a_title"], B=f["b_titles"][0], C=f["c_title"]))

    models = []
    labels = {"K0": "키워드만", "C1": "e5-small", "C2": "e5-large", "C3": "bge-m3", "C4": "KURE-v1", "C5": "bge-m3+리랭커"}
    for k in ("K0", "C1", "C2", "C3", "C4", "C5"):
        s = json.loads((HERE / "results_20261120" / f"{k}.json").read_text(encoding="utf-8"))
        models.append(dict(config=k, label=labels[k], risk_law_hit=s["summary"]["risk_law_hit"], card_top1=s["summary"]["card_top1"],
                           ms_p50=s["summary"]["ms_p50"], build_s=s["build_s"]))
    topic = {k: json.loads((HERE / "results_20261120_topic" / f"{k}.json").read_text(encoding="utf-8"))["summary"]
             for k in ("K0", "C1")}
    topic_fix = {k: dict(risk_law_hit=v["risk_law_hit"], nolaw_attached=v["nolaw_attached"]) for k, v in topic.items()}

    per_item = [dict(id=r["id"], text=r["text"], A=r["a_hit"], B=r["b_top1"], C=r["c_hit"],
                     a=r["risks"][0]["a_title"], b=r["risks"][0]["b_titles"][0], c=r["risks"][0]["c_title"],
                     gold=gold[r["id"]]["laws"]) for r in law]
    st = dict(source=str(Path(a.cmp).resolve().relative_to(ROOT)).replace("\\", "/"), gold=cmp["gold"], hazard_mode=cmp["hazard_mode"], accuracy=accuracy, pairs=pairs, by_type=by_type,
              hazard_first_correct=dict(n=sum(hazard_ok), of=len(hazard_ok), accuracy_given_correct_hazard=cond),
              abstain_on_unclear=abstain, regression=regress, models=models, topic_fix=topic_fix, per_item=per_item)
    if not a.no_timing:
        st["timing"] = timing([r["text"] for r in cmp["items"]])
    out.mkdir(parents=True)
    (out / "stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    charts(st, out)
    print(json.dumps({k: st[k] for k in ("accuracy", "pairs", "abstain_on_unclear", "hazard_first_correct")}, ensure_ascii=False))
    print(json.dumps(st.get("timing"), ensure_ascii=False))


if __name__ == "__main__":
    main()
