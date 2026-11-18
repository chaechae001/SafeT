"""Python 3.11 본체 쪽: SAM 3(3.12) 탐지 JSON 파일을 읽어 LangGraph 흐름(EXAONE 3.5 AWQ, vLLM)을 실행한다.
SAM 3와 본체는 같은 프로세스에서 import하지 않고 JSON 파일로만 연결한다(연결 형식 검증용).
사람 입력은 합성(시험용)이다.
사용: python run_graph_detfile.py APP_DIR BUNDLE SAM3_JSON OUT_JSON
"""
import json, sys, time

app_dir, bundle, det_path, out_path = sys.argv[1:5]
sys.path.insert(0, app_dir + "/src")
import os
os.chdir(app_dir)
from hitl_graph import HitlGraph  # noqa: E402
from langgraph.types import Command  # noqa: E402

raw = json.load(open(det_path, encoding="utf-8"))
mo = raw["model_output"]
# 연결 형식: detect_compare v2 초안 → 그래프 detection 입력. 기기마다 가장 높은 점수 1건만 넘긴다(확정은 사람이 한다).
best = {}
for d in mo["detections"]:
    if d.get("equipment_id") and (d["equipment_id"] not in best or d["confidence"] > best[d["equipment_id"]]["confidence"]):
        best[d["equipment_id"]] = d
det = {"detection_request_id": mo["request_id"], "status": mo["status"], "source": "SAM 3(det-sam3, Python 3.12) JSON",
       "items": [{"detection_id": f'{d["photo_id"]}#{d["detection_id"]}', "equipment_id": e, "confidence": d["confidence"]}
                 for e, d in sorted(best.items())]}
t0 = time.time()
hg = HitlGraph(backend="vllm", bundle=bundle)
app = hg.build()
cfg = {"configurable": {"thread_id": "py311-detfile"}}
r = app.invoke({"assessment_id": "A-PY311-CHECK", "detection": det, "trace": [], "checks": {}}, cfg)
known = [p["equipment_id"] for p in r["__interrupt__"][0].value["proposed"]]
r = app.invoke(Command(resume={"synthetic": True, "actions": [], "added": [] if known else ["EQ_FRYER"]}), cfg)
cands = r["__interrupt__"][0].value["candidates"] if "__interrupt__" in r else []
sel = [{"candidate_id": c["candidate_id"], "likelihood": 2, "severity": 2, "measure_ids": []} for c in cands[:2]]
r = app.invoke(Command(resume={"synthetic": True, "selections": sel}), cfg)
bad = {k: v for k, v in r["checks"].items() if k != "postprocess" and v}
out = {"python": sys.version.split()[0], "detection_input": det, "proposed_equipment": known, "trace": r["trace"],
       "schema_errors": bad, "postprocess": r["checks"].get("postprocess"),
       "llm_calls": {k: (None if v is None else {x: v[x] for x in ("attempts", "seconds", "mode")}) for k, v in (r.get("llm") or {}).items()},
       "risk": [(x["selection_id"], x["risk_score"], x["band_code"], x.get("signal")) for x in (r.get("risk_result") or {}).get("results", [])],
       "wall_seconds": round(time.time() - t0, 2), "note": "SAM 3 결과는 실제 Cloud 실행, 사람 입력은 합성(시험용)"}
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ("python", "proposed_equipment", "trace", "schema_errors", "risk", "wall_seconds")}, ensure_ascii=False))
# vLLM 엔진 정리(hitl_graph.py의 close()가 있으면 사용). 그래도 남는 경우를 막기 위해 os._exit로 끝낸다.
if hasattr(hg, "close"):
    hg.close()
sys.stdout.flush()
os._exit(1 if bad else 0)
