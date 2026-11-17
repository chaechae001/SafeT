"""실행 결과가 계약·완료 기준을 지키는지 검사한다(스키마 검증과 별개의 추가 검사).

uv run --with jsonschema --with referencing --with rfc3339-validator --with rfc3987 python src/check_outputs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT  # noqa: E402

LAWS = json.load(open(ROOT.parent / "261115_RAG_지식베이스_DR" / "261115_RAG_법령검증목록_v1_DR.json", encoding="utf-8"))
VERIFIED = {(v["law_name"], v["article"]) for v in LAWS["verified"] if v.get("verification_status") == "검증"}
USER_FIELDS = ("current_measures", "current_none", "confirmed", "selected_measure_ids", "custom_measures",
               "owner_name", "owner_id", "due_date", "expected_signal", "actual_result", "completed_date")


def check_run(run: Path, expect_items: int | None = None) -> list[tuple[str, bool]]:
    resp = json.loads((run / "response.json").read_text(encoding="utf-8"))
    val = json.loads((run / "validation.json").read_text(encoding="utf-8"))
    events = [json.loads(x) for x in (run / "progress_events.jsonl").read_text(encoding="utf-8").splitlines() if x]
    items = resp.get("items", [])
    res = [
        ("스키마 검증 실행됨", val["schema_validation"]["executed"]),
        ("응답 스키마 통과", val["schema_validation"]["response_valid"]),
        ("진행률 이벤트 스키마 통과", val["schema_validation"]["progress_events_valid"]),
        ("진행률 20→40→60→80→100 순서", [e["percent"] for e in events if e["state"] == "done"] == [20, 40, 60, 80, 100]),
        ("사용자 입력 필드 없음(현재 조치 미선택·대책 미체크·담당/예정일 빈 값)", all(k not in i for i in items for k in USER_FIELDS)),
        ("criteria_version = null(팀 확정 전)", resp.get("criteria_version") is None and all(i["criteria_version"] is None for i in items)),
        ("법령은 검증 목록 조항만", all((l["law_name"], l["article_no"]) in VERIFIED for i in items for l in i["laws"])),
        ("빨강·노랑은 추천 3개 또는 failed", all(
            (i["recommendation_status"] == "ok" and len(i["recommended_measures"]) == 3) or i["recommendation_status"] == "failed"
            for i in items if i["signal"] in ("red", "yellow"))),
        ("off는 원인 코드 있음·추천 없음", all(i["off_reason_code"] and not i["recommended_measures"] for i in items if i["signal"] == "off")),
        ("임시 기준 신호는 이유에 '임시' 표시", all("임시" in i["signal_reason"] for i in items if i["signal"] != "off")),
    ]
    if expect_items is not None:
        res.append((f"항목 수 = {expect_items}", len(items) == expect_items))
    return res


def main():
    runs = {"tc01_offline_provisional": 7, "tc01_offline_strict": 7, "tc01_mock_llm": None,
            "tc01_cloud_qwen25vl3b_attempt2": None}
    runs.update({f"cases/{p.name}": None for p in sorted((ROOT / "runs" / "cases").glob("*")) if p.is_dir()})
    report, all_ok = {}, True
    for name, n in runs.items():
        run = ROOT / "runs" / name
        if not (run / "response.json").exists():
            report[name] = [("실행 결과 있음", False)]
            all_ok = False
            continue
        r = check_run(run, n)
        report[name] = r
        all_ok &= all(ok for _, ok in r)
    out = {k: [{"check": c, "pass": ok} for c, ok in v] for k, v in report.items()}
    (ROOT / "runs" / "check_report.json").write_text(json.dumps({"all_pass": all_ok, "runs": out}, ensure_ascii=False, indent=2),
                                                      encoding="utf-8")
    for k, v in report.items():
        bad = [c for c, ok in v if not ok]
        print(f'{k:<32} {"PASS" if not bad else "FAIL: " + "; ".join(bad)}')
    print("ALL PASS" if all_ok else "SOME FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
