"""STT 문자 오류율(CER) 평가. 공백·문장부호를 빼고 글자 단위 편집 거리를 정답 글자 수로 나눈다. 정답은 합성 TTS 원문(sentences.json)."""
import json, re, csv, statistics as st, sys
ref = {s["id"]: s["text"] for s in json.load(open("sentences.json", encoding="utf-8"))}
norm = lambda t: re.sub(r"[\s\.,!?·~\-]", "", t)
def ed(a, b):
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        p, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (x != y))
    return d[-1]
out = {}
for tag in ("cuda_int8f16", "cpu_int8"):
    r = json.load(open(f"outputs/out_{tag}.json", encoding="utf-8"))
    rows = []
    for x in r["results"]:
        sid, cond = x["file"][:3], x["file"][4:-4]
        a, h = norm(ref[sid]), norm(x["text"])
        rows.append({"id": sid, "cond": cond, "cer": round(ed(a, h) / len(a), 4), "rtf": round(x["seconds"] / x["audio_s"], 3), "sec": x["seconds"], "hyp": x["text"]})
    summ = {c: {"cer_mean": round(st.mean(z["cer"] for z in rows if z["cond"] == c), 4), "exact": sum(z["cer"] == 0 for z in rows if z["cond"] == c),
                "sec_mean": round(st.mean(z["sec"] for z in rows if z["cond"] == c), 3), "rtf_mean": round(st.mean(z["rtf"] for z in rows if z["cond"] == c), 3)} for c in ("clean", "snr10")}
    out[tag] = {"load_s": r["load_s"], "versions": {k: r[k] for k in ("python", "faster_whisper", "ctranslate2")}, "summary": summ, "rows": rows}
t = [(float(a), int(b)) for a, b in csv.reader(open("outputs/vram.csv")) if b]
out["cuda_int8f16"]["peak_vram_mib"] = max(m for _, m in t)
json.dump(out, open("outputs/stt_eval.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for k, v in out.items():
    print(k, "load", v["load_s"], v["summary"], v.get("peak_vram_mib"))
for z in out["cuda_int8f16"]["rows"]:
    if z["cer"] > 0: print(z["id"], z["cond"], z["cer"], ref[z["id"]], "→", z["hyp"])
