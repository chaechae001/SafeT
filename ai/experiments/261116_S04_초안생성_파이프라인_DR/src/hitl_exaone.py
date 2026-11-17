"""추천 단계 LLM = K-EXAONE 2.5 API(외부). 인덱스 v2 검색 후보를 EXAONE이 정렬·설명한다(E_exaone).

공식 문서(https://docs.exaone.ai/ko/docs/k-exaone-2.5, 2026-11-16 확인):
  POST https://api.exaone.ai/v1/chat/completions, Authorization: Bearer, OpenAI 호환, model = "k-exaone_v2.5",
  추론은 항상 켜짐(reasoning_effort low|high|max), 권장 temperature 1.0·top_p 0.95. 호출 한도 수치는 문서에 없음
  → 응답 헤더(x-*-rate-limit-remaining, retry-after)를 읽어 따른다.
외부로 보내는 것: 기기 표준명, 위험코드 명칭, 공개 자료(점검표·D8 보고서 표·D5 안내서) 근거 문장과 출처 ID만.
  사례(CASE-*)·회사 원본·사진·정답셋 원문·현장 설명은 보내지 않는다(build_prompts에서 검사).
키: 환경 변수 EXAONE_API_KEY_FILE이 가리키는 파일에서만 읽는다. 키 값은 출력·기록하지 않는다.

python src/hitl_exaone.py dump                → api/prompts_exaone_hitl_v1.json (호출 없음)
EXAONE_API_KEY_FILE=... python src/hitl_exaone.py call   → api/outputs/exaone_hitl_v1.json (외부 API 호출)
python src/hitl_exaone.py replay              → runs/hitl_recommend/ (호출 없음)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hitl_recommend import OUT_DIR, HitlRecommender  # noqa: E402
from s04_pipeline import ROOT, clean_measure_text, control_type_of, now_kst  # noqa: E402

API_URL = "https://api.exaone.ai/v1/chat/completions"
MODEL = "k-exaone_v2.5"
PARAMS = {"temperature": 1.0, "top_p": 0.95, "reasoning_effort": "low", "max_tokens": 8192}
PROMPT_VERSION = "hitl-E-v1"
LINKS = ROOT.parent / "261115_RAG_지식베이스_DR" / "261116_RAG_기기위험요인링크_v2_DR.jsonl"
PUBLIC_TYPES = {"checklist", "d8_table", "d5_visual"}
PROMPTS = ROOT / "api" / "prompts_exaone_hitl_v1.json"
RAW = ROOT / "api" / "outputs" / "exaone_hitl_v1.json"
SYSTEM = ("너는 음식점 위험성평가를 돕는 추천 도구다. 최종 선택과 판단은 사용자가 한다. 주어진 후보와 근거 안에서만 답한다. "
          "새 위험요인을 만들지 않는다. 위험도·등급·점수·신호는 쓰지 않는다. 출력은 JSON 객체 하나만 쓴다.")
CT = {"elimination_substitution", "engineering", "administrative", "ppe"}


def public_links() -> dict:
    out: dict = {}
    for line in LINKS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        l = json.loads(line)
        if l["source_type"] not in PUBLIC_TYPES or l["source_id"].startswith("CASE-"):
            continue
        out.setdefault((l["equipment_id"], l["hazard_code"]), []).append(l)
    return out


def pool_for(rec: HitlRecommender, links: dict, eid: str) -> list[dict]:
    """인덱스 v2 엄격 후보(R_index_v2 순서) + 후보별 공개 근거(출처 ID·문장)."""
    pool = []
    for c in rec.retrieve_v2(eid):
        ls = links.get((eid, c["hazard_code"]), [])
        ev, seen = [], set()
        for l in ls:
            if l["source_id"] in seen:
                continue
            seen.add(l["source_id"])
            ev.append({"source_id": l["source_id"], "text": clean_measure_text(re.sub(r"\s+", " ", l["hazard_text"]), 90)})
        if ev:
            pool.append(dict(c, evidence=ev[:4]))
    return pool


def prompt(rec: HitlRecommender, eid: str, pool: list[dict]) -> list[dict]:
    name = rec.em.equipment[eid]["standard_name"]
    lines = []
    for p in pool:
        lines.append(f'- 후보 {p["hazard_code"]} ({rec.codes[p["hazard_code"]]})')
        lines += [f'  - [{e["source_id"]}] {e["text"]}' for e in p["evidence"]]
    user = f"""기기: {name}

위험요인 후보와 근거(출처 ID와 공개 자료 문장):
{chr(10).join(lines)}

할 일: 위 후보를 이 기기와 관련 높은 순으로 정렬한다. 근거 문장이 이 기기와 관련 없으면 그 후보는 뺀다.
규칙:
1. code는 위 후보 코드만 쓴다. 같은 code를 두 번 쓰지 않는다. 새 위험요인을 만들지 않는다.
2. source_ids에는 그 후보 아래에 적힌 출처 ID만 1개 이상 쓴다.
3. rationale은 근거 문장에 있는 내용만으로 한국어 한두 문장으로 쓴다. 위험의 높고 낮음은 쓰지 않는다.
4. 위험도·등급·점수·신호는 쓰지 않는다.
출력 형식(JSON 하나): {{"ranked":[{{"code":"후보 코드","source_ids":["출처 ID"],"rationale":"설명"}}]}}"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def build_prompts(rec: HitlRecommender) -> dict:
    links = public_links()
    calls, empty = [], []
    for eid in rec.em.equipment:
        pool = pool_for(rec, links, eid)
        if not pool:
            empty.append(eid)
            continue
        msgs = prompt(rec, eid, pool)
        body = msgs[1]["content"]
        assert "CASE-" not in body and "현장 설명" not in body, eid   # 보내지 않는 자료 검사
        calls.append({"unit_id": f"E:{eid}", "equipment_id": eid, "messages": msgs,
                      "pool": [{"hazard_code": p["hazard_code"], "source_ids": [e["source_id"] for e in p["evidence"]]} for p in pool]})
    return {"created_at": now_kst(), "prompt_version": PROMPT_VERSION, "model": MODEL, "params": PARAMS,
            "sent_data": "기기 표준명, 위험코드 명칭, 공개 자료(점검표·D8 보고서 표·D5 안내서) 근거 문장·출처 ID",
            "no_call_equipment(no_source_found)": empty, "calls": calls}


# ---------------------------------------------------------------- 호출
def _key() -> str:
    p = os.environ.get("EXAONE_API_KEY_FILE")
    if not p or not Path(p).exists():
        raise RuntimeError("EXAONE_API_KEY_FILE 미설정 또는 파일 없음")
    k = Path(p).read_text(encoding="utf-8").strip()
    if not k:
        raise RuntimeError("키 파일이 비어 있음")
    return k


def _post(key: str, messages: list[dict]) -> tuple[int, dict, dict, float]:
    body = json.dumps({"model": MODEL, "messages": messages, "stream": False, **PARAMS}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            code, hdr, data = r.status, dict(r.headers), json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        code, hdr = e.code, dict(e.headers)
        try:
            data = json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            data = {"error": "본문 해석 실패"}
    sec = round(time.time() - t, 2)
    rl = {k: v for k, v in hdr.items() if k.lower().startswith(("x-second", "x-minute", "x-day", "retry-after"))}
    return code, rl, data, sec


def parse(content: str | None):
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        d = None
    return d if isinstance(d, dict) and isinstance(d.get("ranked"), list) else None


def cmd_call():
    prompts = json.loads(PROMPTS.read_text(encoding="utf-8"))
    key = _key()
    RAW.parent.mkdir(parents=True, exist_ok=True)
    out = {"model": MODEL, "api_url": API_URL, "params": PARAMS, "prompt_version": prompts["prompt_version"],
           "prompts_sha256": hashlib.sha256(PROMPTS.read_bytes()).hexdigest(), "started_at": now_kst(),
           "execution_location": "EXAONE API(외부)", "retry_rule": "429는 retry-after(없으면 10·20·40초) 후 재시도, JSON 파싱 실패는 1회 재시도",
           "results": []}
    for c in prompts["calls"]:
        res = {"unit_id": c["unit_id"], "messages": c["messages"], "attempts": [], "accepted_attempt": None}
        n_parse_retry, backoff = 0, 10
        while len(res["attempts"]) < 6:
            code, rl, data, sec = _post(key, c["messages"])
            msg = (data.get("choices") or [{}])[0].get("message", {}) if code == 200 else {}
            att = {"at": now_kst(), "http_status": code, "seconds": sec, "rate_limit_headers": rl,
                   "content": msg.get("content"), "reasoning_content": msg.get("reasoning_content"),
                   "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason") if code == 200 else None,
                   "usage": data.get("usage"), "response_model": data.get("model"),
                   "error": None if code == 200 else data}
            res["attempts"].append(att)
            print(now_kst(), c["unit_id"], "http", code, "sec", sec, "parse", parse(att["content"]) is not None, flush=True)
            if code == 429:
                ra = rl.get("retry-after") or rl.get("Retry-After")
                time.sleep(float(ra) if ra else backoff)
                backoff *= 2
                continue
            if code != 200:
                break
            if parse(att["content"]) is not None:
                res["accepted_attempt"] = len(res["attempts"])
                break
            n_parse_retry += 1
            if n_parse_retry > 1:
                break
        out["results"].append(res)
        RAW.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(1.0)
    out["finished_at"] = now_kst()
    RAW.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("DONE", sum(r["accepted_attempt"] is not None for r in out["results"]), "/", len(out["results"]))


# ---------------------------------------------------------------- 재생·응답 조립(계약 v2)
E35 = {"raw": ROOT / "cloud" / "e35" / "outputs" / "cloud_outputs_e35_v1.json", "method": "E35_awq",
       "model_version": "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-AWQ@f2699f35(vLLM 0.10.1.1)",
       "location": "Elice Cloud(A100 MIG 1g.10gb)", "out": "v2_E35_awq.json", "stats": "exaone35_awq_stats.json"}
E35_ENUM = {"raw": ROOT / "cloud" / "e35" / "outputs" / "cloud_outputs_e35_enum_v1.json", "method": "E35_awq_enum",
            "model_version": "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-AWQ@f2699f35(vLLM 0.10.1.1, guided JSON enum)",
            "location": "Elice Cloud(A100 MIG 1g.10gb)", "out": "v2_E35_awq_enum.json", "stats": "exaone35_awq_enum_stats.json"}


def build_candidates(rec, eid: str, pool: list[dict], v2pool_eid: dict, d: dict, kw: dict, st: dict) -> list[dict]:
    """LLM 출력(d: {"ranked": [...]})을 계약 v2 후보 목록으로 바꾼다. 후보 밖 코드·중복·잘못된 출처 ID는 버리고 st에 센다."""
    from hitl_contract_v2 import ref
    cands: list[dict] = []
    allowed = {p["hazard_code"]: set(p["source_ids"]) for p in pool}
    for x in d["ranked"]:
        if not isinstance(x, dict):
            continue
        code = str(x.get("code", "")).strip()
        if code not in allowed:
            st["outside_pool_codes"] += 1
            continue
        if code in [c["accident_type"]["code"] for c in cands]:
            st["dup_codes"] += 1
            continue
        sids = [s for s in (x.get("source_ids") or []) if isinstance(s, str)]
        good = [s for s in sids if s in allowed[code]]
        st["invalid_source_ids"] += len(sids) - len(good)
        if not good:
            st["dropped_no_valid_source"] += 1
            continue
        rat = str(x.get("rationale", "")).strip() or f'근거 {", ".join(good)}'
        if re.search(r"위험(도|성)?(이|가)?\s*(높|낮|크|작)", rat):
            st["judgement_words"] += 1
        p = v2pool_eid[code]
        ms = []
        for i, m in enumerate(p["v2_measures"]):
            ms.append({"measure_id": f"m-{eid}-{code}-{i + 1}", "text": clean_measure_text(m["text"])[:120],
                       "control_type": (lambda t: t if t in CT else None)(control_type_of(m["text"], kw)),
                       "source_refs": [ref(s, "rag-kb-v2-index") for s in m["source_ids"]]})
        cands.append({"candidate_id": f"{eid}:{code}", "work": None,
                      "hazard": (p["hazard_text"] or rec.codes[code])[:120],
                      "accident_type": {"code": code, "label": rec.codes[code]},
                      "rationale": rat[:300], "source_refs": [ref(s, "rag-kb-v2-index") for s in good],
                      "measure_candidates": ms})
    return cands


def cmd_replay(raw_path=RAW, method="E_exaone", model_version=None, location="EXAONE API(외부)",
               out_name="v2_E_exaone.json", stats_name="exaone_stats.json"):
    from jsonschema import Draft202012Validator, FormatChecker  # noqa: F401
    from hitl_contract_v2 import ref, validator
    rec = HitlRecommender()
    prompts = json.loads(PROMPTS.read_text(encoding="utf-8"))
    raw = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    mv = model_version or f'{MODEL}@api({raw["started_at"][:10]})'
    by_unit = {r["unit_id"]: r for r in raw["results"]}
    v = validator()
    kw = rec.pipe.cfg["measures"]["control_type_keywords"]
    st = {"calls": len(prompts["calls"]), "http_ok": 0, "parse_ok": 0, "retries": 0, "outside_pool_codes": 0, "dup_codes": 0,
          "invalid_source_ids": 0, "dropped_no_valid_source": 0, "judgement_words": 0, "candidates": 0, "seconds": [],
          "reasoning_tokens": [], "completion_tokens": [], "schema_valid": 0, "responses": 0, "errors": []}
    ranked, responses = {}, []
    pools = {c["equipment_id"]: c for c in prompts["calls"]}
    v2pool = {}
    for eid in rec.em.equipment:
        v2pool[eid] = {p["hazard_code"]: p for p in rec.retrieve_v2(eid)}
    for eid in rec.em.equipment:
        cands = []
        if eid in pools:
            r = by_unit.get(f"E:{eid}")
            if r is None:
                raise RuntimeError(f"API 응답 누락 {eid}")
            if r["messages"] != pools[eid]["messages"]:
                raise RuntimeError(f"프롬프트 불일치 {eid}")
            st["retries"] += len(r["attempts"]) - 1
            st["seconds"] += [a["seconds"] for a in r["attempts"] if a.get("http_status", 200) == 200]   # 429 즉시 거절은 시간에서 제외
            st["http_429"] = st.get("http_429", 0) + sum(a.get("http_status") == 429 for a in r["attempts"])
            att = r["attempts"][(r["accepted_attempt"] or len(r["attempts"])) - 1]
            st["http_ok"] += att.get("http_status", 200) == 200
            u = att.get("usage") or {}
            if u:
                st["completion_tokens"].append(u.get("completion_tokens"))
                st["reasoning_tokens"].append(u.get("reasoning_tokens") or (u.get("completion_tokens_details") or {}).get("reasoning_tokens"))
            d = parse(att["content"])
            if d is not None:
                st["parse_ok"] += 1
                cands = build_candidates(rec, eid, pools[eid]["pool"], v2pool[eid], d, kw, st)
        st["candidates"] += len(cands)
        ranked[eid] = [c["accident_type"]["code"] for c in cands]
        resp = {"request_id": f"hitl-eq-{eid}", "call": "hazard_candidates_v2",
                "status": "ok" if cands else "partial", "model_version": mv,
                "kb_version": "rag-kb-v2-index", "generated_at": raw.get("finished_at") or raw["started_at"],
                "groups": [{"equipment_id": eid, "display_name": rec.em.equipment[eid]["standard_name"],
                            "group_status": "ok" if cands else "no_source_found", "candidates": cands}]}
        errs = [e.message[:150] for e in v.iter_errors(resp)]
        st["responses"] += 1
        st["schema_valid"] += not errs
        st["errors"] += errs[:2]
        responses.append(resp)
    secs = st.pop("seconds")
    st["seconds_mean"] = round(sum(secs) / len(secs), 2) if secs else None
    st["seconds_total"] = round(sum(secs), 1)
    st["seconds_max"] = max(secs) if secs else None
    rt = [x for x in st.pop("reasoning_tokens") if x is not None]
    ct = [x for x in st.pop("completion_tokens") if x is not None]
    st["reasoning_tokens_mean"] = round(sum(rt) / len(rt), 1) if rt else "미확인"
    st["completion_tokens_mean"] = round(sum(ct) / len(ct), 1) if ct else "미확인"
    cdir = OUT_DIR / "contract_v2"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / out_name).write_text(json.dumps(responses, ensure_ascii=False, indent=1), encoding="utf-8")
    rk_path = OUT_DIR / "ranked_codes.json"
    rk = json.loads(rk_path.read_text(encoding="utf-8"))
    rk["ranked"][method] = ranked
    rk[f"{method}_model_version"] = f"{mv} ({location})"
    rk_path.write_text(json.dumps(rk, ensure_ascii=False, indent=1), encoding="utf-8")
    st["execution_location"] = location
    st["model_version"] = mv
    st["api_window"] = [raw["started_at"], raw.get("finished_at")]
    (OUT_DIR / stats_name).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    if sys.argv[1] == "dump":
        rec = HitlRecommender()
        d = build_prompts(rec)
        PROMPTS.parent.mkdir(parents=True, exist_ok=True)
        PROMPTS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(len(d["calls"]), "calls; no_source_found:", len(d["no_call_equipment(no_source_found)"]))
    elif sys.argv[1] == "call":
        cmd_call()
    elif sys.argv[1] == "replay":
        cmd_replay()
    elif sys.argv[1] == "replay_e35":
        cmd_replay(E35["raw"], E35["method"], E35["model_version"], E35["location"], E35["out"], E35["stats"])
    elif sys.argv[1] == "replay_e35_enum":
        x = E35_ENUM
        cmd_replay(x["raw"], x["method"], x["model_version"], x["location"], x["out"], x["stats"])
