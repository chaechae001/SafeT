"""규칙 기반 위험도 계산(임시 가정, 팀·전문가 확정 전). AI(LLM)는 관여하지 않는다.

- 설정(기본): config/risk_rule_3x3_notion_v1.json (사용자 결정 2026-11-16: 노션 H1 3×3 + 해석 B '중대성 3이면 빨강', adoption_status=proposed)
- 설정(이전): config/risk_rule_temp_3x3.json (안내서 예시를 옮긴 값, adoption_status=guide_example_not_adopted)
- severity_overrides가 있으면 점수 구간 뒤에 중대성 등급으로 구간을 덮어쓴다(처음 일치한 항목 하나)
- 입력: 사용자가 고른 발생 가능성·중대성(user_selection.v2의 likelihood·severity 등급)
- 출력: 계약 risk_result.v2. 설정이 adopted가 아니면 status=rule_not_adopted(시험 계산)로 둔다.
- 등급 구간은 코드에 없다. 모두 설정 파일에서 읽는다.
uv run --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/risk_rule.py   → 자체 시험
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, now_kst  # noqa: E402

CFG = ROOT / "config" / "risk_rule_3x3_notion_v1.json"
CFG_TEMP = ROOT / "config" / "risk_rule_temp_3x3.json"
ENGINE_VERSION = "risk_rule-0.2"
TEMP_NOTE = "임시 가정, 팀·전문가 확정 전"


def load_rule(path: Path = CFG) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    bands = sorted(cfg["bands"], key=lambda b: b["min_score"])
    for a, b in zip(bands, bands[1:]):
        if a["max_score"] + 1 != b["min_score"]:
            raise ValueError("구간이 겹치거나 비어 있음")
    return cfg


def score(cfg: dict, l: int, s: int) -> int:
    if cfg["method"] == "product":
        return l * s
    if cfg["method"] == "sum":
        return l + s
    return cfg["matrix"][l - 1][s - 1]


def compute(cfg: dict, assessment_id: str, selections: list[dict]) -> dict:
    lv = {x["level"] for x in cfg["likelihood_levels"]}
    sv = {x["level"] for x in cfg["severity_levels"]}
    results = []
    for sel in selections:
        l, s = sel.get("likelihood"), sel.get("severity")
        h = hashlib.sha256(f'{l}|{s}|{cfg["scale_id"]}|{cfg["scale_version"]}'.encode()).hexdigest()
        base = {"selection_id": sel["selection_id"], "phase": sel.get("phase", "before_measures"),
                "likelihood_level": l, "severity_level": s, "input_hash": h}
        if l is None or s is None:
            results.append(base | {"result_status": "not_rated", "risk_score": None, "band_code": None, "tolerable": None, "signal": None})
            continue
        if l not in lv or s not in sv:
            results.append(base | {"result_status": "out_of_scale", "risk_score": None, "band_code": None, "tolerable": None, "signal": None})
            continue
        sc = score(cfg, l, s)
        band = next(b for b in cfg["bands"] if b["min_score"] <= sc <= b["max_score"])
        band = next((o for o in (cfg.get("severity_overrides") or []) if o["severity_level"] == s), band)
        results.append(base | {"result_status": "computed", "risk_score": sc, "band_code": band["band_code"],
                               "tolerable": band["tolerable"], "signal": band.get("signal")})
    status = "rule_not_adopted" if cfg["adoption_status"] != "adopted" else (
        "incomplete" if any(r["result_status"] != "computed" for r in results) else "ok")
    return {"assessment_id": assessment_id, "computed_by": "rule_engine",
            "rule": {"scale_id": cfg["scale_id"], "scale_version": cfg["scale_version"], "adoption_status": cfg["adoption_status"],
                     "method": cfg["method"], "engine_version": ENGINE_VERSION},
            "computed_at": now_kst(), "status": status, "results": results}


# 기대 신호(사용자 결정 해석 B): 중대성 3 → red, 그 외 점수 1~3 green, 4~9 yellow
EXPECT_B = {(l, s): ("red" if s == 3 else ("green" if l * s <= 3 else "yellow")) for l in (1, 2, 3) for s in (1, 2, 3)}


def check(path: Path, reg, v2: Path, expect_signal: dict | None) -> dict:
    from jsonschema import Draft202012Validator, FormatChecker
    cfg = load_rule(path)
    cfg_errs = [e.message for e in Draft202012Validator(json.loads((v2 / "risk_rule_config.v2.schema.json").read_text(encoding="utf-8")),
                                                        registry=reg, format_checker=FormatChecker()).iter_errors(cfg)]
    # 합성 선택값(사용자 입력 대용, 시험용): 3×3 전체 + 미입력 + 척도 밖
    sels = [{"selection_id": f"t-{l}{s}", "likelihood": l, "severity": s} for l in (1, 2, 3) for s in (1, 2, 3)]
    sels += [{"selection_id": "t-none", "likelihood": None, "severity": 2}, {"selection_id": "t-out", "likelihood": 4, "severity": 1}]
    res = compute(cfg, "TEST-" + cfg["scale_id"], sels)
    rv = Draft202012Validator(json.loads((v2 / "risk_result.v2.schema.json").read_text(encoding="utf-8")),
                              registry=reg, format_checker=FormatChecker())
    errs = [e.message for e in rv.iter_errors(res)]
    score_ok = all(r["risk_score"] == int(r["selection_id"][2]) * int(r["selection_id"][3]) for r in res["results"][:9])
    sig_ok = True if expect_signal is None else all(
        r["signal"] == expect_signal[(int(r["selection_id"][2]), int(r["selection_id"][3]))] for r in res["results"][:9])
    edge_ok = [r["result_status"] for r in res["results"][9:]] == ["not_rated", "out_of_scale"]
    return {"config": path.name, "config_schema_errors": cfg_errs, "result_schema_errors": errs, "score_check": score_ok,
            "signal_check": sig_ok, "edge_check": edge_ok, "status": res["status"],
            "grid": {r["selection_id"]: [r["risk_score"], r["band_code"], r["signal"]] for r in res["results"]}, "result": res}


def main():
    from referencing import Registry, Resource
    v2 = ROOT.parent / "261115_AI출력계약_신호기준_DR" / "schemas_v2"
    reg = Registry()
    for f in v2.glob("*.json"):
        s = json.loads(f.read_text(encoding="utf-8"))
        reg = reg.with_resource(s["$id"], Resource.from_contents(s))
    runs = [check(CFG, reg, v2, EXPECT_B), check(CFG_TEMP, reg, v2, None)]
    # 계약 예시 파일도 확장 스키마에서 계속 통과하는지
    ex = ROOT.parent / "261115_AI출력계약_신호기준_DR" / "examples_v2" / "risk_rule_config.guide_3x3_example.json"
    from jsonschema import Draft202012Validator
    ex_errs = [e.message for e in Draft202012Validator(json.loads((v2 / "risk_rule_config.v2.schema.json").read_text(encoding="utf-8")),
                                                       registry=reg).iter_errors(json.loads(ex.read_text(encoding="utf-8")))]
    ok = not ex_errs and all(not r["config_schema_errors"] and not r["result_schema_errors"] and r["score_check"]
                             and r["signal_check"] and r["edge_check"] for r in runs)
    out = {"checked_at": now_kst(), "note": "합성 선택값 시험. 척도는 사용자 결정(2026-11-16)이며 전문가 채택 전(proposed)",
           "guide_example_schema_errors": ex_errs, "runs": runs, "all_ok": ok}
    d = ROOT / "runs" / "hitl_recommend"
    d.mkdir(parents=True, exist_ok=True)
    (d / "risk_rule_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in runs:
        print(json.dumps({k: r[k] for k in ("config", "config_schema_errors", "result_schema_errors", "score_check", "signal_check", "edge_check", "status", "grid")}, ensure_ascii=False))
    print("guide_example_schema_errors", ex_errs, "ALL_OK", ok)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
