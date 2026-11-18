"""평시 상주 구성 실행: 한 프로세스에서 STT(faster-whisper)와 EXAONE 3.5(vLLM, 0.70)를 올려 두고 음성·텍스트 입력을 차례로 처리한다.
사람 입력은 합성(인식 결과 그대로 승인, 기기 그대로 유지, 첫 후보 선택). 사용: python run_graph_resident.py APP_DIR OUT_JSON"""
import json, os, sys, time


def main():  # spawn 방식 하위 프로세스가 이 파일을 다시 불러도 실행되지 않게 감싼다
    global app_dir
    app_dir, out_path = sys.argv[1:3]
    sys.path.insert(0, app_dir + "/src"); os.chdir(app_dir)
    from hitl_graph import HitlGraph  # noqa: E402
    from langgraph.types import Command  # noqa: E402
    CASES = [("voice_S01_clean", {"type": "voice", "audio_path": "stt_test/audio/S01_clean.wav"}),
             ("voice_S05_snr10", {"type": "voice", "audio_path": "stt_test/audio/S05_snr10.wav"}),
             ("text_1", {"type": "text", "text": "튀김기 기름을 교체하다가 손등에 기름이 튀었고, 냉장고 앞 바닥이 미끄러웠습니다."}),
             ("voice_S01_clean_again", {"type": "voice", "audio_path": "stt_test/audio/S01_clean.wav"})]
    hg = HitlGraph(backend="vllm", bundle="runs/hitl_graph/bundle_v1.json")
    hg.stt_backend_name = "faster_whisper"
    app = hg.build()
    res = []
    for name, ui in CASES:
        t0 = time.time(); cfg = {"configurable": {"thread_id": name}}
        r = app.invoke({"assessment_id": f"A-RES-{name}", "user_input": ui, "trace": [], "checks": {}}, cfg)
        steps, first_wait = [], round(time.time() - t0, 2)
        while "__interrupt__" in r:
            iv = r["__interrupt__"][0].value; steps.append(iv["step"])
            if iv["step"] == "confirm_transcript":
                ans = {"text": iv["text"]}
            elif iv["step"] == "confirm_equipment":
                ans = {"synthetic": True, "actions": [], "added": [] if iv["proposed"] else ["EQ_FRYER"]}
            else:
                c = iv["candidates"]
                ans = {"synthetic": True, "selections": [{"candidate_id": c[0]["candidate_id"], "likelihood": 2, "severity": 2, "measure_ids": []}] if c else []}
            r = app.invoke(Command(resume=ans), cfg)
        bad = {k: v for k, v in r["checks"].items() if k != "postprocess" and v}
        res.append({"case": name, "wall_s": round(time.time() - t0, 2), "until_first_interrupt_s": first_wait, "interrupts": steps,
                    "transcript": r.get("transcript"), "input_text": r.get("input_text"),
                    "proposed": [p["equipment_id"] for p in r.get("proposed", [])], "trace": r["trace"], "schema_errors": bad,
                    "llm_calls": {k: (None if v is None else {x: v[x] for x in ("attempts", "seconds", "mode")}) for k, v in (r.get("llm") or {}).items()},
                    "risk_status": (r.get("risk_result") or {}).get("status")})
        print(json.dumps({k: res[-1][k] for k in ("case", "wall_s", "until_first_interrupt_s", "proposed", "schema_errors")}, ensure_ascii=False), flush=True)
    json.dump({"python": sys.version.split()[0], "note": "합성 음성·합성 사람 입력. LLM·STT 한 프로세스 상주", "results": res},
              open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    hg.close(); sys.stdout.flush(); os._exit(1 if any(x["schema_errors"] for x in res) else 0)


if __name__ == "__main__":
    main()
