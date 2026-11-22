"""위험요인 → 법령 조문 매칭 평가.

평가 1(주): 위험요인 ID 정답셋(261122_RAG_법령정답셋_v1_DR.json) 15건. 질의는 카탈로그 시나리오 문구.
평가 2(보조): risk_law_search gold_v0의 입력 문장 25건(법령 정답이 있는 것). 질의 확장 없음.

지표(조문 단위, 상위 10개 목록)
- recall@k: core 조문 중 상위 k에 든 비율의 평균
- hit@k: core 조문이 하나라도 상위 k에 든 위험요인 비율
- MRR: 첫 core 조문 순위의 역수 평균(없으면 0)
- exact@1: 1순위가 core 조문인 비율
- acc_p@5: 상위 5개 중 core·related(문서 와일드카드 포함) 비율

  python ai/experiments/261122_RAG_법령매칭_DR/eval_law_matching.py [--out 결과폴더]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from ai.risk_law_search.laws import load_laws  # noqa: E402
from law_retrievers import build_all  # noqa: E402

GOLD = HERE / "261122_RAG_법령정답셋_v1_DR.json"
GOLD_V0 = ROOT / "ai/risk_law_search/benchmark/gold_v0.json"
CATALOG = ROOT / "contracts/catalog_risk/catalog.json"
KS = (1, 3, 5, 10)


def scenario_query(s):
    return " ".join([s["title"], s["task"], s["event"], s["scenario"]])


def scenario_expansion(s):
    return " ".join(s["keywords"] + [c["current_text"] for c in s["controls"]])


def accepts(key, accepted):
    return key in accepted or key.split(":")[0] + ":*" in accepted


def score_one(ranked, core, related):
    out = {f"recall@{k}": sum(1 for c in core if c in ranked[:k]) / len(core) for k in KS}
    out.update({f"hit@{k}": float(any(c in ranked[:k] for c in core)) for k in KS})
    first = next((i for i, key in enumerate(ranked, 1) if key in core), None)
    out["mrr"] = 1 / first if first else 0.0
    out["exact@1"] = float(bool(ranked) and ranked[0] in core)
    acc = set(core) | set(related)
    out["acc_p@5"] = sum(1 for key in ranked[:5] if accepts(key, acc)) / 5
    out["first_rank"] = first
    return out


def mean(rows, metric):
    return round(sum(r[metric] for r in rows) / len(rows), 3) if rows else None


METRICS = ["recall@1", "recall@3", "recall@5", "recall@10", "hit@3", "mrr", "exact@1", "acc_p@5"]


def summarize(per):
    return {m: mean(per, m) for m in METRICS} | {"n": len(per)}


def gold_v0_eval(retrievers):
    data = json.loads(GOLD_V0.read_text(encoding="utf-8"))
    items = [it for it in data["items"] if it["laws"]]
    res = {}
    for r in retrievers:
        per = []
        for it in items:
            ranked = r.rank(it["text"])
            core = [k for k in it["laws"] if not k.endswith(":*")]
            wild = [k for k in it["laws"] if k.endswith(":*")]
            first = next((i for i, key in enumerate(ranked, 1) if accepts(key, it["laws"])), None)
            per.append({"id": it["id"], "mrr": 1 / first if first else 0.0,
                        "hit@1": float(first == 1), "hit@3": float(bool(first) and first <= 3),
                        "hit@5": float(bool(first) and first <= 5),
                        "recall@5": (sum(1 for c in core if c in ranked[:5]) + sum(1 for w in wild if any(accepts(k, [w]) for k in ranked[:5])))
                        / len(it["laws"]), "top3": ranked[:3]})
        res[r.name] = dict(summary={m: mean(per, m) for m in ("hit@1", "hit@3", "hit@5", "recall@5", "mrr")} | {"n": len(per)},
                           per_query=per)
    return res, data["status"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "results_261122"))
    args = ap.parse_args()
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    catalog = {s["id"]: s for s in json.loads(CATALOG.read_text(encoding="utf-8-sig"))["scenarios"]}
    _, units = load_laws(ROOT / "chroma/laws")
    retrievers = build_all(units)
    items = [it for it in gold["items"] if it["status"] == "평가"]
    report = dict(run_at=datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
                  gold=dict(file=GOLD.name, version=gold["version"], counts=gold["counts"], status=gold["status"]),
                  query="카탈로그 title+task+event+scenario. R4·R5만 keywords+controls 추가.", results={})
    for r in retrievers:
        per = []
        for it in items:
            s = catalog[it["scenario_id"]]
            ranked = r.rank(scenario_query(s), expansion=scenario_expansion(s))
            core = [e["key"] for e in it["core"]]
            related = [e["key"] for e in it["related"]]
            row = score_one(ranked, core, related)
            row.update(scenario_id=it["scenario_id"], split=it["split"], top5=ranked[:5], core=core,
                       source_cited=any("source_cited" in e["basis"] for e in it["core"]))
            per.append(row)
        report["results"][r.name] = dict(
            all=summarize(per), dev=summarize([p for p in per if p["split"] == "dev"]),
            holdout=summarize([p for p in per if p["split"] == "holdout"]),
            source_cited=summarize([p for p in per if p["source_cited"]]), per_scenario=per)
    report["gold_v0"], report["gold_v0_status"] = gold_v0_eval(retrievers)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "law_matching_eval.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines = ["| 검색기 | 범위 | n | recall@1 | recall@3 | recall@5 | recall@10 | hit@3 | MRR | exact@1 | acc_p@5 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, res in report["results"].items():
        for part in ("all", "dev", "holdout", "source_cited"):
            m = res[part]
            lines.append(f"| {name} | {part} | {m['n']} | " + " | ".join(str(m[k]) for k in METRICS) + " |")
    lines += ["", "| 검색기 (gold_v0 입력 문장) | n | hit@1 | hit@3 | hit@5 | recall@5 | MRR |", "|---|---|---|---|---|---|---|"]
    for name, res in report["gold_v0"].items():
        m = res["summary"]
        lines.append(f"| {name} | {m['n']} | {m['hit@1']} | {m['hit@3']} | {m['hit@5']} | {m['recall@5']} | {m['mrr']} |")
    (out / "law_matching_eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
