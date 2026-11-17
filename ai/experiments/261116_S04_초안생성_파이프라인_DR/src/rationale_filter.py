"""추천 설명문(rationale)의 위험 정도 판단 표현 후처리 시험. 모델 호출 없음, 파이프라인 미연결(팀 결정 전).

옵션
  (a) flag    : 설명문은 그대로 두고 탐지 결과만 따로 기록한다.
  (b) delete  : 탐지된 문장만 지운다. 남는 문장이 없으면 출처 ID 목록 문장으로 채운다.
  (c) replace : 탐지된 문장을 근거 문장 발췌(출처 ID 포함)로 바꾼다.
규칙: config/rationale_filter.json (그룹별 근거 표시, G3은 작성자 초안).
입력(읽기만): runs/hitl_recommend/contract_v2/v2_{E_exaone,E35_awq,B_rag}.json
출력: runs/hitl_recommend/rationale_filter/
uv run -q --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/rationale_filter.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, now_kst  # noqa: E402

CFG = ROOT / "config" / "rationale_filter.json"
CV2 = ROOT / "runs" / "hitl_recommend" / "contract_v2"
OUT = ROOT / "runs" / "hitl_recommend" / "rationale_filter"
METHODS = {"E_exaone": "K-EXAONE 2.5 API", "E35_awq": "EXAONE 3.5 7.8B AWQ", "B_rag": "Qwen2.5-VL-3B RAG"}
SCOPES = {"documented": ("G1_risk_high_low", "G2_grade_score_signal"),
          "all": ("G1_risk_high_low", "G2_grade_score_signal", "G3_degree_words")}
# 미탐 점검용 느슨한 단서(탐지 규칙이 아님. 사람 검토 목록을 뽑는 데만 쓴다)
LOOSE = re.compile(r"높|낮|크다|큰 |작다|중요|주의가 필요|각별|특히|우선")


def load_cfg(path: Path = CFG) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for g in cfg["groups"]:
        g["_re"] = [re.compile(p) for p in g["patterns"]]
    return cfg


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+", (text or "").strip())
    return [p for p in parts if p]


def detect(cfg: dict, text: str, groups: tuple[str, ...]) -> list[dict]:
    hits = []
    for g in cfg["groups"]:
        if g["group_id"] not in groups:
            continue
        for rx in g["_re"]:
            for m in rx.finditer(text or ""):
                hits.append({"group_id": g["group_id"], "basis": g["basis"], "match": m.group(0), "start": m.start()})
    return sorted(hits, key=lambda h: h["start"])


# ---------------------------------------------------------------- 근거 문장 사전
def evidence_map() -> dict[str, str]:
    """출처 ID → 근거 문장. EXAONE 프롬프트의 '[ID] 문장'과 지식베이스 행·조각에서 모은다(공개 자료만)."""
    ev: dict[str, str] = {}
    p = ROOT / "api" / "prompts_exaone_hitl_v1.json"
    if p.exists():
        for c in json.loads(p.read_text(encoding="utf-8"))["calls"]:
            for msg in c["messages"]:
                for sid, t in re.findall(r"\[([A-Za-z0-9\-]+)\] (.+)", msg["content"]):
                    ev.setdefault(sid, t.strip())
    try:
        from hitl_recommend import HitlRecommender
        kb = HitlRecommender().kb
        for k, r in kb.rows.items():
            ev.setdefault(k, r["source_text"])
        for k, c in kb.chunks.items():
            ev.setdefault(k, c["text"])
    except Exception as e:  # 지식베이스를 못 읽으면 프롬프트 근거만 쓴다
        print("KB 미사용:", e)
    return ev


# ---------------------------------------------------------------- 옵션
def opt_flag(cfg, text, groups, refs, ev):
    return text, detect(cfg, text, groups)


def _fallback(cfg, refs):
    return cfg["replace"]["fallback_template"].format(source_ids=", ".join(r["source_id"] for r in refs))


def opt_delete(cfg, text, groups, refs, ev):
    sents = split_sentences(text)
    keep = [s for s in sents if not detect(cfg, s, groups)]
    hits = detect(cfg, text, groups)
    if not hits:
        return text, hits
    out = " ".join(keep) if keep else _fallback(cfg, refs)
    return out[: cfg["replace"]["max_len"]], hits


def opt_replace(cfg, text, groups, refs, ev):
    hits = detect(cfg, text, groups)
    if not hits:
        return text, hits
    rp = cfg["replace"]
    sub = None
    for r in refs:
        t = ev.get(r["source_id"])
        if t:
            t = re.sub(r"\s+", " ", t).strip()
            sub = rp["template"].format(evidence=t[: rp["evidence_chars"]] + ("…" if len(t) > rp["evidence_chars"] else ""),
                                        source_id=r["source_id"])
            break
    sub = sub or _fallback(cfg, refs)
    out, used = [], False
    for s in split_sentences(text):
        if detect(cfg, s, groups):
            if not used:  # 같은 대체 문장을 반복하지 않는다
                out.append(sub)
                used = True
        else:
            out.append(s)
    return " ".join(out)[: rp["max_len"]], hits


OPTIONS = {"a_flag": opt_flag, "b_delete": opt_delete, "c_replace": opt_replace}


def apply(cfg, responses, groups, option, ev):
    res = copy.deepcopy(responses)
    log = []
    for r in res:
        for g in r["groups"]:
            for c in g["candidates"]:
                new, hits = OPTIONS[option](cfg, c["rationale"], groups, c["source_refs"], ev)
                if hits:
                    log.append({"candidate_id": c["candidate_id"], "before": c["rationale"], "after": new,
                                "hits": [{k: h[k] for k in ("group_id", "basis", "match")} for h in hits]})
                c["rationale"] = new
    return res, log


def ranked_of(responses) -> dict[str, list[str]]:
    return {g["equipment_id"]: [c["accident_type"]["code"] for c in g["candidates"]] for r in responses for g in r["groups"]}


# ---------------------------------------------------------------- 실행
def main():
    from eval_hitl import GOLDSET, eval_goldset
    from hitl_contract_v2 import validator
    cfg = load_cfg()
    ev = evidence_map()
    v = validator()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "responses").mkdir(exist_ok=True)
    v2idx = json.loads((ROOT.parent / "261115_RAG_지식베이스_DR" / "261116_RAG_기기위험요인인덱스_v2_DR.json").read_text(encoding="utf-8"))
    ne = {(x["equipment_id"] if isinstance(x, dict) else x) for x in v2idx["no_evidence"]}
    rk_official = json.loads((ROOT / "runs" / "hitl_recommend" / "ranked_codes.json").read_text(encoding="utf-8"))["ranked"]
    summary = {"generated_at": now_kst(), "config": CFG.name, "filter_version": cfg["filter_version"],
               "status": "시험용, 파이프라인 미연결, 팀 결정 전", "inputs": {}, "evidence_ids": len(ev), "methods": {}}
    detections, review = [], []
    for m, label in METHODS.items():
        p = CV2 / f"v2_{m}.json"
        raw = p.read_bytes()
        summary["inputs"][m] = {"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(raw).hexdigest()}
        resp = json.loads(raw.decode("utf-8"))
        cands = [c for r in resp for g in r["groups"] for c in g["candidates"]]
        ms = {"label": label, "candidates": len(cands), "scopes": {}}
        base_ranked = ranked_of(resp)
        base_eval = eval_goldset({m: base_ranked}, GOLDSET, [1, 3, 5], ne)
        ms["ranked_equals_official"] = all(base_ranked.get(e, []) == rk_official.get(m, {}).get(e, []) for e in base_ranked)
        for c in cands:
            allh = detect(cfg, c["rationale"], SCOPES["all"])
            for h in allh:
                detections.append({"method": m, "candidate_id": c["candidate_id"], "rationale": c["rationale"], **{k: h[k] for k in ("group_id", "basis", "match")}})
            if not allh and LOOSE.search(c["rationale"] or ""):
                review.append({"method": m, "candidate_id": c["candidate_id"], "rationale": c["rationale"], "loose_cue": LOOSE.search(c["rationale"]).group(0)})
        for sc, groups in SCOPES.items():
            so = {"detected_candidates": sum(bool(detect(cfg, c["rationale"], groups)) for c in cands)}
            for opt in OPTIONS:
                out, log = apply(cfg, resp, groups, opt, ev)
                errs = [e.message[:150] for r in out for e in v.iter_errors(r)]
                ev2 = eval_goldset({m: ranked_of(out)}, GOLDSET, [1, 3, 5], ne)
                so[opt] = {"changed_candidates": sum(x["before"] != x["after"] for x in log),
                           "schema_valid": f"{sum(not list(v.iter_errors(r)) for r in out)}/{len(out)}", "schema_errors": errs[:3],
                           "ranked_unchanged": ranked_of(out) == base_ranked,
                           "goldset_scores_unchanged": json.dumps(ev2, sort_keys=True) == json.dumps(base_eval, sort_keys=True),
                           "remaining_hits_after": sum(bool(detect(cfg, c["rationale"], groups)) for r in out for g in r["groups"] for c in g["candidates"]),
                           "examples": log[:5]}
                if opt != "a_flag":
                    (OUT / "responses" / f"v2_{m}__{opt}__{sc}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            ms["scopes"][sc] = so
        summary["methods"][m] = ms
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "detections.json").write_text(json.dumps(detections, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "review_missed_candidates.json").write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = all(o["schema_valid"].split("/")[0] == o["schema_valid"].split("/")[1] and o["ranked_unchanged"] and o["goldset_scores_unchanged"]
             for ms in summary["methods"].values() for so in ms["scopes"].values() for k, o in so.items() if k in OPTIONS)
    print(json.dumps({m: {"candidates": x["candidates"], "ranked_equals_official": x["ranked_equals_official"],
                          **{sc: {"detected": so["detected_candidates"], **{o: (so[o]["changed_candidates"], so[o]["schema_valid"], so[o]["goldset_scores_unchanged"], so[o]["remaining_hits_after"]) for o in OPTIONS}}
                             for sc, so in x["scopes"].items()}} for m, x in summary["methods"].items()}, ensure_ascii=False, indent=1))
    print("detections", len(detections), "loose-review", len(review), "ALL_OK" if ok else "CHECK_FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
