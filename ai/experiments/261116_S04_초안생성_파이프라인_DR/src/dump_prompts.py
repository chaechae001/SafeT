"""Cloud 추론용 프롬프트 묶음을 만든다. 모델 호출 없음.
python src/dump_prompts.py  → cloud/prompts_s04.json
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline, now_kst

reqs = [ROOT / "inputs" / "tc01_request.json"] + sorted((ROOT / "inputs" / "cases").glob("*.json"))
out = {"created_at": now_kst(), "pipeline_version": None, "prompts": []}
for rp in reqs:
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json", mode="llm")
    out["pipeline_version"] = pipe.cfg["pipeline_version"]
    d = pipe.dump_prompt(json.loads(rp.read_text(encoding="utf-8")))
    out["prompts"].append({"request_id": d["request_id"], "request_file": str(rp.relative_to(ROOT)).replace("\\", "/"),
                           "messages": d["messages"]})
(ROOT / "cloud").mkdir(exist_ok=True)
p = ROOT / "cloud" / "prompts_s04.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(p, len(out["prompts"]), [len(x["messages"][1]["content"]) for x in out["prompts"]])
