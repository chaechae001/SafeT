"""3차 개선 내부 비교: 지난 라운드(기준선·A·AB2)와 A2+C1·A2+C2(불일치 필터 off/on)를 같은 지표로 비교한다.
모델 호출 없음(Cloud 출력 v1~v5 재생). TC01 라벨링용 CSV도 만든다.

추가 지표
- 기기-위험 불일치(사후, 모든 변형 같은 규칙): 항목 문장(작업·위험요인·원인·설명)에서 기기마스터 기기를 찾고,
  항목 위험 분류 코드(위험요인+사고 유형)가 그 기기의 related_hazards 코드와 하나도 겹치지 않으면 불일치.
  기기를 못 찾거나 분류 코드가 없으면 판단 안 함.
- 추천 대책 생성 성공: 빨강·노랑 항목 중 recommendation_status=ok 수 / 빨강·노랑 항목 수.
- 출처 ID 보유율: evidence_refs에 점검표 행(CHK-) ID가 있는 항목 비율.
uv run --with jsonschema --with referencing --with rfc3339-validator --with rfc3987 python src/eval_round3.py
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_improvements as E  # noqa: E402
from dump_prompts_v3 import A2, A3, REQS  # noqa: E402
from equipment_map import EquipmentMap  # noqa: E402
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

V4 = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs_v4.json").read_text(encoding="utf-8"))
V5 = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs_v5.json").read_text(encoding="utf-8"))
V6 = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs_v6.json").read_text(encoding="utf-8"))
V7 = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs_v7.json").read_text(encoding="utf-8"))
SRC = {"A2": (A2, V4, V5), "A3": (A3, V6, V7)}
NEW = {f"{b}+{c.upper()}{'+F' if f else ''}": (b, c, f) for b in ("A2", "A3") for c in ("c2", "c1") for f in (False, True)}


def calls_for(request_id: str, stage: str, base: str):
    _, s1, s2 = SRC[base]
    out, used = {}, []
    for r in s1["results"] + (s2["results"] if stage == "c1" else []):
        if r["request_id"] == request_id:
            idx = (r["accepted_attempt"] - 1) if r.get("accepted_attempt") else len(r["attempts"]) - 1
            out[r["unit_id"]] = {"messages": r["messages"], "attempts": r["attempts"], "use_attempt": idx}
            used.append((r, idx))
    return out, used


def posthoc_mismatch(em: EquipmentMap, items: list[dict]):
    n, judged, rows = 0, 0, []
    for i in items:
        text = " ".join([i["work"], i["hazard"], i["cause"], i["description"]])
        eids = em.match(text)
        codes = em.classify(f'{i["hazard"]} {i["accident_type"]}')
        if not eids or not codes:
            continue
        judged += 1
        allowed = em.codes(eids)
        if not set(codes) & set(allowed):
            n += 1
            rows.append({"hazard": i["hazard"], "equipment": eids, "item_codes": codes, "equipment_codes": list(allowed)})
    return n, judged, rows


def extra_metrics(em, items):
    mm, judged, mm_rows = posthoc_mismatch(em, items)
    ry = [i for i in items if i["signal"] in ("red", "yellow")]
    return {
        "mismatch_posthoc": mm, "mismatch_judged": judged, "mismatch_rows": mm_rows,
        "red_yellow": len(ry), "rec_success": sum(i["recommendation_status"] == "ok" for i in ry),
        "source_id_items": sum(any(e.startswith("CHK-") for e in i["evidence_refs"]) for i in items),
    }


def run_new(name: str, req_meta: dict, em):
    base, stage, filt = NEW[name]
    req = json.loads((ROOT / req_meta["request_file"]).read_text(encoding="utf-8"))
    calls, used = calls_for(req["request_id"], stage, base)
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json", mode="replay")
    pipe.cfg["backend"]["llm"].update(SRC[base][0])
    pipe.cfg["backend"]["llm"]["measure_stage"] = stage
    pipe.cfg["backend"]["llm"]["postprocess"]["mismatch_filter"] = filt
    pipe.replay = {"model_id": V4["model_id"], "revision": V4["revision"]}
    pipe.replay_calls = calls
    resp = pipe.run(req)
    errs = pipe.validator.errors("s04_draft.response.schema.json", resp)
    items = resp.get("items", [])
    cov, tot, hit = E.coverage(req["request_id"], items)
    # 시간: 항목 생성 호출 + (C1) 실제로 쓰인 대책 호출
    used_units = {r["unit_id"] for r in [x[0] for x in used] if not r["unit_id"].startswith("c1:")}
    used_c1 = {x["unit_id"] for x in pipe.raw_llm if x["unit_id"].startswith("c1:")}
    sec = sum(a["seconds"] for r, idx in used if r["unit_id"] in used_units | used_c1 for a in r["attempts"][: idx + 1])
    m = {
        "variant": name, "request_id": req["request_id"], "calls": len(used_units) + len(used_c1),
        "retries": sum(idx for r, idx in used if r["unit_id"] in used_units | used_c1),
        "calls_json_failed_final": pipe.parse_fail_calls, "schema_valid": not errs, "status": resp["status"],
        "error": (resp.get("error") or {}).get("code"), "items": len(items), "coverage": cov, "coverage_total": tot,
        "coverage_hits": hit, "duplicates_removed": pipe.dup_items, "script_rejects": pipe.script_rejects,
        "signals": dict(Counter(i["signal"] for i in items)),
        "rec_ok": sum(i["recommendation_status"] == "ok" for i in items),
        "rec_failed": sum(i["recommendation_status"] == "failed" for i in items),
        "items_with_kb_source": sum(any(e.startswith("CHK-") for e in i["evidence_refs"]) for i in items),
        "gen_seconds": round(sec, 1), "mismatch_detected_pipeline": pipe.mismatch_detected,
        "mismatch_removed": pipe.mismatch_removed, "mismatch_log": pipe.mismatch_log,
        "c1_invalid": pipe.c1_invalid, "c1_reasons": pipe.c1_reasons,
    }
    return resp, m


def main():
    out_dir = ROOT / "runs" / "improve_round3"
    out_dir.mkdir(parents=True, exist_ok=True)
    em = EquipmentMap(S04Pipeline(ROOT / "config" / "pipeline_config.json").kb.rows)
    rows, resps = [], {}
    for v in ["baseline", "A", "AB2"]:
        for meta in E.P1["prompts"]:
            resp, m = E.run_variant(v, meta)
            m.update(extra_metrics(em, resp.get("items", [])))
            rows.append(m)
            resps[(v, meta["request_id"])] = resp
    for v in NEW:
        (out_dir / v).mkdir(exist_ok=True)
        for meta in E.P1["prompts"]:
            resp, m = run_new(v, meta, em)
            m.update(extra_metrics(em, resp.get("items", [])))
            rows.append(m)
            resps[(v, meta["request_id"])] = resp
            (out_dir / v / f'{meta["request_id"]}.json').write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    off = json.loads((ROOT / "runs" / "tc01_offline_provisional" / "response.json").read_text(encoding="utf-8"))
    resps[("offline_template", "tc01-261116-0001")] = off

    order = ["baseline", "A", "AB2"] + list(NEW)
    summ = {}
    for v in order:
        r = [x for x in rows if x["variant"] == v]
        tc = next(x for x in r if x["request_id"].startswith("tc01"))
        ry = sum(x["red_yellow"] for x in r)
        it = sum(x["items"] for x in r)
        summ[v] = {
            "tc01_items": tc["items"], "tc01_coverage": f'{tc["coverage"]}/{tc["coverage_total"]}',
            "tc01_signals": tc["signals"], "tc01_mismatch_posthoc": f'{tc["mismatch_posthoc"]}/{tc["mismatch_judged"]}',
            "tc01_rec_success": f'{tc["rec_success"]}/{tc["red_yellow"]}', "tc01_calls": tc["calls"],
            "tc01_retries": tc["retries"], "tc01_gen_seconds": tc["gen_seconds"], "tc01_duplicates_removed": tc["duplicates_removed"],
            "all_schema_valid": f'{sum(x["schema_valid"] for x in r)}/{len(r)}',
            "all_status_failed": sum(x["status"] == "failed" for x in r),
            "all_calls": sum(x["calls"] for x in r), "all_retries": sum(x["retries"] for x in r),
            "all_items": it, "all_duplicates_removed": sum(x["duplicates_removed"] for x in r),
            "all_mismatch_posthoc": f'{sum(x["mismatch_posthoc"] for x in r)}/{sum(x["mismatch_judged"] for x in r)}',
            "all_mismatch_removed": sum(x.get("mismatch_removed", 0) for x in r),
            "all_rec_success": f'{sum(x["rec_success"] for x in r)}/{ry}',
            "all_c1_invalid": sum(x.get("c1_invalid", 0) for x in r),
            "all_source_id_rate": f'{sum(x["source_id_items"] for x in r)}/{it}',
            "all_gen_seconds": round(sum(x["gen_seconds"] for x in r), 1),
            "signals_total": dict(sum((Counter(x["signals"]) for x in r), Counter())),
        }
    res = {"generated_at": now_kst(), "note": "내부 비교. 평가 7건. 성능 향상으로 단정하지 않는다. 적절성은 작성자(비전문가) 검토.",
           "model_id": V4["model_id"], "revision": V4["revision"], "summary": summ, "rows": rows}
    (out_dir / "round3_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    # TC01 라벨링용 CSV(팀·전문가 입력 칸은 비움)
    review = json.loads((ROOT / "runs" / "improve_round3" / "author_review_tc01.json").read_text(encoding="utf-8")) \
        if (ROOT / "runs" / "improve_round3" / "author_review_tc01.json").exists() else {}
    cols = ["row_id", "variant", "item_key", "work", "hazard", "accident_type", "cause", "signal", "signal_reason",
            "recommendation_status", "recommended_measures", "source_ids", "author_review_비전문가", "author_note",
            "expert_적절성(적절/부분/부적절)", "expert_기기위험일치(Y/N)", "expert_신호적절(Y/N)", "expert_대책적절(Y/N)",
            "expert_누락위험", "expert_의견", "검토자", "검토일"]
    with open(out_dir / "261116_TC01_항목평가표_라벨링용_DR.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        n = 0
        for v in ["offline_template", "baseline", "A", "AB2", "A2+C1+F", "A3+C1+F", "A3+C2+F"]:
            for i in resps[(v, "tc01-261116-0001")]["items"]:
                n += 1
                rv = review.get(f'{v}|{i["hazard"]}', {})
                w.writerow([f"R{n:03d}", v, i["item_key"], i["work"], i["hazard"], i["accident_type"], i["cause"], i["signal"],
                            i["signal_reason"], i["recommendation_status"], " / ".join(m["text"] for m in i["recommended_measures"]),
                            " ".join(e for e in i["evidence_refs"] if e.startswith("CHK-")),
                            rv.get("judgement", ""), rv.get("note", ""), "", "", "", "", "", "", "", ""])
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    for x in rows:
        if x["request_id"].startswith("tc01") or x["variant"] in NEW:
            print(x["variant"], x["request_id"][:20], "items", x["items"], "mm", x["mismatch_posthoc"], "/", x["mismatch_judged"],
                  "rec", x["rec_success"], "/", x["red_yellow"], "src", x["source_id_items"], "c1inv", x.get("c1_invalid"),
                  x.get("c1_reasons"), "removed", x.get("mismatch_removed"))
    for v in ["A2+C1+F", "A3+C1", "A3+C1+F", "A3+C2+F"]:
        for i in resps[(v, "tc01-261116-0001")]["items"]:
            print("TC01", v, "|", i["work"], "|", i["hazard"], "|", i["accident_type"], "|", i["signal"], i["recommendation_status"],
                  "|", [m["text"][:28] for m in i["recommended_measures"]])


if __name__ == "__main__":
    main()
