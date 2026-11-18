"""Elice Cloud에서 S04 프롬프트로 Qwen2.5-VL-3B-Instruct를 실행한다(텍스트 입력만).

- 새 설치·다운로드 없음: HF 캐시에 있는 모델만 쓴다(HF_HUB_OFFLINE=1).
- 프롬프트당 3회 시도: 1회 greedy, 2·3회 sampling(temperature 0.7, top_p 0.9, seed 1·2).
- 출력: cloud_outputs.json (원본 응답·토큰 수·시간·메모리), infer_log.txt
실행: /home/elicer/safet-venv/bin/python infer_qwen25vl_s04.py prompts_s04.json cloud_outputs.json
"""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import datetime as dt
import json
import platform
import sys
import time
from pathlib import Path

import torch
import transformers
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
KST = dt.timezone(dt.timedelta(hours=9))
MAX_NEW = 3072
ATTEMPTS = [
    {"do_sample": False},
    {"do_sample": True, "temperature": 0.7, "top_p": 0.9, "seed": 1},
    {"do_sample": True, "temperature": 0.7, "top_p": 0.9, "seed": 2},
]


def now():
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def main(prompts_path, out_path):
    hub = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-VL-3B-Instruct"
    revision = (hub / "refs/main").read_text().strip()
    prompts = json.loads(Path(prompts_path).read_text(encoding="utf-8"))
    print(now(), "revision", revision, "prompts", len(prompts["prompts"]), flush=True)
    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_ID, revision=revision)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL_ID, revision=revision, torch_dtype=torch.bfloat16, device_map="cuda")
    model.eval()
    load_sec = round(time.time() - t0, 1)
    print(now(), "loaded", load_sec, "s", flush=True)
    out = {
        "model_id": MODEL_ID, "revision": revision, "started_at": now(),
        "env": {"python": platform.python_version(), "torch": torch.__version__, "transformers": transformers.__version__,
                "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
                "gpu_total_gb_visible": round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1)},
        "load_sec": load_sec, "max_new_tokens": MAX_NEW, "dtype": "bfloat16", "input": "text only (no images)",
        "pipeline_version": prompts.get("pipeline_version"), "results": [],
    }
    for p in prompts["prompts"]:
        text = processor.apply_chat_template(p["messages"], tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], return_tensors="pt").to("cuda")
        n_in = int(inputs["input_ids"].shape[1])
        res = {"request_id": p["request_id"], "messages": p["messages"], "input_tokens": n_in, "attempts": []}
        for i, a in enumerate(ATTEMPTS):
            kw = {k: v for k, v in a.items() if k != "seed"}
            if "seed" in a:
                torch.manual_seed(a["seed"])
            torch.cuda.reset_peak_memory_stats()
            t = time.time()
            with torch.no_grad():
                gen = model.generate(**inputs, max_new_tokens=MAX_NEW, **kw)
            sec = round(time.time() - t, 2)
            new = gen[0, n_in:]
            content = processor.decode(new, skip_special_tokens=True)
            res["attempts"].append({
                "attempt": i + 1, "params": a, "content": content, "output_tokens": int(new.shape[0]),
                "hit_max_new_tokens": int(new.shape[0]) >= MAX_NEW, "seconds": sec,
                "peak_gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2), "finished_at": now()})
            print(now(), p["request_id"], "attempt", i + 1, "tokens", int(new.shape[0]), "sec", sec, flush=True)
            Path(out_path).write_text(json.dumps(out | {"results": out["results"] + [res]}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        out["results"].append(res)
    out["finished_at"] = now()
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(now(), "DONE", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
