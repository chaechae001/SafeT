"""STT 상주 프로세스(det-sam3, 3.12). 모델을 올리고 1차 인식 → ready 신호 → go2 신호가 오면 2차 인식(LLM이 올라간 상태) → stop 신호까지 유지.
사용: python stt_hold.py MODEL_DIR AUDIO_DIR WORKDIR"""
import glob, json, os, sys, time, wave
import numpy as np
mdir, adir, w = sys.argv[1:4]
from faster_whisper import WhisperModel
t0 = time.time(); m = WhisperModel(mdir, device="cuda", compute_type="int8_float16"); load = round(time.time() - t0, 2)
files = sorted(glob.glob(os.path.join(adir, "*_clean.wav")))
def run():
    out = []
    for f in files:
        x = wave.open(f); a = np.frombuffer(x.readframes(x.getnframes()), np.int16).astype(np.float32) / 32768.0; x.close()
        t = time.time(); segs, _ = m.transcribe(a, language="ko", beam_size=5, vad_filter=False)
        out.append({"file": os.path.basename(f), "text": "".join(s.text for s in segs).strip(), "seconds": round(time.time() - t, 3)})
    return out
p1 = run(); open(os.path.join(w, "stt_ready"), "w").close(); print("STT ready", load, flush=True)
while not os.path.exists(os.path.join(w, "go2")):
    if os.path.exists(os.path.join(w, "stop")):
        print("STT stop before go2", flush=True); os._exit(0)
    time.sleep(0.5)
p2 = run(); open(os.path.join(w, "stt_done2"), "w").close(); print("STT pass2 done", flush=True)
json.dump({"load_s": load, "pass1_alone": p1, "pass2_with_llm": p2}, open(os.path.join(w, "stt_cohost.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
while not os.path.exists(os.path.join(w, "stop")): time.sleep(0.5)
print("STT exit", flush=True); os._exit(0)
