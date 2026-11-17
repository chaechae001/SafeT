"""추천형 응답을 계약 v2(hazard_candidates.v2.response)로 바꾸고 검증한다(모델 호출 없음, 계약 폴더는 읽기만).
uv run --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/hitl_contract_v2.py

변환 규칙
- 후보마다 source_refs가 1개 이상 있어야 한다(계약: 출처 없는 후보는 버린다).
  출처 ID가 없는 후보(LLM 단독, 일부 기기마스터 연결)는 서버가 지식베이스에서 근거 행을 찾아 붙이고(server_attached),
  그래도 없으면 버린다. 버린 수를 방법별로 기록한다.
- source_type: CHK-* → checklist, CASE-* → case, 그 밖(청크 ID, 인덱스 v2의 D8T-*·D5 전사 ID) → guide_chunk.
  D8T-*를 guide_chunk로 두는 것은 이 변환기의 임시 대응이다(계약 enum에 표 행 유형이 없음, 계약 세션 확인 필요).
- rationale: LLM 이유 문장이 있으면 그대로, 없으면 출처 ID를 나열한 고정 문장. 위험 정도 판단 문구는 넣지 않는다.
- 후보가 없는 기기는 group_status = no_source_found(사용자가 직접 추가).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hitl_recommend import OUT_DIR, HitlRecommender  # noqa: E402
from s04_pipeline import ROOT, now_kst  # noqa: E402

V2 = ROOT.parent / "261115_AI출력계약_신호기준_DR" / "schemas_v2"
CT = {"elimination_substitution", "engineering", "administrative", "ppe"}


def validator():
    reg = Registry()
    for f in V2.glob("*.json"):
        sch = json.loads(f.read_text(encoding="utf-8"))
        reg = reg.with_resource(sch["$id"], Resource.from_contents(sch))
    sch = json.loads((V2 / "hazard_candidates.v2.response.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(sch, registry=reg, format_checker=FormatChecker())


def stype(sid: str) -> str:
    return "checklist" if sid.startswith("CHK-") else "case" if sid.startswith("CASE-") else "guide_chunk"


def ref(sid: str, kb_version: str) -> dict:
    return {"source_id": sid, "source_type": stype(sid), "kb_version": kb_version}


def convert(rec: HitlRecommender, r: dict, stats: dict) -> dict:
    kbv = "rag-kb-v2-index" if r["method"] == "R_index_v2" else "rag-kb-v1"
    groups = []
    for e in r["equipment"]:
        cands = []
        for c in e["candidates"]:
            src = list(c["source_ids"])
            attached = False
            if not src:
                src = rec.evidence_rows(e["equipment_id"], c["hazard_code"], 2)
                attached = bool(src)
            if not src:
                stats["dropped_no_source"] += 1
                continue
            stats["server_attached"] += attached
            reason = c["reason"] or f'근거 자료 {", ".join(src[:3])}에 이 기기와 {c["hazard_name"]} 관련 내용이 있다.'
            if attached:
                reason += f' (출처는 서버가 붙임: {", ".join(src)})'
            cands.append({
                "candidate_id": f'{e["equipment_id"]}:{c["hazard_code"]}',
                "work": None,
                "hazard": (c["hazard_text"] or c["hazard_name"])[:120],
                "accident_type": {"code": c["hazard_code"], "label": c["hazard_name"]},
                "rationale": reason[:300],
                "source_refs": [ref(s, kbv) for s in src],
                "measure_candidates": [{"measure_id": f'm-{e["equipment_id"]}-{c["hazard_code"]}-{i + 1}', "text": m["text"][:120],
                                        "control_type": m["control_type"] if m["control_type"] in CT else None,
                                        "source_refs": [ref(m["row_id"], kbv)]} for i, m in enumerate(c["measure_candidates"])],
            })
        stats["candidates_out"] += len(cands)
        groups.append({"equipment_id": e["equipment_id"], "display_name": e["standard_name"],
                       "group_status": "ok" if cands else "no_source_found", "candidates": cands})
    return {"request_id": r["request_id"], "call": "hazard_candidates_v2",
            "status": "ok" if all(g["group_status"] == "ok" for g in groups) else "partial",
            "model_version": r["model_version"] or f'retrieval-only:{r["method"]}@{r["pipeline_version"]}',
            "kb_version": kbv, "generated_at": r["generated_at"], "groups": groups}


def main():
    rec = HitlRecommender()
    v = validator()
    out_dir = OUT_DIR / "contract_v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"checked_at": now_kst(), "schema": str(V2 / "hazard_candidates.v2.response.schema.json"), "methods": {}}
    ok_all = True
    for f in sorted(OUT_DIR.glob("responses_*.json")):
        m = f.stem.replace("responses_", "")
        stats = {"responses": 0, "valid": 0, "candidates_in": 0, "candidates_out": 0, "server_attached": 0,
                 "dropped_no_source": 0, "no_source_found_groups": 0, "errors": []}
        conv = []
        for r in json.loads(f.read_text(encoding="utf-8")):
            stats["responses"] += 1
            stats["candidates_in"] += sum(len(e["candidates"]) for e in r["equipment"])
            c = convert(rec, r, stats)
            stats["no_source_found_groups"] += sum(g["group_status"] == "no_source_found" for g in c["groups"])
            errs = [f'{r["request_id"]}: {x.message[:150]}' for x in v.iter_errors(c)]
            stats["valid"] += not errs
            stats["errors"] += errs[:3]
            conv.append(c)
        ok_all &= stats["valid"] == stats["responses"]
        (out_dir / f"v2_{m}.json").write_text(json.dumps(conv, ensure_ascii=False, indent=1), encoding="utf-8")
        report["methods"][m] = stats
    # 음성 시험: 판단 필드·출처 없는 후보는 거부해야 한다
    sample = json.loads((out_dir / "v2_R_index.json").read_text(encoding="utf-8"))[0]
    neg = {}
    for name, mut in (("signal", lambda c: c.update(signal="red")), ("likelihood", lambda c: c.update(likelihood=2)),
                      ("empty_source_refs", lambda c: c.update(source_refs=[]))):
        b = json.loads(json.dumps(sample))
        mut(b["groups"][0]["candidates"][0])
        neg[name] = "거부됨" if not v.is_valid(b) else "통과(문제)"
        ok_all &= not v.is_valid(b)
    report["negative_tests"], report["all_ok"] = neg, ok_all
    (out_dir / "contract_v2_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for m, s in report["methods"].items():
        print(f'{m:12s} valid {s["valid"]}/{s["responses"]} cand {s["candidates_in"]}->{s["candidates_out"]} '
              f'attached {s["server_attached"]} dropped {s["dropped_no_source"]} nsf_groups {s["no_source_found_groups"]} err {s["errors"][:1]}')
    print("negative", neg, "ALL_OK" if ok_all else "FAIL")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
