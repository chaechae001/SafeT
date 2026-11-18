"""추천형 응답 점검(모델 호출 없음). jsonschema 필요:
uv run --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/check_hitl.py
- contract_hitl 스키마 통과
- 신호·위험도·등급 키가 어디에도 없음
- 출처 ID·대책 행 ID가 지식베이스에 있음, 기기 ID가 기기마스터에 있음
- user_decision은 모두 null(AI가 채우지 않음)
- 음성 시험: 신호 키를 넣거나 user_decision을 채운 응답은 스키마가 거부해야 함
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

OUT = ROOT / "runs" / "hitl_recommend"
FORBIDDEN = {"signal", "level", "risk_level", "risk_score", "severity_level", "likelihood_level", "grade"}


def walk_keys(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, f"{path}/{k}"
            yield from walk_keys(v, f"{path}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from walk_keys(v, f"{path}/{i}")


def main():
    schema = json.loads((ROOT / "contract_hitl" / "hitl_recommend.response.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema, format_checker=FormatChecker())
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json")
    kb, em = pipe.kb, pipe.emap
    report = {"checked_at": now_kst(), "files": {}, "negative_tests": {}}
    v2 = json.loads((ROOT.parent / "261115_RAG_지식베이스_DR" / "261116_RAG_기기위험요인인덱스_v2_DR.json").read_text(encoding="utf-8"))
    v2_src = {sid for e in v2["index"] for h in e["hazards"] for sid in h["source_ids"]}
    known = lambda sid: sid in kb.rows or sid in kb.chunks or sid in v2_src  # noqa: E731
    all_ok = True
    for f in sorted(OUT.glob("responses_*.json")):
        resps = json.loads(f.read_text(encoding="utf-8"))
        errs = []
        for r in resps:
            errs += [f'{r["request_id"]}: {e.message[:120]}' for e in v.iter_errors(r)]
            errs += [f'{r["request_id"]}: 금지 키 {p}' for k, p in walk_keys(r) if k in FORBIDDEN]
            for e in r["equipment"]:
                if e["equipment_id"] not in em.equipment:
                    errs.append(f'알 수 없는 기기 {e["equipment_id"]}')
                for c in e["candidates"]:
                    errs += [f'출처 ID 없음 {s}' for s in c["source_ids"] if not known(s)]
                    errs += [f'CASE 출처 사용 {s}' for s in c["source_ids"] if s.startswith("CASE-")]
                    errs += [f'대책 행 없음 {m["row_id"]}' for m in c["measure_candidates"] if not known(m["row_id"])]
                    if any(val is not None for val in c["user_decision"].values()):
                        errs.append("user_decision이 채워짐")
        cands = [c for r in resps for e in r["equipment"] for c in e["candidates"]]
        report["files"][f.name] = {"responses": len(resps), "candidates": len(cands), "errors": errs[:20], "error_count": len(errs),
                                   "measure_methods": {m: sum(c["measure_method"] == m for c in cands) for m in ("c1", "c2", "c2_failed", "index_v2")}}
        all_ok &= not errs
    # 음성 시험
    base = json.loads(next(OUT.glob("responses_R_index.json")).read_text(encoding="utf-8"))[0]
    bad1 = copy.deepcopy(base)
    bad1["equipment"][0]["candidates"][0]["signal"] = "red"
    bad2 = copy.deepcopy(base)
    bad2["equipment"][0]["candidates"][0]["user_decision"]["severity"] = 3
    bad3 = copy.deepcopy(base)
    bad3["risk_scale_status"] = "확정"
    for name, b in (("signal_key", bad1), ("user_decision_filled", bad2), ("scale_status_changed", bad3)):
        rejected = not v.is_valid(b)
        report["negative_tests"][name] = "거부됨" if rejected else "통과(문제)"
        all_ok &= rejected
    report["all_ok"] = all_ok
    (OUT / "check_hitl.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: (x["error_count"], x["candidates"], x["measure_methods"]) for k, x in report["files"].items()}, ensure_ascii=False))
    print("negative", report["negative_tests"], "ALL_OK" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
