"""스키마 검증기가 잘못된 응답을 실제로 거부하고, 항목 수리(off/invalid_output)가 동작하는지 확인한다."""
import copy, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline

pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json")
good = json.loads((ROOT / "runs" / "tc01_offline_provisional" / "response.json").read_text(encoding="utf-8"))
cases = {
    "빨강에 추천 2개": lambda r: r["items"][0]["recommended_measures"].pop(),
    "초안에 사용자 필드(current_measures)": lambda r: r["items"][0].__setitem__("current_measures", ["x"]),
    "검증 안 된 법령(verified=false)": lambda r: r["items"][2]["laws"][0].__setitem__("verified", False),
    "off인데 원인 코드 없음": lambda r: r["items"][5].__setitem__("off_reason_code", None),
    "알 수 없는 신호": lambda r: r["items"][1].__setitem__("signal", "orange"),
}
out = []
for name, mutate in cases.items():
    bad = copy.deepcopy(good); mutate(bad)
    rejected = bool(pipe.validator.errors("s04_draft.response.schema.json", bad))
    pipe.warnings = []
    bad.setdefault("warnings", [])
    fixed = pipe.validate_and_repair(bad)
    repaired = not pipe.validator.errors("s04_draft.response.schema.json", fixed)
    out.append({"case": name, "rejected": rejected, "valid_after_repair": repaired, "status_after": fixed["status"]})
    print(f"{name:<36} rejected={rejected} repaired_valid={repaired} status={fixed['status']}")
(ROOT / "runs" / "negative_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
