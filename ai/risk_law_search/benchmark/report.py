"""측정 결과(JSON) → 비교 표 Markdown 조각(표만). 해석 문장은 사람이 붙인다.

  python ai/risk_law_search/benchmark/report.py <결과 폴더>
"""
import json
import sys
from pathlib import Path

ORDER = ["C1", "C2", "C3", "C4", "C5", "K0"]


def pct(x):
    return "–" if x is None else f"{x * 100:.0f}%"


def main():
    folder = Path(sys.argv[1])
    rs = [json.loads((folder / f"{c}.json").read_text(encoding="utf-8")) for c in ORDER if (folder / f"{c}.json").exists()]
    out = []
    out.append("| # | 조합 | 카드 Top-1 | 카드 Top-3 | 카드 MRR | 선택 결과 적중 | 선택 결과 정밀도 | 정상 입력 기준 미달 | 무관 입력 통과 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for r in rs:
        s = r["summary"]
        out.append(f"| {r['config']} | {r['label']} | {pct(s['card_top1'])} | {pct(s['card_top3'])} | {s['card_mrr']:.2f} | "
                   f"{pct(s['chosen_hit'])} | {pct(s['chosen_precision'])} | {pct(s['pos_low_confidence'])} | {pct(s['neg_false_pass'])} |")
    out.append("")
    out.append("| # | 조합 | 위험요인별 법령(analyze) | 법령 검색 1순위(search) | 조문 순위 Top-1 | 조문 순위 Top-3 | 무관 입력에 법령 반환 |")
    out.append("|---|---|---|---|---|---|---|")
    for r in rs:
        s = r["summary"]
        out.append(f"| {r['config']} | {r['label']} | {pct(s['risk_law_hit'])} | {pct(s['search_law_hit'])} | "
                   f"{pct(s['law_top1'])} | {pct(s['law_top3'])} | {pct(s['neg_false_law'])} |")
    out.append("")
    out.append("| # | 조합 | 준비 시간(색인+연결) | 그중 재정렬 연결 | 검색 1건 평균 | 중앙값 | p95 | 최대 | 최대 메모리 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for r in rs:
        s = r["summary"]
        out.append(f"| {r['config']} | {r['label']} | {r['build_s']:.0f}초 | {r['rerank_links_s']:.0f}초 | {s['ms_mean']:.0f} ms | "
                   f"{s['ms_p50']:.0f} ms | {s['ms_p95']:.0f} ms | {s['ms_max']:.0f} ms | {r['peak_mb'] / 1024:.1f} GB |")
    out.append("")
    out.append("문항별 카드 Top-1 적중(O/X, 음성 입력은 통과 여부: 통과=X)")
    out.append("")
    out.append("| 문항 | " + " | ".join(r["config"] for r in rs) + " |")
    out.append("|---|" + "---|" * len(rs))
    for k, it in enumerate(rs[0]["items"]):
        cells = []
        for r in rs:
            p = r["items"][k]
            cells.append(("X" if p["false_pass"] else "O") if p["negative"] else ("O" if p["card_top1"] else "X"))
        out.append(f"| {it['id']} {it['text']} | " + " | ".join(cells) + " |")
    print("\n".join(out))


if __name__ == "__main__":
    main()
