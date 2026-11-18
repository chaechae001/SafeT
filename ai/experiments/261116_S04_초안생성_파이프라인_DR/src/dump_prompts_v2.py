"""개선 실험(A: 기기·작업 단위 분할, B: RAG 후보 선택, AB: 결합)용 프롬프트 묶음. 모델 호출 없음.
python src/dump_prompts_v2.py → cloud/prompts_s04_v2.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

VARIANTS = {"A": {"strategy": "split", "candidates": False},
            "B": {"strategy": "single", "candidates": True},
            "AB": {"strategy": "split", "candidates": True},
            "B2": {"strategy": "single", "candidates": True, "candidate_prompt_version": 2},
            "AB2": {"strategy": "split", "candidates": True, "candidate_prompt_version": 2}}


def pipeline_for(variant: str) -> S04Pipeline:
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json", mode="llm")
    pipe.cfg["backend"]["llm"].update(VARIANTS[variant])
    return pipe


def main(only=None, out_name="prompts_s04_v2.json"):
    reqs = [ROOT / "inputs" / "tc01_request.json"] + sorted((ROOT / "inputs" / "cases").glob("*.json"))
    out = {"created_at": now_kst(), "variants": VARIANTS, "calls": []}
    for v in (only or VARIANTS):
        for rp in reqs:
            pipe = pipeline_for(v)
            out["pipeline_version"] = pipe.cfg["pipeline_version"]
            d = pipe.dump_prompt(json.loads(rp.read_text(encoding="utf-8")))
            for c in d["calls"]:
                out["calls"].append({"variant": v, "request_id": d["request_id"],
                                     "request_file": str(rp.relative_to(ROOT)).replace("\\", "/"),
                                     "unit_id": c["unit_id"], "messages": c["messages"]})
    p = ROOT / "cloud" / out_name
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(p, len(out["calls"]), Counter(c["variant"] for c in out["calls"]),
          max(len(c["messages"][1]["content"]) for c in out["calls"]))


if __name__ == "__main__":
    # 1차 개선 실행(01:21)은 A·B·AB, 2차(01:3x)는 B2·AB2
    if len(sys.argv) > 1 and sys.argv[1] == "round2":
        main(["B2", "AB2"], "prompts_s04_v3.json")
    else:
        main(["A", "B", "AB"])
