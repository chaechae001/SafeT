"""EXAONE 3.5 AWQ(vLLM, 3.11)를 STT가 올라간 상태에서 낮은 메모리 비율로 올려 enum 추천 25건을 실행한다.
사용: python e35_cohost.py ENUM_SCRIPT_DIR PROMPTS WORKDIR UTIL"""
import gc, json, os, sys, time
sd, pf, w, util = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
sys.path.insert(0, sd)
from infer_exaone35_awq_enum import REV, REPO, schema_for, ok  # 3.10/3.11 기존 실행과 같은 스키마 생성
from huggingface_hub import snapshot_download
from vllm import LLM, SamplingParams
from vllm.sampling_params import GuidedDecodingParams
prompts = json.load(open(pf, encoding="utf-8"))
t0 = time.time()
llm = LLM(model=snapshot_download(REPO, revision=REV), trust_remote_code=True, guided_decoding_backend="xgrammar",
          max_model_len=4096, gpu_memory_utilization=util, enforce_eager=True, seed=0)
load = round(time.time() - t0, 2); print("LLM loaded", util, load, flush=True)
res = []
for c in prompts["calls"]:
    gd = GuidedDecodingParams(json=schema_for(c["pool"], False))  # xgrammar가 uniqueItems 미지원 — 기존 enum 실행도 같은 대체 경로를 탔다
    t = time.time(); o = llm.chat(c["messages"], SamplingParams(temperature=0.0, seed=0, max_tokens=1024, guided_decoding=gd), use_tqdm=False)[0]
    res.append({"unit_id": c["unit_id"], "content": o.outputs[0].text, "ok": ok(o.outputs[0].text), "seconds": round(time.time() - t, 3)})
open(os.path.join(w, "go2"), "w").close()
while not os.path.exists(os.path.join(w, "stt_done2")): time.sleep(0.5)
json.dump({"util": util, "load_s": load, "results": res}, open(os.path.join(w, f"e35_cohost_util{util}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
try:
    llm.llm_engine.engine_core.shutdown()
except Exception as e:
    print("shutdown 실패", e, flush=True)
del llm; gc.collect()
print("E35 done", sum(r["ok"] for r in res), "/", len(res), flush=True); os._exit(0)
