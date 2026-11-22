"""v2 검증셋 TTS 음성을 운영 관문 STT(/v1/transcribe)로 전사한다. 자동 재시도 없음."""
import base64, json, os, sys, time, urllib.request
from pathlib import Path
W = Path(__file__).resolve().parent
key = (Path.home() / "safet/deploy/secrets/api_key").read_text().strip()
out = []
for wav in sorted((W / "audio").glob("V*.wav")):
    body = json.dumps({"audio_base64": base64.b64encode(wav.read_bytes()).decode(), "request_id": "neg261123_" + wav.stem}).encode()
    req = urllib.request.Request("http://127.0.0.1:8010/v1/transcribe", data=body,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read())
    out.append(dict(id=wav.stem, text=res["text"], audio_s=res["audio_s"], stt_seconds=res["seconds"],
                    wall_seconds=round(time.time() - t, 3), model=res["model"], transcribed_at=res["transcribed_at"]))
    print(wav.stem, res["text"], flush=True)
(W / "stt_v2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
