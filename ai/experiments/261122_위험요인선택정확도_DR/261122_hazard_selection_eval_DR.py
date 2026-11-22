"""위험요인(시나리오 ID) 선택 정확도 오프라인 평가.

실제 모델·DB·RAG 없이 `run_pipeline`을 서비스와 같은 순서로 실행한다.
- 사진: Elice Cloud 실측 SAM 3 탐지 결과(기기 ID)를 정답셋에 고정해 재사용한다.
- RAG: 서비스 `RAG_LINKS`와 같은 EQ_FRYER burn·slip 연결만 모의한다(근거 문서는 없음).
- 모델: 두 방식으로 모의한다.
  * greedy: 배치의 후보를 모두 평가 행으로 고르고 입력 문장 하나를 인용한다.
    2026-11-22 실제 EXAONE에서 관측한 과선택 행태의 최악 조건이다. 규칙·후처리의 오탐 차단력을 본다.
  * oracle: 정답(required·allowed)에 있는 후보만 고른다. 후보 단계와 후처리 때문에 생기는 누락의 상한을 본다.
- 서비스 `extract()`의 ENV 인용 필터와 `build_context()`의 튀김기 기기 추가를 같은 규칙으로 재현한다.

사용: 저장소 루트에서
    python ai/experiments/261122_위험요인선택정확도_DR/261122_hazard_selection_eval_DR.py --label before --out <json>
    (--gold로 검증셋 261122_위험요인검증셋_holdout_v1_DR.json을 지정할 수 있다.)
"""
import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ai.assessment_authoring.contracts import load_catalog  # noqa: E402
from ai.assessment_authoring.pipeline import run_pipeline  # noqa: E402
from ai.assessment_authoring import retrieval_adapter as ra  # noqa: E402

GOLD = Path(__file__).with_name("261122_위험요인정답셋_v1_DR.json")
RAG_LINKS = {"EQ_FRYER:burn": ["FRY"], "EQ_FRYER:slip": ["ENV"]}  # backend/services/authoring_rag.py와 동일


def sentences(text):
    return [s.strip() for s in re.findall(r"[^.!?\n]+[.!?]?", text) if s.strip()]


def rag_provider(equipment_ids, k=None):
    rows = [dict(equipment_ids=["EQ_FRYER"], hazard_code=code) for code in ("burn", "slip")
            if "EQ_FRYER" in equipment_ids]
    return dict(enabled=True, candidates=rows)


def make_context(text, equipment_ids):
    ids = list(equipment_ids)
    # backend authoring_rag.build_context와 같은 규칙: 작업 문장이 튀김기를 긍정 언급하면 기기로 추가한다.
    if ra._positive(text, "튀김기") and "EQ_FRYER" not in ids:
        ids.append("EQ_FRYER")
    media = [dict(id="PHOTO1", kind="equipment_detection", text="사진에서 기기 후보가 탐지되었습니다.")]
    media.append(dict(id="TEXT", kind="text", text=text))
    return dict(contract_version="assessment-authoring-1", catalog_version="CATALOG-MVP-1.1",
                media=media, equipment_ids=ids)


def make_extractor(mode, case, scenarios):
    wanted = set(case["required"]) | set(case["allowed"])

    def extract(context, batch, catalog, evidence):
        text = next(m["text"] for m in context["media"] if m["id"] == "TEXT")
        parts = sentences(text)
        out = []
        for row in batch["candidates"]:
            sid = row["scenario_id"]
            if mode == "oracle" and sid not in wanted:
                continue
            # 인용 선택은 평가 대상 코드와 독립인 고정 규칙: 해당 시나리오 단어가 들어간 첫 문장, 없으면 첫 문장.
            words = CITE_WORDS[sid]
            quote = next((s for s in parts if any(w in s for w in words)), parts[0])
            # backend authoring_rag.extract의 ENV 필터: RAG 문서로 올라온 ENV는 인용 문장이 ENV 기준어를 포함해야 한다.
            if sid == "ENV" and "ENV" not in ra.text_candidates(dict(id="TEXT", text=quote), [])[0]:
                continue
            out.append(dict(scenario_id=sid, rationale="모의 응답", evidence=[dict(media_id="TEXT", statement=quote)],
                            control_evidence=[], assumptions=[], questions=[]))
        return dict(contract_version="assessment-authoring-1", candidates=out, unmatched_risks=[])
    return extract


CITE_WORDS = {}


def cite_words(catalog):
    """모의 모델이 인용 문장을 고를 때 쓰는 단어. 정답셋 v1 작성 시점(e047787)의 카탈로그 keywords와 매핑 기준어로 고정한다."""
    frozen = json.loads(GOLD.with_name("261122_cite_words_v1_DR.json").read_text(encoding="utf-8"))
    return {s["id"]: frozen.get(s["id"], []) for s in catalog["scenarios"]}


def run(mode, gold, catalog):
    CITE_WORDS.clear()
    CITE_WORDS.update(cite_words(catalog))
    scenarios = {s["id"]: s for s in catalog["scenarios"]}
    results = []
    for photo, meta in gold["photos"].items():
        for case in gold["cases"]:
            context = make_context(case["text"], meta["equipment_ids"])
            out = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=None, catalog_snapshot=catalog,
                               rag_provider=rag_provider, rag_links=RAG_LINKS,
                               extract_with_evidence=make_extractor(mode, case, scenarios), batch_size=1)
            rows = sorted(r["scenario_id"] for r in out["assessment"]["rows"])
            review = out["assessment"]["core"]["review_candidates"]
            denied = sorted(r["scenario_id"] for r in review if r["reason"] == "input_denies_work")
            required, allowed = set(case["required"]), set(case["allowed"])
            results.append(dict(
                photo=photo, case=case["id"], tags=case["tags"], text=case["text"], rows=rows,
                candidates=sorted(c["scenario_id"] for c in out["retrieval"]["candidates"]),
                review=review, denied=denied,
                tp=sorted(required & set(rows)), fn=sorted(required - set(rows)),
                fp=sorted(set(rows) - required - allowed),
                denial_ok=(set(case.get("denied", [])) == set(denied)) if case.get("denied") else ("FRY" not in denied)))
    return results


def summarize(results):
    tp = sum(len(r["tp"]) for r in results)
    fp = sum(len(r["fp"]) for r in results)
    fn = sum(len(r["fn"]) for r in results)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    exact = sum(1 for r in results if not r["fp"] and not r["fn"])
    return dict(pairs=len(results), tp=tp, fp=fp, fn=fn, precision=round(precision, 3), recall=round(recall, 3),
                f1=round(f1, 3), exact=exact, exact_rate=round(exact / len(results), 3),
                denial_ok=sum(r["denial_ok"] for r in results))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out")
    parser.add_argument("--gold", default=str(GOLD), help="정답셋 JSON(기본: 정답셋 v1)")
    args = parser.parse_args()
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    catalog = load_catalog()
    report = dict(label=args.label, gold=gold["version"], label_status=gold["label_status"])
    for mode in ("greedy", "oracle"):
        results = run(mode, gold, catalog)
        report[mode] = dict(summary=summarize(results), results=results)
        s = report[mode]["summary"]
        print(f"[{args.label}/{mode}] pairs={s['pairs']} P={s['precision']} R={s['recall']} F1={s['f1']} "
              f"TP={s['tp']} FP={s['fp']} FN={s['fn']} exact={s['exact']} denial_ok={s['denial_ok']}")
        for r in results:
            if r["fp"] or r["fn"] or not r["denial_ok"]:
                print(f"  {r['photo']:<10} {r['case']} FP={r['fp']} FN={r['fn']} denied={r['denied']} "
                      f"ok={r['denial_ok']} | {r['text']}")
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
