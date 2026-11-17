"""Cloud 모델 출력(cloud/outputs/cloud_outputs.json)을 로컬 파이프라인으로 재생해 평가한다.

- 요청 7건 × 시도 3회 × 후처리(off=원래 처리, on=ID 정규화·중복 제거·외국 문자 차단) = 42회.
- 재시도 정책: 시도 1→2→3 순서로, 응답 스키마 통과 + status≠failed + 항목 1개 이상인 첫 시도를 채택.
uv run --with jsonschema --with referencing --with rfc3339-validator --with rfc3987 python src/eval_cloud_replay.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

CLOUD = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs.json").read_text(encoding="utf-8"))
PROMPTS = json.loads((ROOT / "cloud" / "prompts_s04.json").read_text(encoding="utf-8"))


def run(req: dict, rep: dict, attempt: int, pp_on: bool):
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json", mode="replay")
    for k in ("normalize_ids", "filter_input_ids", "dedupe", "script_gate"):
        pipe.cfg["backend"]["llm"]["postprocess"][k] = pp_on
    pipe.replay, pipe.replay_attempt = rep, attempt
    resp = pipe.run(req)
    errs = pipe.validator.errors("s04_draft.response.schema.json", resp)
    items = resp.get("items", [])
    uniq3 = sum(1 for i in items if len({m["text"] for m in i["recommended_measures"]}) == 3)
    return resp, {
        "parse_failed": pipe.parse_failed, "status": resp["status"], "error": (resp.get("error") or {}).get("code"),
        "schema_valid": not errs, "items": len(items), "duplicate_items_removed": pipe.dup_items, "script_rejects": pipe.script_rejects,
        "signals": dict(Counter(i["signal"] for i in items)),
        "recommendation_status": dict(Counter(i["recommendation_status"] for i in items)),
        "items_with_3_distinct_measures": uniq3,
        "items_with_input_evidence": sum(1 for i in items if any(not e.startswith(("D", "CHK")) for e in i["evidence_refs"])),
        "current_candidates_total": sum(len(i["current_measure_candidates"]) for i in items),
        "laws": sum(len(i["laws"]) for i in items),
        "repairs_invalid_output": sum(1 for i in items if i.get("off_reason_code") == "invalid_output"),
    }


def main():
    out_dir = ROOT / "runs" / "cloud_replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    table, chosen = [], {}
    for res in CLOUD["results"]:
        meta = next(p for p in PROMPTS["prompts"] if p["request_id"] == res["request_id"])
        req = json.loads((ROOT / meta["request_file"]).read_text(encoding="utf-8"))
        rep = {**res, "model_id": CLOUD["model_id"], "revision": CLOUD["revision"]}
        for pp_on in (False, True):
            tag = "pp_on" if pp_on else "pp_off"
            picked = None
            for a in range(len(res["attempts"])):
                resp, m = run(req, rep, a, pp_on)
                (out_dir / tag).mkdir(exist_ok=True)
                (out_dir / tag / f'{res["request_id"]}_attempt{a + 1}.json').write_text(
                    json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
                att = res["attempts"][a]
                row = {"request_id": res["request_id"], "postprocess": tag, "attempt": a + 1,
                       "output_tokens": att["output_tokens"], "seconds": att["seconds"], **m}
                table.append(row)
                ok = m["schema_valid"] and m["status"] != "failed" and m["items"] >= 1
                if picked is None and ok:
                    picked = a + 1
            chosen[f'{res["request_id"]}|{tag}'] = picked
    summary = {}
    for tag in ("pp_off", "pp_on"):
        rows = [r for r in table if r["postprocess"] == tag]
        first = [r for r in rows if r["attempt"] == 1]
        summary[tag] = {
            "runs": len(rows),
            "json_parse_fail": sum(r["parse_failed"] for r in rows),
            "schema_valid": sum(r["schema_valid"] for r in rows),
            "status_failed": sum(r["status"] == "failed" for r in rows),
            "usable(schema ok & ≥1 item)": sum(r["schema_valid"] and r["status"] != "failed" and r["items"] >= 1 for r in rows),
            "attempt1_usable": sum(r["schema_valid"] and r["status"] != "failed" and r["items"] >= 1 for r in first),
            "after_retry_usable_requests": sum(1 for k, v in chosen.items() if k.endswith(tag) and v),
            "requests": len(first),
            "duplicate_items_removed": sum(r["duplicate_items_removed"] for r in rows),
            "script_rejects": sum(r["script_rejects"] for r in rows),
            "signals_total": dict(sum((Counter(r["signals"]) for r in rows), Counter())),
            "items_total": sum(r["items"] for r in rows),
            "items_with_3_distinct_measures": sum(r["items_with_3_distinct_measures"] for r in rows),
            "rec_ok_items": sum(r["recommendation_status"].get("ok", 0) for r in rows),
        }
    result = {"generated_at": now_kst(), "model_id": CLOUD["model_id"], "revision": CLOUD["revision"],
              "retry_policy": "시도 1→2→3 중 스키마 통과·status≠failed·항목≥1인 첫 시도", "summary": summary,
              "chosen_attempt": chosen, "rows": table}
    (out_dir / "cloud_replay_eval.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(chosen, ensure_ascii=False))
    for r in table:
        print(r["postprocess"], r["request_id"][:22], r["attempt"], "parse_fail" if r["parse_failed"] else "", r["status"], r["error"] or "",
              "valid" if r["schema_valid"] else "INVALID", "items", r["items"], "dup", r["duplicate_items_removed"], "script", r["script_rejects"],
              r["signals"], r["recommendation_status"], "uniq3", r["items_with_3_distinct_measures"])


if __name__ == "__main__":
    main()
