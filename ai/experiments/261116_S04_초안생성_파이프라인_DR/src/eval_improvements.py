"""기준선(1차 Cloud 단일 호출)과 개선 A·B·AB를 같은 조건으로 비교한다(내부 비교, 모델 호출 없음).

- 기준선: cloud/outputs/cloud_outputs.json. 3회 시도 중 JSON 파싱이 되는 첫 시도를 채택(개선 실험의 Cloud 재시도 규칙과 같음).
  처리 시간·재시도는 채택 시도까지만 센다.
- 개선 1차: cloud/outputs/cloud_outputs_v2.json (A·B·AB), 2차: cloud_outputs_v3.json (B2·AB2, 후보 프롬프트 2판).
  Cloud에서 JSON 파싱 실패 시에만 재시도.
- 후처리는 모두 현재 설정(ID 정규화·중복 제거·외국 문자 차단)으로 같다.
- 커버리지 키워드는 이번 비교를 위해 정한 내부 평가 기준이다(안전 기준 아님).
uv run --with jsonschema --with referencing --with rfc3339-validator --with rfc3987 python src/eval_improvements.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dump_prompts_v2 import VARIANTS  # noqa: E402
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

V1 = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs.json").read_text(encoding="utf-8"))
V2 = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs_v2.json").read_text(encoding="utf-8"))
V3 = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs_v3.json").read_text(encoding="utf-8"))
P1 = json.loads((ROOT / "cloud" / "prompts_s04.json").read_text(encoding="utf-8"))

COVERAGE = {
    "tc01-261116-0001": {"튀김기": ["튀김", "기름"], "가스레인지": ["가스"], "냉장고·식자재 운반": ["냉장", "식자재", "운반", "상자", "중량"],
                         "칼·도마": ["칼", "도마", "베임", "절단", "손질"], "염지기": ["염지"], "바닥": ["바닥", "미끄", "넘어"]},
    "case-FOOD_A_01-261116": {"멀티탭·전기": ["멀티탭", "전선", "전기", "감전", "콘센트"]},
    "case-FOOD_A_02-261116": {"LPG 용기": ["LPG", "용기"]},
    "case-FOOD_A_04-261116": {"가스 배관·전선": ["배관", "전선"]},
    "case-CAFE_B_01-261116": {"투명 출입문": ["출입문", "유리문", "문"]},
    "case-KITCHEN_N_01-261116": {"분전반": ["분전반", "감전", "전기"]},
    "case-KITCHEN_N_02-261116": {"분전반": ["분전반", "감전", "전기"]},
}


VARS = ["baseline", "A", "B", "AB", "B2", "AB2"]


def first_ok(attempts):
    for i, a in enumerate(attempts):
        if S04Pipeline.parse_model_json(a["content"])[0] is not None:
            return i
    return len(attempts) - 1


def replay_calls_for(variant: str, request_id: str):
    if variant == "baseline":
        r = next(x for x in V1["results"] if x["request_id"] == request_id)
        idx = first_ok(r["attempts"])
        return {"all": {"messages": r["messages"], "attempts": r["attempts"], "use_attempt": idx}}, [(r, idx)]
    out, used = {}, []
    for r in V2["results"] + V3["results"]:
        if r["variant"] == variant and r["request_id"] == request_id:
            idx = (r["accepted_attempt"] - 1) if r["accepted_attempt"] else len(r["attempts"]) - 1
            out[r["unit_id"]] = {"messages": r["messages"], "attempts": r["attempts"], "use_attempt": idx}
            used.append((r, idx))
    return out, used


def coverage(request_id: str, items: list[dict]):
    units = COVERAGE[request_id]
    hit = {}
    for u, kws in units.items():
        hit[u] = any(any(k in " ".join([i["work"], i["hazard"], i["cause"], i["description"]]) for k in kws) for i in items)
    return sum(hit.values()), len(units), hit


def run_variant(variant: str, req_meta: dict):
    req = json.loads((ROOT / req_meta["request_file"]).read_text(encoding="utf-8"))
    calls, used = replay_calls_for(variant, req["request_id"])
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json", mode="replay")
    if variant != "baseline":
        pipe.cfg["backend"]["llm"].update(VARIANTS[variant])
    pipe.replay = {"model_id": V1["model_id"], "revision": V1["revision"]}
    pipe.replay_calls = calls
    resp = pipe.run(req)
    errs = pipe.validator.errors("s04_draft.response.schema.json", resp)
    items = resp.get("items", [])
    cov, tot, hit = coverage(req["request_id"], items)
    gen_sec = sum(a["seconds"] for r, idx in used for a in r["attempts"][: idx + 1])
    out_tok = sum(a["output_tokens"] for r, idx in used for a in r["attempts"][: idx + 1])
    return resp, {
        "variant": variant, "request_id": req["request_id"], "calls": len(used),
        "retries": sum(idx for _, idx in used), "calls_json_failed_final": pipe.parse_fail_calls,
        "schema_valid": not errs, "status": resp["status"], "error": (resp.get("error") or {}).get("code"),
        "items": len(items), "coverage": cov, "coverage_total": tot, "coverage_hits": hit,
        "duplicates_removed": pipe.dup_items, "script_rejects": pipe.script_rejects,
        "signals": dict(Counter(i["signal"] for i in items)),
        "rec_ok": sum(i["recommendation_status"] == "ok" for i in items),
        "rec_failed": sum(i["recommendation_status"] == "failed" for i in items),
        "items_with_kb_source": sum(any(e.startswith("CHK-") for e in i["evidence_refs"]) for i in items),
        "current_candidates": sum(len(i["current_measure_candidates"]) for i in items),
        "laws": sum(len(i["laws"]) for i in items),
        "gen_seconds": round(gen_sec, 1), "output_tokens": out_tok,
    }


def main():
    out_dir = ROOT / "runs" / "improve_AB"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for v in VARS:
        (out_dir / v).mkdir(exist_ok=True)
        for meta in P1["prompts"]:
            resp, m = run_variant(v, meta)
            (out_dir / v / f'{meta["request_id"]}.json').write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
            rows.append(m)
    summ = {}
    for v in VARS:
        r = [x for x in rows if x["variant"] == v]
        tc = next(x for x in r if x["request_id"].startswith("tc01"))
        cs = [x for x in r if not x["request_id"].startswith("tc01")]
        summ[v] = {
            "tc01_items": tc["items"], "tc01_coverage": f'{tc["coverage"]}/{tc["coverage_total"]}',
            "tc01_signals": tc["signals"], "tc01_rec_ok": tc["rec_ok"], "tc01_calls": tc["calls"],
            "tc01_retries": tc["retries"], "tc01_gen_seconds": tc["gen_seconds"],
            "tc01_duplicates_removed": tc["duplicates_removed"], "tc01_schema_valid": tc["schema_valid"],
            "cases_coverage": f'{sum(x["coverage"] for x in cs)}/{sum(x["coverage_total"] for x in cs)}',
            "cases_items": sum(x["items"] for x in cs), "cases_rec_ok": sum(x["rec_ok"] for x in cs),
            "all_schema_valid": f'{sum(x["schema_valid"] for x in r)}/{len(r)}',
            "all_status_failed": sum(x["status"] == "failed" for x in r),
            "all_calls": sum(x["calls"] for x in r), "all_retries": sum(x["retries"] for x in r),
            "all_calls_json_failed_final": sum(x["calls_json_failed_final"] for x in r),
            "all_duplicates_removed": sum(x["duplicates_removed"] for x in r),
            "all_script_rejects": sum(x["script_rejects"] for x in r),
            "all_items_with_kb_source": sum(x["items_with_kb_source"] for x in r),
            "all_items": sum(x["items"] for x in r),
            "all_gen_seconds": round(sum(x["gen_seconds"] for x in r), 1),
            "signals_total": dict(sum((Counter(x["signals"]) for x in r), Counter())),
        }
    res = {"generated_at": now_kst(), "note": "내부 비교. 평가 대상 7건(합성 1, AI 요약 사례 6). 성능 향상으로 단정하지 않는다.",
           "model_id": V1["model_id"], "revision": V1["revision"], "coverage_keywords": COVERAGE,
           "summary": summ, "rows": rows}
    (out_dir / "improve_AB_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    for x in rows:
        print(x["variant"], x["request_id"][:22], "calls", x["calls"], "retry", x["retries"], x["status"], "items", x["items"],
              "cov", f'{x["coverage"]}/{x["coverage_total"]}', "dup", x["duplicates_removed"], "rec_ok", x["rec_ok"],
              "kb", x["items_with_kb_source"], "sec", x["gen_seconds"])


if __name__ == "__main__":
    main()
