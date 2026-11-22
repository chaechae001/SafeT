"""검증셋 v2(원문·STT 전사)로 튀김(FRY) 최종 상태를 평가한다.

사진에 튀김기(EQ_FRYER)가 찍힌 상황을 가정한다. retrieve_with_evidence의 결과로 FRY 최종 상태를 정한다.
- used: 글 후보(text_candidates)에 있음 → 평가 행 대상
- unused: 해당 없음(not_applicable_candidates) → 제외
- review: 그 밖(사진 후보로만 남아 작업 미확인 확인 대상)

  python eval_v2.py --label B_rules --out <json>
  python eval_v2.py --label C_exaone --judge exaone --base http://127.0.0.1:8010 --key-file <path> --out <json>
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from ai.assessment_authoring.contracts import load_catalog  # noqa: E402
from ai.assessment_authoring.retrieval_adapter import retrieve_with_evidence  # noqa: E402

TEXT_SET = HERE / "261123_미사용판정_검증셋_v2_DR.json"
STT_SET = HERE / "261123_미사용판정_검증셋_v2_STT_DR.json"


def final_state(trace):
    if "FRY" in trace["not_applicable_candidates"]:
        return "unused"
    if "FRY" in trace["text_candidates"]:
        return "used"
    return "review"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--judge", choices=["none", "exaone"], default="none")
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--key-file")
    ap.add_argument("--model", default="exaone-3.5-7.8b-instruct-awq")
    ap.add_argument("--out")
    args = ap.parse_args()
    kwargs = {}
    calls = []
    if args.judge == "exaone":
        from ai.assessment_authoring.negation_judge import exaone_judge
        judge = exaone_judge(args.base, Path(args.key_file).read_text().strip(), args.model)

        def timed(text, targets):
            t = time.perf_counter()
            try:
                return judge(text, targets)
            finally:
                calls.append(round(time.perf_counter() - t, 3))
        kwargs["negation_judge"] = timed
    catalog = load_catalog()
    source = json.loads(TEXT_SET.read_text(encoding="utf-8"))
    stt = {r["id"]: r["text"] for r in json.loads(STT_SET.read_text(encoding="utf-8"))["items"]}
    rows, by = [], collections.defaultdict(collections.Counter)
    for item in source["items"]:
        for kind, text in (("text", item["text"]), ("voice_transcript", stt[item["id"]])):
            context = dict(contract_version="assessment-authoring-1", catalog_version="CATALOG-MVP-1.1",
                           media=[dict(id="WORK", kind=kind, text=text)], equipment_ids=["EQ_FRYER"])
            n_before = len(calls)
            t = time.perf_counter()
            _, trace = retrieve_with_evidence(context, catalog, **kwargs)
            elapsed = round(time.perf_counter() - t, 3)
            got = final_state(trace)
            expected = item["expected_fry"]
            outcome = ("correct" if got == expected else "review" if got == "review"
                       else "danger" if expected == "used" else "missed_unused")
            rows.append(dict(id=item["id"], kind=kind, category=item["category"], text=text, expected=expected,
                             got=got, outcome=outcome, seconds=elapsed, judge_calls=len(calls) - n_before,
                             judgements=trace.get("negation_judgements", [])))
            for key in ("전체", "입력:" + kind, "분류:" + item["category"], "기대:" + expected):
                by[key][outcome] += 1
    summary = {k: dict(v, total=sum(v.values())) for k, v in sorted(by.items())}
    latency = dict(sentences=len(rows), judge_calls=len(calls),
                   judge_seconds_mean=round(sum(calls) / len(calls), 3) if calls else None,
                   judge_seconds_max=max(calls) if calls else None,
                   total_seconds_mean=round(sum(r["seconds"] for r in rows) / len(rows), 3))
    for k, v in summary.items():
        print(f"[{args.label}] {k:22s} 정답 {v.get('correct', 0):3d} 확인 {v.get('review', 0):3d} "
              f"위험오류 {v.get('danger', 0):3d} 미사용놓침 {v.get('missed_unused', 0):3d} / {v['total']}")
    print(f"[{args.label}] 지연 {latency}")
    for r in rows:
        if r["outcome"] != "correct":
            print(f"  {r['outcome']:13s} {r['id']} {r['kind'][:5]} 기대 {r['expected']} 결과 {r['got']} | {r['text']}")
    if args.out:
        Path(args.out).write_text(json.dumps(dict(label=args.label, judge=args.judge, summary=summary,
                                                  latency=latency, rows=rows), ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")


if __name__ == "__main__":
    main()
