"""[enum 강제판] EXAONE 3.5 7.8B Instruct AWQ 로컬(Cloud) 추론 — K-EXAONE 2.5 API 비교와 같은 프롬프트(api/prompts_exaone_hitl_v1.json 사본).
공식 저장소(고정 revision)의 configuration_exaone.py 실행을 위해 trust_remote_code=True. 모델 계산은 vLLM 내장 Exaone 구현.
vLLM guided JSON(xgrammar). 호출마다 pool에서 스키마 생성: ranked 항목 = anyOf[후보별 {code: const, source_ids: 그 후보 출처 ID enum}], maxItems=후보 수.
uniqueItems(source_ids)는 넣어 보고, 백엔드가 거부하면 빼고 다시 시도하며 그 사실을 기록한다.
재시도: 파싱·구조 실패 시 최대 2회(temperature 0.7, seed=시도 번호). 1차는 greedy(temperature 0).
사용: python infer_exaone35_awq.py PROMPTS OUT TIMELINE
"""
import hashlib, json, sys, time, datetime, gc, os

T = lambda: time.time()
KST = datetime.timezone(datetime.timedelta(hours=9))
now = lambda: datetime.datetime.now(KST).isoformat(timespec="seconds")
REPO = "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-AWQ"
REV = "f2699f35d5b4ba511ab93826c22bd07370296b5c"  # 2024-12-11 공식 revision. 가중치·토크나이저 LFS 해시는 최신 e5026081(transformers v5용 설정 코드)과 동일, configuration/modeling_exaone.py만 transformers 4.x용
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ranked"],
          "properties": {"ranked": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                         "required": ["code", "source_ids", "rationale"],
                         "properties": {"code": {"type": "string"}, "source_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                                        "rationale": {"type": "string"}}}}}}


def mark(tl, ev, **kw):
    tl.write(json.dumps({"t": T(), "at": now(), "event": ev, **kw}, ensure_ascii=False) + "\n"); tl.flush()


def schema_for(pool, unique=True):
    items = []
    for p in pool:
        sid = {"type": "array", "minItems": 1, "items": {"type": "string", "enum": p["source_ids"]}}
        if unique:
            sid["uniqueItems"] = True
        items.append({"type": "object", "additionalProperties": False, "required": ["code", "source_ids", "rationale"],
                      "properties": {"code": {"type": "string", "const": p["hazard_code"]}, "source_ids": sid,
                                     "rationale": {"type": "string"}}})
    return {"type": "object", "additionalProperties": False, "required": ["ranked"],
            "properties": {"ranked": {"type": "array", "minItems": 1, "maxItems": len(pool), "items": {"anyOf": items}}}}


def ok(content):
    try:
        d = json.loads(content)
    except Exception:
        return False
    return isinstance(d, dict) and isinstance(d.get("ranked"), list) and all(
        isinstance(x, dict) and isinstance(x.get("code"), str) and isinstance(x.get("source_ids"), list) for x in d["ranked"])


def main():
    pf, outf, tlf = sys.argv[1:4]
    prompts = json.load(open(pf, encoding="utf-8"))
    tl = open(tlf, "a", encoding="utf-8")
    from huggingface_hub import snapshot_download
    path = snapshot_download(REPO, revision=REV)
    import torch, vllm
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import GuidedDecodingParams
    mark(tl, "e35enum_load_start")
    llm = LLM(model=path, trust_remote_code=True, guided_decoding_backend="xgrammar", max_model_len=4096, gpu_memory_utilization=0.85, enforce_eager=True, seed=0)
    mark(tl, "e35enum_load_done")
    unique = True
    schema_notes = []
    out = {"model": REPO, "revision": REV, "local_path": path, "engine": f"vllm {vllm.__version__}", "torch": torch.__version__,
           "gpu": torch.cuda.get_device_name(0), "params": {"first": "temperature 0 (greedy)", "retry": "temperature 0.7, seed=attempt",
           "max_tokens": 1024, "max_model_len": 4096, "gpu_memory_utilization": 0.85, "enforce_eager": True, "trust_remote_code": True, "guided_json": "기기별 enum(anyOf: 후보 code const + 그 후보 source_ids enum), maxItems=후보 수", "guided_backend": "xgrammar"},
           "prompt_version": prompts["prompt_version"], "prompts_sha256": hashlib.sha256(open(pf, "rb").read()).hexdigest(),
           "started_at": now(), "execution_location": "Elice Cloud(A100 MIG 1g.10gb)",
           "retry_rule": "구조·파싱 실패 시 최대 2회 재시도", "results": []}
    for c in prompts["calls"]:
        res = {"unit_id": c["unit_id"], "messages": c["messages"], "attempts": [], "accepted_attempt": None}
        for a in range(3):
            t0 = T()
            while True:
                sp = SamplingParams(temperature=0.0 if a == 0 else 0.7, seed=a, max_tokens=1024,
                                    guided_decoding=GuidedDecodingParams(json=schema_for(c["pool"], unique)))
                try:
                    o = llm.chat(c["messages"], sp, use_tqdm=False)[0]
                    break
                except Exception as e:  # 스키마 기능 미지원 시 uniqueItems를 빼고 한 번만 다시
                    if not unique:
                        raise
                    unique = False
                    schema_notes.append({"unit_id": c["unit_id"], "error": repr(e)[:500], "action": "uniqueItems 제거 후 재시도"})
                    print("SCHEMA_FALLBACK", repr(e)[:300], flush=True)
                    t0 = T()
            sec = round(T() - t0, 3)
            g = o.outputs[0]
            att = {"at": now(), "seconds": sec, "content": g.text, "finish_reason": g.finish_reason,
                   "usage": {"prompt_tokens": len(o.prompt_token_ids), "completion_tokens": len(g.token_ids)}}
            res["attempts"].append(att)
            print(now(), c["unit_id"], "attempt", a + 1, "sec", sec, "ok", ok(g.text), flush=True)
            if ok(g.text):
                res["accepted_attempt"] = a + 1
                break
        out["results"].append(res)
        json.dump(out, open(outf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out["finished_at"] = now()
    out["uniqueItems_used"] = unique
    out["schema_notes"] = schema_notes
    json.dump(out, open(outf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    mark(tl, "e35enum_unload_start")
    del llm; gc.collect(); torch.cuda.empty_cache()
    mark(tl, "e35enum_unload_done_inproc")
    print("DONE", sum(r["accepted_attempt"] is not None for r in out["results"]), "/", len(out["results"]), flush=True)


if __name__ == "__main__":
    main()
