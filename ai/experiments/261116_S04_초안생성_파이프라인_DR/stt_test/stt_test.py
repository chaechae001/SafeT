"""(v2: 음성을 numpy 배열로 직접 넘김) faster-whisper(large-v3-turbo CT2) 한국어 인식 시험. det-sam3 venv(3.12)에서 실행. 입력은 합성 TTS 음성(Windows Heami)과 잡음 추가본.
사용: python stt_test.py MODEL_DIR AUDIO_DIR OUT_JSON DEVICE COMPUTE"""
import glob, json, os, sys, time, wave
import numpy as np
mdir, adir, out, dev, comp = sys.argv[1:6]
from faster_whisper import WhisperModel
import faster_whisper, ctranslate2
t0 = time.time()
m = WhisperModel(mdir, device=dev, compute_type=comp, cpu_threads=2)
load_s = round(time.time() - t0, 2)
res = []
for f in sorted(glob.glob(os.path.join(adir, "*.wav"))):
    t = time.time()
    w = wave.open(f); a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0; w.close()  # av 19와 faster-whisper 1.2.1의 디코딩 비호환을 피해 16 kHz 배열로 직접 넘긴다
    segs, info = m.transcribe(a, language="ko", beam_size=5, vad_filter=False)
    text = "".join(s.text for s in segs).strip()
    res.append({"file": os.path.basename(f), "text": text, "seconds": round(time.time() - t, 3), "audio_s": round(info.duration, 2)})
    print(res[-1]["file"], res[-1]["seconds"], text, flush=True)
json.dump({"device": dev, "compute_type": comp, "load_s": load_s, "faster_whisper": faster_whisper.__version__,
           "ctranslate2": ctranslate2.__version__, "python": sys.version.split()[0], "results": res},
          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("DONE", dev, comp, len(res))
