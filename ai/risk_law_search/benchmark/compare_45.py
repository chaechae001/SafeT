"""우리 위험요인 + 법령 찾기 비교: A(현재, 카드–법령 연결) vs B(#45 방식, law_kure.KureLawFinder) vs C(B+주제 확인).

  python ai/risk_law_search/benchmark/compare_45.py --out <결과 폴더>

- 위험요인은 A·B 모두 같은 analyze(keyword 모드) 결과다. 다른 것은 법령 찾기뿐이다. 화면(--law-alt kure45)과 같은 코드다.
- B는 검색 단계만이다(AI 판정 없음). #45 최종 결과는 EXAONE이 상위 6개 중 근거를 고른 것이므로
  b_top6(후보 6개 안에 정답 포함)이 AI 판정의 상한이다.
- 정답: gold_v0.json(AI 보조·검토 전). 법령 지표는 첫 위험요인 기준(bench.py와 같음).
- b_nolaw_attached: B는 항상 후보 6개를 내므로 검색 단계에서는 1.0이다. AI 판정이 '근거 부족'으로 거를 수 있으나 측정하지 않았다.
- 결과 파일은 새 파일로만 만든다.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from ai.risk_law_search.engine import Engine  # noqa: E402
from ai.risk_law_search.law_kure import KureLawFinder  # noqa: E402

AS_OF = "2026-11-20"
EXTRA = ["식칼이 떨어짐", "칼 튀김기 선반 바닥", "선반 위 물건이 떨어짐", "사다리에서 떨어짐"]


def hit(k, gold):
    return bool(k) and any(g == k or (g.endswith(":*") and g[:-2] == k.split(":")[0]) for g in gold)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out) / "compare_45.json"
    if out.exists():
        raise SystemExit(f"{out} 이미 있음(덮어쓰지 않음)")
    eng = Engine(ROOT / "docs" / "chroma", as_of=AS_OF, mode="keyword", log=lambda m: None)
    eng.alt_law = KureLawFinder(eng)
    art = lambda law: f"{law['doc_no']}:{eng.unit_by_id[law['id']]['article']}" if law else None
    gold = json.loads((Path(__file__).with_name("gold_v0.json")).read_text(encoding="utf-8"))
    items, ms = [], []
    for it in gold["items"] + [dict(id=f"X{n}", text=t, cards=None, laws=None) for n, t in enumerate(EXTRA, 1)]:
        t0 = time.perf_counter()
        units = eng.analyze(it["text"])["units"]
        ms.append((time.perf_counter() - t0) * 1000)
        row = dict(id=it["id"], text=it["text"], risks=[])
        for u in units:
            for r in u["risks"]:
                b = r["law_alt"]["candidates"]
                c = r["law_alt_topic"]["candidates"]
                row["risks"].append(dict(unit=u["text"], card=r["card_id"], risk_type=r["risk_type"], title=r["title"],
                                         a_law=art(r["law"]), a_title=r["law"]["article_title"] if r["law"] else None,
                                         b_laws=[art(x) for x in b], b_titles=[x["article_title"] for x in b],
                                         c_law=art(c[0]) if c else None, c_title=c[0]["article_title"] if c else None))
        if it["laws"] and row["risks"]:
            f = row["risks"][0]
            row.update(a_hit=hit(f["a_law"], it["laws"]), b_top1=hit(f["b_laws"][0], it["laws"]),
                       b_top6=any(hit(k, it["laws"]) for k in f["b_laws"]), c_hit=hit(f["c_law"], it["laws"]))
        elif it["cards"] and row["risks"]:
            row.update(a_attached=row["risks"][0]["a_law"] is not None, c_attached=row["risks"][0]["c_law"] is not None)
        items.append(row)
    law = [r for r in items if "a_hit" in r]
    nolaw = [r for r in items if "a_attached" in r]
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    summary = dict(n_law=len(law), a_hit=mean([r["a_hit"] for r in law]), b_top1=mean([r["b_top1"] for r in law]),
                   b_top6=mean([r["b_top6"] for r in law]), c_hit=mean([r["c_hit"] for r in law]), n_nolaw=len(nolaw),
                   a_nolaw_attached=mean([r["a_attached"] for r in nolaw]), b_nolaw_attached=1.0 if nolaw else None,
                   c_nolaw_attached=mean([r["c_attached"] for r in nolaw]),
                   analyze_ms_mean=round(sum(ms) / len(ms), 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8") as f:
        json.dump(dict(as_of=AS_OF, gold=gold["version"], hazard_mode="keyword", b=eng.alt_law.info(),
                       summary=summary, items=items), f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
