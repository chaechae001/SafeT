"""추천형 S04 평가: 기기별 위험요인 후보의 Recall@K·Precision@K (모델 호출 없음).

정답셋(RAG 세션이 실제 평가 기록에서 작성 중)이 생기면:
    python src/eval_hitl.py --gt <정답셋.json>
정답셋 형식(어느 쪽이든 받는다. 기기 키 = 기기마스터 equipment_id):
  1) {"equipment": {"EQ_FRYER": ["burn", "fire"], ...}}
  2) {"items": [{"equipment_id": "EQ_FRYER", "hazard_code": "burn"}, ...]}
     hazard_code 대신 hazard_text만 있으면 기기마스터 위험 코드 낱말로 분류하고(분류 결과를 보고서에 남김),
     분류되지 않는 문장은 '코드 없음'으로 따로 센다(평가에서 빠지지 않고 재현율 분모에 남는다).
정의(기기 하나):  Recall@K = |상위 K ∩ 정답| / |정답|,  Precision@K = |상위 K ∩ 정답| / K
  - 후보가 K개보다 적어도 분모는 K다. 정답이 없는 기기는 평가에서 뺀다. 기기별 값을 단순 평균(macro)한다.
python src/eval_hitl.py --selftest   → 손으로 계산한 값과 비교(합성 정답, 계산 검사용)
python src/eval_hitl.py              → 정답셋 없이 실행 가능한 점검만(정답 대비 점수 아님)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

OUT = ROOT / "runs" / "hitl_recommend"


def at_k(ranked: list[str], gold: set[str], k: int) -> tuple[float, float]:
    hit = len(set(ranked[:k]) & gold)
    return hit / len(gold), hit / k


def evaluate(ranked: dict[str, dict[str, list[str]]], gt: dict[str, set[str]], ks: list[int]) -> dict:
    res = {}
    for m, per in ranked.items():
        eqs = [e for e in gt if gt[e]]
        missing = [e for e in eqs if e not in per]
        row = {"n_equipment": len(eqs), "missing_in_output": missing,
               "avg_candidates": round(sum(len(per.get(e, [])) for e in eqs) / max(len(eqs), 1), 2)}
        for k in ks:
            rs, ps = zip(*[at_k(per.get(e, []), gt[e], k) for e in eqs]) if eqs else ((), ())
            row[f"R@{k}"] = round(sum(rs) / len(rs), 4) if rs else None
            row[f"P@{k}"] = round(sum(ps) / len(ps), 4) if ps else None
        res[m] = row
    return res


def load_gt(path: Path, em) -> tuple[dict[str, set[str]], dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    gt: dict[str, set[str]] = {}
    info = {"source": str(path), "classified_from_text": [], "no_code": [], "unknown_equipment": []}
    if "equipment" in d:
        for e, codes in d["equipment"].items():
            gt.setdefault(e, set()).update(codes)
    for it in d.get("items", []):
        e = it["equipment_id"]
        if e not in em.equipment:
            info["unknown_equipment"].append(e)
            continue
        codes = [it["hazard_code"]] if it.get("hazard_code") else em.classify(it.get("hazard_text", ""))
        if not it.get("hazard_code"):
            info["classified_from_text"].append({"equipment_id": e, "text": it.get("hazard_text"), "codes": codes})
        if not codes:
            info["no_code"].append({"equipment_id": e, "text": it.get("hazard_text")})
            codes = [f'__no_code__:{it.get("hazard_text")}']   # 맞힐 수 없는 정답으로 분모에 남긴다
        gt.setdefault(e, set()).update(codes)
    bad = sorted({c for v in gt.values() for c in v if c not in em.code_names and not c.startswith("__no_code__")})
    if bad:
        raise ValueError(f"정답셋에 알 수 없는 위험 코드: {bad}")
    return gt, info


def selftest() -> dict:
    """합성 정답으로 계산식만 검사한다(성능 평가 아님)."""
    ranked = {"X": {"E1": ["burn", "fire", "slip"], "E2": ["cut"], "E3": []}}
    gt = {"E1": {"burn", "slip", "gas"}, "E2": {"cut", "electric"}, "E3": {"slip"}, "E4": set()}
    r = evaluate(ranked, gt, [1, 3])["X"]
    # 손 계산: E1 R@1=1/3 P@1=1, R@3=2/3 P@3=2/3 / E2 R@1=1/2 P@1=1, R@3=1/2 P@3=1/3 / E3 0 / E4 제외
    exp = {"R@1": round((1/3 + 1/2 + 0) / 3, 4), "P@1": round((1 + 1 + 0) / 3, 4),
           "R@3": round((2/3 + 1/2 + 0) / 3, 4), "P@3": round((2/3 + 1/3 + 0) / 3, 4), "n_equipment": 3}
    ok = all(r[k] == v for k, v in exp.items())
    return {"ok": ok, "got": {k: r[k] for k in exp}, "expected": exp}


def checks_without_gt(ranked: dict, em) -> dict:
    """정답셋 없이 할 수 있는 점검. 점수가 아니라 출력 특성이다."""
    out = {}
    master = {e: {h["code"] for h in em.equipment[e]["related_hazards"]} for e in em.equipment}
    for m, per in ranked.items():
        lens = [len(v) for v in per.values()]
        row = {"equipment": len(per), "empty_output": sum(n == 0 for n in lens),
               "avg_candidates": round(sum(lens) / max(len(lens), 1), 2), "max_candidates": max(lens) if lens else 0,
               "code_freq_top5": Counter(c for v in per.values() for c in v).most_common(5)}
        if m == "A_llm":
            # 기기마스터를 보지 않은 방법만 마스터와의 겹침을 센다(정답 아님, 내부 일치도).
            agree = [len(set(v[:5]) & master[e]) / len(master[e]) for e, v in per.items() if master.get(e)]
            row["master_overlap_top5_macro"] = round(sum(agree) / len(agree), 4) if agree else None
            row["_master_overlap_note"] = "기기마스터 related_hazards와의 겹침. 기기마스터는 검수 전 초안이고 정답셋이 아니다."
        out[m] = row
    return out


GOLDSET = ROOT.parent / "261115_RAG_지식베이스_DR" / "261116_RAG_위험요인추천_정답셋_v2_DR.jsonl"
# 기기마스터 v1을 쓰는 방법. 정답셋 leakage.in_equipment_master_v1_refs=true 질의에서 누출 경로가 있다.
USES_MASTER_V1 = {"R_index", "B_rag", "B_rag_fill"}


def eval_goldset(ranked: dict, path: Path, ks: list[int], no_evidence: set[str]) -> dict:
    """정답셋 v2(질의 단위). 기기 질의만 평가한다. 작업 질의는 입력 형식이 달라 미평가로 남긴다."""
    gold = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    eq_q = [g for g in gold if g["query"]["type"] == "equipment"]
    subsets = {
        "누출위험_제외(기기 질의, 누출 낮음)": [g for g in eq_q if g["leakage_risk"].startswith("낮음")],
        "누출위험_포함(기기 질의 전체)": eq_q,
        "기본평가_R등급(기기 질의, 누출 높음 3개 포함)": [g for g in eq_q if g["tier"] == "R"],
    }
    out = {"goldset": str(path.name), "queries_total": len(gold), "equipment_queries": len(eq_q),
           "not_evaluated": [{"gold_id": g["gold_id"], "work_label": g["query"]["work_label"],
                              "reason": "작업 질의. 이 파이프라인 입력은 확인된 기기 목록이라 형식이 맞지 않음"}
                             for g in gold if g["query"]["type"] != "equipment"],
           "subsets": {}, "per_query": []}
    for name, qs in subsets.items():
        res = {"queries": [g["gold_id"] for g in qs]}
        for m, per in ranked.items():
            row = {}
            for k in ks:
                rs, ps = zip(*[at_k(per.get(g["query"]["equipment_id"], []), set(g["gold_hazard_codes"]), k) for g in qs])
                row[f"R@{k}"], row[f"P@{k}"] = round(sum(rs) / len(rs), 4), round(sum(ps) / len(ps), 4)
            row["leak_path_queries"] = [g["gold_id"] for g in qs if m in USES_MASTER_V1
                                        and any(ev["leakage"].get("in_equipment_master_v1_refs") for ev in g["evidence"])]
            res[m] = row
        out["subsets"][name] = res
    for g in eq_q:
        e = g["query"]["equipment_id"]
        out["per_query"].append({
            "gold_id": g["gold_id"], "tier": g["tier"], "equipment_id": e, "gold": g["gold_hazard_codes"],
            "leakage_risk": g["leakage_risk"], "index_v2_no_evidence": e in no_evidence,
            "master_v1_ref_leak": any(ev["leakage"].get("in_equipment_master_v1_refs") for ev in g["evidence"]),
            "top5": {m: per.get(e, [])[:5] for m, per in ranked.items()},
            "hits@5": {m: sorted(set(per.get(e, [])[:5]) & set(g["gold_hazard_codes"])) for m, per in ranked.items()}})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--goldset", nargs="?", const=str(GOLDSET))
    a = ap.parse_args()
    cfg = json.loads((ROOT / "config" / "hitl_recommend_config.json").read_text(encoding="utf-8"))
    ks = cfg["eval"]["k_values"]
    st = selftest()
    print("selftest", st)
    if a.selftest:
        return
    assert st["ok"], "평가식 자체 검사 실패"
    em = S04Pipeline(ROOT / "config" / "pipeline_config.json").emap
    rk = json.loads((OUT / "ranked_codes.json").read_text(encoding="utf-8"))
    res = {"generated_at": now_kst(), "model_version": rk["model_version"], "k_values": ks, "selftest": st,
           "checks_without_gt": checks_without_gt(rk["ranked"], em)}
    if a.goldset:
        v2 = json.loads((ROOT.parent / "261115_RAG_지식베이스_DR" / "261116_RAG_기기위험요인인덱스_v2_DR.json").read_text(encoding="utf-8"))
        ne = {(x["equipment_id"] if isinstance(x, dict) else x) for x in v2["no_evidence"]}
        res["goldset_eval"] = eval_goldset(rk["ranked"], Path(a.goldset), ks, ne)
        (OUT / "eval_hitl_goldset_v2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        for n, sub in res["goldset_eval"]["subsets"].items():
            print(n, sub["queries"])
            for m in rk["ranked"]:
                print(f"  {m:12s}", {k: v for k, v in sub[m].items() if k != "leak_path_queries"}, sub[m]["leak_path_queries"] or "")
        return
    if a.gt:
        gt, info = load_gt(Path(a.gt), em)
        res["ground_truth"] = info | {"equipment_with_gt": sum(bool(v) for v in gt.values())}
        res["scores"] = evaluate(rk["ranked"], gt, ks)
        name = "eval_hitl_gt.json"
    else:
        res["scores"] = "정답셋 미준비 — 미실행"
        name = "eval_hitl_nogt.json"
    (OUT / name).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("checks_without_gt", "scores")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
