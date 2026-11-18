"""3차 개선(A2 + C1/C2 + 기기 매핑) 프롬프트 묶음. 모델 호출 없음.

stage1: A2 항목 생성 호출 → cloud/prompts_s04_v4.json
stage2: stage1 Cloud 출력(cloud/outputs/cloud_outputs_v4.json)을 재생해 빨강·노랑 항목마다 C1 대책 선택 호출
        → cloud/prompts_s04_v5.json (불일치 필터 off로 모은 상위 집합. 필터 on 항목도 같은 ID로 재생된다)
python src/dump_prompts_v3.py stage1 | stage2
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

A2 = {"strategy": "split", "candidates": False, "equipment_mapping": True, "item_prompt": "v3_items"}
# A3(3차 2회): 4판 항목 프롬프트(예시 문장 제거) + C2 순위에서 점수 0 행 유지
A3 = {**A2, "item_prompt": "v4_items", "rank_keep_unscored": True}
CFG = {"A2": (A2, "prompts_s04_v4.json", "cloud_outputs_v4.json", "prompts_s04_v5.json"),
       "A3": (A3, "prompts_s04_v6.json", "cloud_outputs_v6.json", "prompts_s04_v7.json")}
REQS = [ROOT / "inputs" / "tc01_request.json"] + sorted((ROOT / "inputs" / "cases").glob("*.json"))


def make(mode: str, extra: dict, mismatch_filter: bool = False, base: dict = A2) -> S04Pipeline:
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json", mode=mode)
    pipe.cfg["backend"]["llm"].update(base)
    pipe.cfg["backend"]["llm"].update(extra)
    pipe.cfg["backend"]["llm"]["postprocess"]["mismatch_filter"] = mismatch_filter
    return pipe


def stage1(name="A2"):
    base, p1, _, _ = CFG[name]
    out = {"created_at": now_kst(), "variant": name, "config": base, "calls": []}
    for rp in REQS:
        d = make("llm", {}, base=base).dump_prompt(json.loads(rp.read_text(encoding="utf-8")))
        for c in d["calls"]:
            out["calls"].append({"variant": name, "request_id": d["request_id"],
                                 "request_file": str(rp.relative_to(ROOT)).replace("\\", "/"),
                                 "unit_id": c["unit_id"], "messages": c["messages"], "expect_key": "items"})
    p = ROOT / "cloud" / p1
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(p, len(out["calls"]))


def replay_calls(results, request_id):
    calls = {}
    for r in results:
        if r["request_id"] == request_id:
            idx = (r["accepted_attempt"] - 1) if r.get("accepted_attempt") else len(r["attempts"]) - 1
            calls[r["unit_id"]] = {"messages": r["messages"], "attempts": r["attempts"], "use_attempt": idx}
    return calls


def stage2(name="A2"):
    base, _, o1, p2 = CFG[name]
    v4 = json.loads((ROOT / "cloud" / "outputs" / o1).read_text(encoding="utf-8"))
    out = {"created_at": now_kst(), "variant": f"{name}+C1", "calls": []}
    for rp in REQS:
        req = json.loads(rp.read_text(encoding="utf-8"))
        pipe = make("replay", {"measure_stage": "c1"}, mismatch_filter=False, base=base)
        pipe.replay = {"model_id": v4["model_id"], "revision": v4["revision"]}
        pipe.replay_calls = replay_calls(v4["results"], req["request_id"])
        pipe.c1_collect = []
        pipe.run(req)
        for c in pipe.c1_collect:
            out["calls"].append({"variant": f"{name}+C1", "request_id": req["request_id"], **c})
    p = ROOT / "cloud" / p2
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(p, len(out["calls"]))


if __name__ == "__main__":
    {"stage1": stage1, "stage2": stage2}[sys.argv[1]](*(sys.argv[2:3] or ["A2"]))
