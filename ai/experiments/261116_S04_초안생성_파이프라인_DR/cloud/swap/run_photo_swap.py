"""사진 입력 시 모델 교체 자동화 시험(3.11 본체). 평시 LLM+STT 상주 → 사진 도착 → LLM·STT 내림 → SAM 3(det-sam3, 3.12, 별도 프로세스) 탐지 →
기기 확인 화면(interrupt)을 띄운 직후 뒤에서 LLM·STT를 다시 올림 → 사용자가 확인을 마치면 추천 진행. 사람 입력은 합성.
사용: python run_photo_swap.py APP_DIR SAM3_INPUT_DIR OUT_JSON"""
import gc, json, os, subprocess, sys, threading, time


def mem():
    o = subprocess.run("nvidia-smi | grep -oE '[0-9]+MiB / +9728MiB' | head -1 | grep -oE '^[0-9]+'", shell=True, capture_output=True, text=True).stdout.strip()
    return int(o or -1)


def main():
    app_dir, sam_in, out_path = sys.argv[1:4]
    sys.path.insert(0, app_dir + "/src"); os.chdir(app_dir)
    from hitl_graph import HitlGraph
    from langgraph.types import Command
    T, ev = time.time, []
    mark = lambda name: ev.append({"event": name, "t": round(T(), 3), "mem_mib": mem()})
    hg = HitlGraph(backend="vllm", bundle="runs/hitl_graph/bundle_v1.json"); hg.stt_backend_name = "faster_whisper"
    app = hg.build()
    # 1) 평시: STT → LLM 순서로 올리고 텍스트 1건 처리(워밍업)
    mark("resident_load_start"); hg.stt; hg.backend; mark("resident_ready")
    cfg = {"configurable": {"thread_id": "warm"}}
    r = app.invoke({"assessment_id": "A-SWAP-warm", "user_input": {"type": "text", "text": "튀김기 기름이 튀었습니다."}, "trace": [], "checks": {}}, cfg)
    while "__interrupt__" in r:
        iv = r["__interrupt__"][0].value
        ans = {"actions": [], "added": []} if iv["step"] == "confirm_equipment" else {"selections": [{"candidate_id": iv["candidates"][0]["candidate_id"], "likelihood": 1, "severity": 1, "measure_ids": []}]}
        r = app.invoke(Command(resume=ans), cfg)
    mark("warm_done")
    # 2) 사진 도착: LLM·STT 내림
    mark("photo_arrived"); hg.close(); hg._backend = None; hg._stt = None; gc.collect()
    for _ in range(240):
        if mem() < 1200: break
        time.sleep(0.25)
    mark("resident_unloaded")
    # 3) SAM 3 탐지(별도 프로세스, 3.12)
    det_out = os.path.join(os.path.dirname(out_path), "sam3_swap.json")
    subprocess.run(["/home/elicer/venvs/det-sam3/bin/python", "/home/elicer/safet/experiments/261116_detect_compare_DR/detect_compare_v2.py",
                    "--model", "sam3", "--inputs", sam_in, "--out", det_out], capture_output=True, text=True)
    mark("sam3_done")
    for _ in range(240):
        if mem() < 1200: break
        time.sleep(0.25)
    mark("sam3_unloaded")
    mo = json.load(open(det_out, encoding="utf-8"))["model_output"]
    best = {}
    for d in mo["detections"]:
        if d.get("equipment_id") and d["confidence"] >= 0.5 and (d["equipment_id"] not in best or d["confidence"] > best[d["equipment_id"]]["confidence"]):
            best[d["equipment_id"]] = d
    det = {"detection_request_id": mo["request_id"], "status": mo["status"],
           "items": [{"detection_id": f'{d["photo_id"]}#{d["detection_id"]}', "equipment_id": e, "confidence": d["confidence"]} for e, d in best.items()]}
    # 4) 기기 확인 화면을 먼저 띄우고, 뒤에서 LLM·STT 다시 올림
    cfg = {"configurable": {"thread_id": "photo"}}
    r = app.invoke({"assessment_id": "A-SWAP-photo", "user_input": {"type": "photo"}, "detection": det, "trace": [], "checks": {}}, cfg)
    mark("confirm_screen_shown")
    def reload():
        hg.stt; hg.backend; mark("resident_reloaded")
    th = threading.Thread(target=reload); th.start()
    th.join()   # 실제 서비스에서는 사용자가 확인하는 동안 기다린다. 여기서는 다시 올리는 데 걸린 시간만 잰다
    steps = []
    while "__interrupt__" in r:
        iv = r["__interrupt__"][0].value; steps.append(iv["step"])
        if iv["step"] == "confirm_equipment":
            ans = {"synthetic": True, "actions": [], "added": [] if iv["proposed"] else ["EQ_FRYER"]}
        else:
            c = iv["candidates"]; ans = {"synthetic": True, "selections": [{"candidate_id": c[0]["candidate_id"], "likelihood": 2, "severity": 2, "measure_ids": []}] if c else []}
        r = app.invoke(Command(resume=ans), cfg)
    mark("photo_done")
    t = {e["event"]: e["t"] for e in ev}
    summary = {"unload_s": round(t["resident_unloaded"] - t["photo_arrived"], 2), "sam3_s": round(t["sam3_done"] - t["resident_unloaded"], 2),
               "sam3_unload_s": round(t["sam3_unloaded"] - t["sam3_done"], 2),
               "until_confirm_screen_s": round(t["confirm_screen_shown"] - t["photo_arrived"], 2),
               "reload_after_screen_s": round(t["resident_reloaded"] - t["confirm_screen_shown"], 2),
               "photo_total_s": round(t["photo_done"] - t["photo_arrived"], 2)}
    bad = {k: v for k, v in r["checks"].items() if k != "postprocess" and v}
    json.dump({"events": ev, "summary": summary, "detection_items": det["items"], "interrupts": steps, "trace": r["trace"], "schema_errors": bad},
              open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"summary": summary, "n_items": len(det["items"]), "schema_errors": bad}, ensure_ascii=False), flush=True)
    hg.close(); sys.stdout.flush(); os._exit(1 if bad else 0)


if __name__ == "__main__":
    main()
