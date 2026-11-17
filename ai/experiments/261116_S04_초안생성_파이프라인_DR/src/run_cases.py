"""실제 사례 일부로 S04 파이프라인을 돌리고 내부 참고용 비교표를 만든다.

사례 원본(JSONL)은 읽기만 한다. 비교는 '내부 참고용'이며 정확도·현장 성능 지표가 아니다.
uv run --with jsonschema --with referencing --with rfc3339-validator --with rfc3987 python src/run_cases.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_s04 import run_one  # noqa: E402
from s04_pipeline import ROOT, now_kst, tokenize  # noqa: E402

CASES = ROOT.parent / "261113_restaurant_completed_assessments_DR" / "261113_실제사업장_위험성평가사례_8건_DR.jsonl"


def bigram_overlap(a: str, b: str) -> float:
    ta = {t for t in tokenize(a) if len(t) == 2}
    tb = {t for t in tokenize(b) if len(t) == 2}
    return round(len(ta & tb) / len(ta | tb), 3) if ta and tb else 0.0


def main():
    cases = [json.loads(line) for line in open(CASES, encoding="utf-8") if line.strip()]
    picked = [c for c in cases if c.get("project_review_status") == "검수 후보"]
    in_dir = ROOT / "inputs" / "cases"
    in_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in picked:
        req = {
            "request_id": f'case-{c["id"]}-261116', "assessment_id": f'CASE-{c["id"]}', "criteria_version": None,
            "business": {"industry": "음식점"}, "equipment": [],
            "field_input": {"photos": [], "text": c["hazard_summary"], "voice_transcripts": []},
        }
        rp = in_dir / f'{c["id"]}.json'
        rp.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
        out = ROOT / "runs" / "cases" / c["id"]
        summary = run_one(rp, out, quiet=True)
        resp = json.loads((out / "response.json").read_text(encoding="utf-8"))
        items = resp.get("items", [])
        best = max(items, key=lambda i: bigram_overlap(c["hazard_summary"], i["hazard"] + " " + i["description"]), default=None)
        rec_text = " ".join(m["text"] for i in items for m in i["recommended_measures"])
        rows.append({
            "case_id": c["id"], "case_hazard": c["hazard_summary"], "case_control": c["control_summary"],
            "case_before": c["before"], "status": resp["status"], "schema_valid": summary["schema_validation"]["response_valid"],
            "items": [{"work": i["work"], "hazard": i["hazard"], "signal": i["signal"], "off_reason_code": i["off_reason_code"],
                       "recommendation_status": i["recommendation_status"],
                       "recommended": [m["text"] for m in i["recommended_measures"]]} for i in items],
            "hazard_copied_from_input": any(i["hazard"].rstrip("…") in c["hazard_summary"] for i in items),
            "best_hazard_overlap": bigram_overlap(c["hazard_summary"], (best["hazard"] + " " + best["description"]) if best else ""),
            "control_vs_recommended_overlap": bigram_overlap(c["control_summary"], rec_text),
            "error": resp.get("error"),
        })
    out_json = ROOT / "runs" / "cases" / "case_comparison_internal.json"
    out_json.write_text(json.dumps({"generated_at": now_kst(), "note": "내부 참고용. 정확도·현장 성능 지표가 아님. 사례 점수는 원문 척도(가능성×중대성)이며 신호로 환산하지 않음.",
                                    "source": str(CASES.relative_to(ROOT.parent)), "rows": rows}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    lines = ["# 실제 사례 비교 (내부 참고용)", "",
             "> 정확도·현장 성능 지표가 아니다. 사례 점수는 원문 척도이며 신호로 환산하지 않았다. 겹침 값은 문자 2-gram 자카드 유사도로, 의미 일치를 뜻하지 않는다. '입력 복사'는 범용 항목이 입력 문장을 그대로 위험요인으로 쓴 경우라 겹침 1.0이 의미 없다.", "",
             "| 사례 | 사례 위험(요약) | 사례 개선 전 점수 | 상태 | 스키마 | 생성 항목(신호) | 위험 겹침 | 대책 겹침 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        its = "<br>".join(f'{i["work"]}: {i["hazard"]} ({i["signal"]})' for i in r["items"]) or f'없음({(r["error"] or {}).get("code")})'
        b = r["case_before"]
        lines.append(f'| {r["case_id"]} | {r["case_hazard"]} | {b["likelihood"]}×{b["severity"]}={b["score"]} | {r["status"]} | '
                     f'{"통과" if r["schema_valid"] else "실패"} | {its} | {r["best_hazard_overlap"]}{" (입력 복사)" if r["hazard_copied_from_input"] else ""} | {r["control_vs_recommended_overlap"]} |')
    (ROOT / "runs" / "cases" / "case_comparison_internal.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
