"""개선 실험(A·B·AB) Cloud 추론. 1차 스크립트와 같은 모델·revision·생성 설정.

차이: 시도를 3회 모두 돌리지 않고, JSON 파싱(아래 parse_ok)이 실패할 때만 다음 시도로 넘어간다.
시도 1 greedy → 시도 2 sampling(seed 1) → 시도 3 sampling(seed 2).
실행: /home/elicer/safet-venv/bin/python infer_qwen25vl_s04_v2.py prompts_s04_v2.json cloud_outputs_v2.json
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
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
EXPECTED_REVISION = "66285546d2b821cf421d4f5eb2576359d3770cd3"
KST = dt.timezone(dt.timedelta(hours=9))
MAX_NEW = 3072
ATTEMPTS = [
    {"do_sample": False},
    {"do_sample": True, "temperature": 0.7, "top_p": 0.9, "seed": 1},
    {"do_sample": True, "temperature": 0.7, "top_p": 0.9, "seed": 2},
]


def now():
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def parse_ok(content):
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return False
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return False
    return isinstance(d, dict) and isinstance(d.get("items"), list)


def main(prompts_path, out_path):
    hub = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-VL-3B-Instruct"
    revision = (hub / "refs/main").read_text().strip()
    assert revision == EXPECTED_REVISION, revision
    prompts = json.loads(Path(prompts_path).read_text(encoding="utf-8"))
    print(now(), "revision", revision, "calls", len(prompts["calls"]), flush=True)
    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_ID, revision=revision)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL_ID, revision=revision, dtype=torch.bfloat16, device_map="cuda")
    model.eval()
    out = {
        "model_id": MODEL_ID, "revision": revision, "started_at": now(), "load_sec": round(time.time() - t0, 1),
        "env": {"python": platform.python_version(), "torch": torch.__version__, "transformers": transformers.__version__,
                "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0)},
        "max_new_tokens": MAX_NEW, "dtype": "bfloat16", "input": "text only (no images)",
        "retry_rule": "JSON 파싱 실패 시에만 다음 시도", "results": [],
    }
    for c in prompts["calls"]:
        text = processor.apply_chat_template(c["messages"], tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], return_tensors="pt").to("cuda")
        n_in = int(inputs["input_ids"].shape[1])
        res = {k: c[k] for k in ("variant", "request_id", "unit_id", "messages")}
        res.update(input_tokens=n_in, attempts=[], accepted_attempt=None)
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
            ok = parse_ok(content)
            res["attempts"].append({"attempt": i + 1, "params": a, "content": content, "output_tokens": int(new.shape[0]),
                                    "hit_max_new_tokens": int(new.shape[0]) >= MAX_NEW, "seconds": sec, "parse_ok": ok,
                                    "peak_gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
                                    "finished_at": now()})
            print(now(), c["variant"], c["request_id"], c["unit_id"], "attempt", i + 1, "tokens", int(new.shape[0]),
                  "sec", sec, "ok", ok, flush=True)
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
