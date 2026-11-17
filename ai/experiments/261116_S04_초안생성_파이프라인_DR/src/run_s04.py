"""S04 초안 생성 실행기.

예)
uv run --with jsonschema --with referencing --with rfc3339-validator --with rfc3987 \
  python src/run_s04.py --request inputs/tc01_request.json --out runs/tc01_offline
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402


def dump(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def run_one(request_path: Path, out_dir: Path, mode=None, criteria_mode=None, mock_llm=None, quiet=False,
            replay=None, attempt=0) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json", mode=mode, criteria_mode=criteria_mode,
                       mock_llm_path=mock_llm)
    if replay is not None:
        pipe.replay, pipe.replay_attempt = replay, attempt

    def show(ev):
        if not quiet:
            print(f'[{ev["percent"]:>3}%] {ev["stage"]:<20} {ev["label"]} ({ev["state"]})')

    started = now_kst()
    resp = pipe.run(request, on_progress=show)
    dump(out_dir / "request.json", request)
    dump(out_dir / "response.json", resp)
    if pipe.raw_llm:
        dump(out_dir / "raw_llm.json", pipe.raw_llm)

    # 100%: 프로토타입은 백엔드 대신 로컬 파일 저장 성공 후에 보낸다.
    if resp["status"] != "failed" and (out_dir / "response.json").exists():
        pipe._progress(resp["request_id"], "save_draft")
        pipe._log("save_draft", "로컬 파일 저장 성공(백엔드 저장 대체)", path=str(out_dir / "response.json"))

    v = pipe.validator
    resp_errs = v.errors("s04_draft.response.schema.json", resp)
    req_errs = v.errors("s04_draft.request.schema.json", request)
    ev_errs = [e for ev in pipe.events if ev["stage"] != "pipeline"
               for e in v.errors("common.schema.json", {k: x for k, x in ev.items() if k != "emitted_at"},
                                 "/$defs/ProgressEvent")]
    items = resp.get("items", [])
    summary = {
        "run_started_at": started, "run_finished_at": now_kst(), "request": str(request_path.relative_to(ROOT)),
        "mode": pipe.mode, "criteria_mode": pipe.cfg["signal"]["criteria_mode"], "model_version": pipe.model_version,
        "schema_validation": {
            "executed": v.available, "not_executed_reason": v.reason or None,
            "format_checkers": getattr(v, "checked_formats", []),
            "request_valid": not req_errs, "response_valid": not resp_errs, "progress_events_valid": not ev_errs,
            "response_errors": resp_errs[:20], "progress_errors": ev_errs[:20],
        },
        "status": resp["status"], "item_count": len(items), "llm_parse_failed": pipe.parse_failed,
        "error": resp.get("error"),
        "signals": dict(Counter(i["signal"] for i in items)),
        "recommendation_status": dict(Counter(i["recommendation_status"] for i in items)),
        "laws_attached": sum(len(i["laws"]) for i in items),
        "progress": [f'{e["percent"]}:{e["stage"]}:{e["state"]}' for e in pipe.events],
        "ui_initial_state_check": {
            "user_fields_absent": all(k not in i for i in items for k in (
                "current_measures", "current_none", "confirmed", "selected_measure_ids", "custom_measures",
                "owner_name", "owner_id", "due_date", "expected_signal")),
            "note": "AI 응답에 사용자 입력 필드가 없으면 화면 초기 상태는 현재 조치 미선택·대책 미체크·담당자/예정일 빈 값이다.",
        },
    }
    dump(out_dir / "validation.json", summary)
    with open(out_dir / "progress_events.jsonl", "w", encoding="utf-8") as f:
        for ev in pipe.events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    with open(out_dir / "pipeline_log.jsonl", "w", encoding="utf-8") as f:
        for row in pipe.log:
            f.write(json.dumps(row, ensure_ascii=False, default=list) + "\n")

    # 비밀값 유출 검사(키 값 자체는 출력하지 않는다)
    markers = pipe.llm.secret_markers() if pipe.llm else []
    if markers:
        for p in out_dir.iterdir():
            if any(m in p.read_text(encoding="utf-8", errors="ignore") for m in markers):
                raise SystemExit(f"비밀값이 출력 파일에 포함됨: {p.name} — 파일을 확인하세요.")
    if not quiet:
        print(json.dumps({k: summary[k] for k in ("status", "item_count", "signals", "recommendation_status",
                                                   "laws_attached")}, ensure_ascii=False))
        print("schema:", json.dumps(summary["schema_validation"], ensure_ascii=False)[:400])
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--mode", choices=["offline_template", "llm", "mock_llm", "replay"])
    ap.add_argument("--criteria-mode", choices=["strict", "provisional_guide_example"])
    ap.add_argument("--mock-llm", type=Path)
    ap.add_argument("--replay", type=Path, help="Cloud 출력 파일(cloud_outputs.json)")
    ap.add_argument("--attempt", type=int, default=0)
    a = ap.parse_args()
    req = a.request if a.request.is_absolute() else ROOT / a.request
    out = a.out if a.out.is_absolute() else ROOT / a.out
    rep = None
    if a.replay:
        allrep = json.loads(a.replay.read_text(encoding="utf-8"))
        req_id = json.loads(req.read_text(encoding="utf-8"))["request_id"]
        rep = next(r for r in allrep["results"] if r["request_id"] == req_id)
        rep = {**rep, "model_id": allrep["model_id"], "revision": allrep["revision"]}
    run_one(req, out, a.mode, a.criteria_mode, a.mock_llm, replay=rep, attempt=a.attempt)


if __name__ == "__main__":
    main()
