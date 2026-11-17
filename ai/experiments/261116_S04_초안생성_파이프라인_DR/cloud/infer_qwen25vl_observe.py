"""사진 상태 관찰(VLM) Cloud 추론. Qwen2.5-VL-3B-Instruct(revision 고정), 캐시된 모델만 사용(HF_HUB_OFFLINE=1).

입력: prompts_observe_v1.json (calls[]: case_id, photo_id, image_file, messages), images/ 폴더
이미지 크기 상한: max_pixels = 1024*28*28 (약 80만 화소). 시도 1 greedy → JSON 파싱 실패 시에만 sampling(seed 1, 2).
실행: /home/elicer/safet-venv/bin/python infer_qwen25vl_observe.py prompts_observe_v1.json cloud_outputs_observe_v1.json
"""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import datetime as dt
import json
import platform
import re
import sys
import time
from pathlib import Path

import torch
import transformers
from PIL import Image
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
EXPECTED_REVISION = "66285546d2b821cf421d4f5eb2576359d3770cd3"
KST = dt.timezone(dt.timedelta(hours=9))
MAX_NEW = 1024
MAX_PIXELS = 1024 * 28 * 28
ATTEMPTS = [
    {"do_sample": False},
    {"do_sample": True, "temperature": 0.7, "top_p": 0.9, "seed": 1},
    {"do_sample": True, "temperature": 0.7, "top_p": 0.9, "seed": 2},
]


def now():
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def parse_ok(content, key="observations"):
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return False
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return False
    return isinstance(d, dict) and isinstance(d.get(key), list)


def main(prompts_path, out_path):
    base = Path(prompts_path).resolve().parent
    hub = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-VL-3B-Instruct"
    revision = (hub / "refs/main").read_text().strip()
    assert revision == EXPECTED_REVISION, revision
    prompts = json.loads(Path(prompts_path).read_text(encoding="utf-8"))
    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_ID, revision=revision, max_pixels=MAX_PIXELS)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL_ID, revision=revision, dtype=torch.bfloat16, device_map="cuda")
    model.eval()
    out = {"model_id": MODEL_ID, "revision": revision, "started_at": now(), "load_sec": round(time.time() - t0, 1),
           "env": {"python": platform.python_version(), "torch": torch.__version__, "transformers": transformers.__version__,
                   "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0)},
           "max_new_tokens": MAX_NEW, "max_pixels": MAX_PIXELS, "dtype": "bfloat16",
           "retry_rule": "JSON 파싱 실패(기대 키 배열 없음) 시에만 다음 시도", "results": []}
    print(now(), "revision", revision, "calls", len(prompts["calls"]), "load", out["load_sec"], flush=True)
    for c in prompts["calls"]:
        img = Image.open(base / c["image_file"]).convert("RGB")
        text = processor.apply_chat_template(c["messages"], tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=[img], return_tensors="pt").to("cuda")
        n_in = int(inputs["input_ids"].shape[1])
        res = {k: c[k] for k in ("case_id", "photo_id", "image_file", "messages")}
        res.update(input_tokens=n_in, image_size=list(img.size), attempts=[], accepted_attempt=None)
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
            ok = parse_ok(content, c.get("expect_key", "observations"))
            res["attempts"].append({"attempt": i + 1, "params": a, "content": content, "output_tokens": int(new.shape[0]),
                                    "hit_max_new_tokens": int(new.shape[0]) >= MAX_NEW, "seconds": sec, "parse_ok": ok,
                                    "peak_gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2), "finished_at": now()})
            print(now(), c["case_id"], "attempt", i + 1, "in", n_in, "out", int(new.shape[0]), "sec", sec, "ok", ok, flush=True)
            if ok:
                res["accepted_attempt"] = i + 1
                break
        out["results"].append(res)
        Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    out["finished_at"] = now()
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(now(), "DONE", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
