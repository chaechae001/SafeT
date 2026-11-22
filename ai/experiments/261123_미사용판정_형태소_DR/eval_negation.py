"""변형 회귀셋으로 현재 체크아웃의 미사용 판정(text_candidates)을 평가한다.

  python ai/experiments/261123_미사용판정_형태소_DR/eval_negation.py --label after --out <json>
"""
import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from ai.assessment_authoring.retrieval_adapter import text_candidates  # noqa: E402

SET = HERE / "261123_미사용판정_변형셋_v1_DR.json"
HOLDOUT = HERE / "261123_미사용판정_검증셋_holdout_v1_DR.json"


def judge(item):
    hits, denied = text_candidates(dict(id=item["id"], text=item["text"]), [])
    got = dict(FRY=["FRY" in hits, denied], **{sid: sid in hits for sid in item["expected"] if sid != "FRY"})
    return got, got == item["expected"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out")
    ap.add_argument("--holdout", action="store_true", help="별도 검증셋으로 평가")
    args = ap.parse_args()
    path = HOLDOUT if args.holdout else SET
    data = json.loads(path.read_text(encoding="utf-8"))
    rows, by = [], collections.defaultdict(lambda: [0, 0])
    for item in data["items"]:
        got, ok = judge(item)
        rows.append(dict(id=item["id"], ok=ok, text=item["text"], expected=item["expected"], got=got))
        keys = [("분류", item["category"]), ("입력", item["kind"])]
        keys += [("변형", f"{k}={v}") for k, v in item["variants"].items()]
        for key in keys + [("전체", "")]:
            by[key][0] += ok
            by[key][1] += 1
    summary = {f"{a}:{b}" if b else a: dict(correct=c, total=n, fail_rate=round(1 - c / n, 3))
               for (a, b), (c, n) in sorted(by.items())}
    for name, s in summary.items():
        print(f"[{args.label}] {name:24s} {s['correct']:3d}/{s['total']:3d}  실패율 {s['fail_rate']:.3f}")
    for r in rows:
        if not r["ok"]:
            print(f"  FAIL {r['id']} 기대 {r['expected']} 결과 {r['got']} | {r['text']}")
    if args.out:
        Path(args.out).write_text(json.dumps(dict(label=args.label, set=path.name, set_version=data["version"],
                                                  summary=summary, rows=rows), ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")


if __name__ == "__main__":
    main()
