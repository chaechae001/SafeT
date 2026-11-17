"""입력 3종(사진·음성·텍스트) 분기 시험. 재생 모드(LLM·STT 기록 재생), 사람 입력은 합성.
uv run -q --with langgraph --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/test_hitl_inputs.py
→ runs/hitl_graph/inputs_test.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hitl_graph import OUT, HitlGraph  # noqa: E402
from s04_pipeline import ROOT  # noqa: E402

CASES = {
    "text": {"user_input": {"type": "text", "text": "튀김기 기름을 교체하다가 손등에 기름이 튀었고, 냉장고 앞 바닥이 미끄러웠습니다."}},
    "voice": {"user_input": {"type": "voice", "audio_path": str(ROOT / "stt_test" / "audio" / "S01_clean.wav")}},
    "photo": {"user_input": {"type": "photo"},
              "detection": {"detection_request_id": "det-SYNTH-0002", "status": "ok", "synthetic": True,
                            "items": [{"detection_id": "photo-1#d1", "equipment_id": "EQ_FRYER", "confidence": None}]}},
}


def run(name: str, init: dict) -> dict:
    from langgraph.types import Command
    hg = HitlGraph(backend="replay")
    app = hg.build()
    cfg = {"configurable": {"thread_id": f"inputs-{name}"}}
    r = app.invoke({"assessment_id": f"A-SYNTH-{name}", "trace": [], "checks": {}, **init}, cfg)
    steps = []
    while "__interrupt__" in r:
        iv = r["__interrupt__"][0].value
        steps.append(iv["step"])
        if iv["step"] == "confirm_transcript":
            ans = {"text": iv["text"]}                       # 합성: 인식 결과를 그대로 승인
        elif iv["step"] == "confirm_equipment":
            ans = {"synthetic": True, "actions": [], "added": [] if iv["proposed"] else ["EQ_FRYER"]}
        else:
            c = iv["candidates"]
            ans = {"synthetic": True, "selections": [{"candidate_id": c[0]["candidate_id"], "likelihood": 2, "severity": 2, "measure_ids": []}]} if c else {"selections": []}
        r = app.invoke(Command(resume=ans), cfg)
    hg.close()
    bad = {k: v for k, v in r["checks"].items() if k != "postprocess" and v}
    return {"interrupts": steps, "trace": r["trace"], "input_text": r.get("input_text"),
            "proposed": [p["equipment_id"] for p in r.get("proposed", [])],
            "origins": sorted({e["origin"] + "/" + e["user_action"] for e in r["equipment_confirmed"]["equipment"]}),
            "schema_errors": bad, "risk_status": (r.get("risk_result") or {}).get("status")}


def main():
    out = {k: run(k, v) for k, v in CASES.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "inputs_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {x: v[x] for x in ("interrupts", "proposed", "origins", "schema_errors", "risk_status")} for k, v in out.items()}, ensure_ascii=False))
    ok = all(not v["schema_errors"] and v["risk_status"] for v in out.values()) and out["voice"]["interrupts"][0] == "confirm_transcript"
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
