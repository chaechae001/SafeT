"""Human-in-the-Loop 추천형 S04 (hitl-recommend-0.1, 2026-11-16).

입력: 사용자가 확인한 기기 목록(equipment_id) + 선택 입력(현장 설명).
출력: 기기별 위험요인 후보(복수)와 각 후보의 예방대책 후보, 출처 ID. 신호·위험도·등급은 출력하지 않는다.
발생 가능성·중대성은 사용자가 고르고 위험도는 규칙으로 계산한다(척도 미확정).

방법(config/hitl_recommend_config.json의 methods):
- R_bm25   검색만(기기마스터 없이 BM25)
- R_index  검색만(기기마스터 = 기기→위험요인 인덱스 + BM25 보충)
- A_llm    LLM 단독(기기 표준명 + 위험 분류 코드 목록)
- B_rag    RAG: R_index 후보·근거 발췌를 주고 LLM이 정렬·설명(LLM이 고른 후보만)
- B_rag_fill  B_rag + LLM이 고르지 않은 R_index 후보(원래 순서)
대책 후보: 3차 라운드 C2(서버 규칙)와 C1(LLM 선택)을 S04Pipeline에서 그대로 가져다 쓴다.

모드: dump(프롬프트만 만들기) / replay(Cloud 응답 재생). 모델을 직접 부르지 않는다.
python src/hitl_recommend.py dump                       → cloud/prompts_hitl_v1.json
python src/hitl_recommend.py replay cloud/outputs/cloud_outputs_hitl_v1.json → runs/hitl_recommend/
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, S04Pipeline, clean_measure_text, now_kst  # noqa: E402

CFG_PATH = ROOT / "config" / "hitl_recommend_config.json"
OUT_DIR = ROOT / "runs" / "hitl_recommend"
SCHEMA = ROOT / "contract_hitl" / "hitl_recommend.response.schema.json"
METHODS = ("R_bm25", "R_index", "R_index_v2", "A_llm", "B_rag", "B_rag_fill")
INDEX_V2 = ROOT.parent / "261115_RAG_지식베이스_DR" / "261116_RAG_기기위험요인인덱스_v2_DR.json"

SYSTEM = ("너는 음식점 위험성평가를 돕는 추천 도구다. 최종 선택과 판단은 사용자가 한다. "
          "위험도·등급·점수는 쓰지 않는다. 안전 기준이나 법령을 지어내지 않는다. 출력은 JSON 객체 하나만 쓴다.")


class HitlRecommender:
    def __init__(self, cfg_path: Path = CFG_PATH):
        self.cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json")
        self.pipe.cfg["backend"]["llm"]["rank_keep_unscored"] = True   # A3 설정(점수 0 풀 행 유지)
        self.kb, self.em = self.pipe.kb, self.pipe.emap
        self.codes = self.em.code_names
        rc = self.cfg["retrieval"]
        if rc["exclude_case_rows"]:
            assert all(r["source_type"] != "case" for r in self.kb.rows.values()), "사례 행이 인덱스에 남아 있음"
        # RAG 세션 인덱스 v2(2026-11-16). 엄격 모드: 사례(CASE-*) 출처는 쓰지 않는다(정답셋 R 등급과 같은 기록).
        self.v2 = json.loads(INDEX_V2.read_text(encoding="utf-8")) if INDEX_V2.exists() else None
        self.v2_index = {e["equipment_id"]: e for e in self.v2["index"]} if self.v2 else {}
        self.v2_no_evidence = {(x["equipment_id"] if isinstance(x, dict) else x) for x in (self.v2 or {}).get("no_evidence", [])}

    # ------------------------------------------------------------ 검색
    def _eq_query(self, eid: str) -> str:
        e = self.em.equipment[eid]
        return " ".join([e["standard_name"]] + e.get("synonyms", []))

    def bm25_codes(self, eid: str) -> list[tuple[str, float, list[str]]]:
        """기기명으로 행·청크를 검색하고, 검색 문장에 든 위험 낱말로 코드별 점수를 더한다."""
        rc = self.cfg["retrieval"]
        q = self._eq_query(eid)
        score: dict[str, float] = defaultdict(float)
        ev: dict[str, list[str]] = defaultdict(list)
        hits = [(rid, s, self.kb.rows[rid]["source_text"]) for rid, s in self.kb.row_index.search(q, rc["bm25_rows_top"])]
        hits += [(cid, s, self.kb.chunks[cid]["text"]) for cid, s in self.kb.chunk_index.search(q, rc["bm25_chunks_top"])]
        for sid, s, text in hits:
            for c in self.em.classify(text):
                score[c] += s
                ev[c].append(sid)
        return sorted(((c, round(v, 3), ev[c]) for c, v in score.items()), key=lambda x: -x[1])

    def master_refs(self, eid: str, code: str) -> list[str]:
        out = []
        for h in self.em.equipment[eid]["related_hazards"]:
            if h["code"] == code:
                for r in h.get("refs", []):
                    loc = r.get("locator") or ""
                    if loc in self.kb.rows or loc in self.kb.chunks:
                        out.append(loc)
        return list(dict.fromkeys(out))

    def evidence_rows(self, eid: str, code: str, n: int) -> list[str]:
        kws = self.em.code_keywords[code]
        mapped = [r for r in self.em.rows_for([eid]) if any(k in self.kb.rows[r]["source_text"] for k in kws)]
        ranked = [r for r, _ in self.kb.row_index.search(self._eq_query(eid) + " " + self.codes[code], 20,
                                                          lambda r: r in set(mapped))] + mapped
        return list(dict.fromkeys(ranked))[:n]

    def retrieve(self, eid: str) -> dict[str, list[dict]]:
        bm = self.bm25_codes(eid)
        r_bm25 = [{"hazard_code": c, "score": s, "origin": "retrieval_bm25", "source_ids": ids[:5]} for c, s, ids in bm]
        hz = self.em.equipment[eid]["related_hazards"]
        bm_score = {c: s for c, s, _ in bm}
        tiers = [h for h in hz if h["evidence"] == "근거있음"] + [h for h in hz if h["evidence"] != "근거있음"]
        r_index = []
        for tier in ("근거있음", "제안"):
            grp = [h for h in tiers if (h["evidence"] == "근거있음") == (tier == "근거있음")]
            grp.sort(key=lambda h: -bm_score.get(h["code"], 0.0))   # 같은 근거 단계 안에서는 BM25 점수 순
            for h in grp:
                if h["code"] not in [x["hazard_code"] for x in r_index]:
                    r_index.append({"hazard_code": h["code"], "score": bm_score.get(h["code"], 0.0),
                                    "origin": f'index_master({h["evidence"]})', "master_summary": h["summary"],
                                    "source_ids": self.master_refs(eid, h["code"])})
        for c, s, ids in bm:
            if c not in [x["hazard_code"] for x in r_index]:
                r_index.append({"hazard_code": c, "score": s, "origin": "index_bm25_extra", "source_ids": ids[:5]})
        return {"R_bm25": r_bm25, "R_index": r_index, "R_index_v2": self.retrieve_v2(eid)}

    def retrieve_v2(self, eid: str) -> list[dict]:
        """인덱스 v2 검색(엄격). 근거 등급 A 우선, 같은 등급은 출처 수 순. CASE-* 출처를 빼고 남는 출처가 없으면 후보에서 뺀다."""
        e = self.v2_index.get(eid)
        if not e:
            return []
        out = []
        for h in e["hazards"]:
            src = [s for s in h["source_ids"] if not s.startswith("CASE-")]
            if not src:
                continue
            ms = [m for m in h["measures"] if m["relevance_rank"] <= 3 and any(not s.startswith("CASE-") for s in m["source_ids"])]
            ms.sort(key=lambda m: m["relevance_rank"])
            out.append({"hazard_code": h["hazard_code"], "origin": "index_v2", "source_ids": src,
                        "hazard_text": (h.get("hazard_texts") or [""])[0], "tier": min(h.get("tiers") or ["Z"]),
                        "n_src": len(src),
                        "v2_measures": [{"text": m["text"], "source_ids": [s for s in m["source_ids"] if not s.startswith("CASE-")],
                                         "relevance_rank": m["relevance_rank"]} for m in ms[:3]]})
        out.sort(key=lambda x: (x["tier"], -x["n_src"]))
        return out

    # ------------------------------------------------------------ 프롬프트
    def _code_list(self) -> str:
        return "\n".join(f"- {c}: {n}" for c, n in self.codes.items())

    def prompt_A(self, eid: str, site_note: str | None) -> list[dict]:
        e = self.em.equipment[eid]
        note = f"\n현장 설명(사용자 입력): {site_note}" if site_note else ""
        user = f"""기기: {e["standard_name"]}{note}

위험 분류 코드:
{self._code_list()}

할 일: 음식점에서 이 기기를 쓰거나 청소·관리할 때 생길 수 있는 위험요인 후보를 관련 높은 순으로 최대 {self.cfg["llm"]["max_candidates"]}개 쓴다.
규칙:
1. code는 위 코드 중 하나를 쓴다. 같은 code를 두 번 쓰지 않는다.
2. hazard는 무엇이 어떻게 위험한지 한국어 한 문장으로 쓴다.
3. reason은 이 기기에 해당하는 이유를 한국어 한 문장으로 쓴다.
4. 위험도·등급·점수는 쓰지 않는다.
출력은 아래 틀의 JSON 하나만 쓴다(후보 수만큼 원소를 늘린다):
{{"candidates":[{{"code":"","hazard":"","reason":""}}]}}"""
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]

    def pool_for_B(self, r_index: list[dict]) -> list[dict]:
        return r_index[: self.cfg["retrieval"]["pool_size_for_llm"]]

    def prompt_B(self, eid: str, pool: list[dict], site_note: str | None) -> list[dict]:
        e = self.em.equipment[eid]
        n_ev = self.cfg["retrieval"]["evidence_rows_per_code"]
        lines = []
        for p in pool:
            c = p["hazard_code"]
            ev = []
            if p.get("master_summary"):
                ev.append(p["master_summary"])
            for rid in self.evidence_rows(eid, c, n_ev):
                ev.append(clean_measure_text(self.kb.rows[rid]["source_text"], 70))
            if not ev:
                for sid in p.get("source_ids", [])[:n_ev]:
                    t = self.kb.rows[sid]["source_text"] if sid in self.kb.rows else self.kb.chunks[sid]["text"]
                    ev.append(clean_measure_text(t, 70))
            ev = [re.sub(r"\s+", " ", x).strip() for x in ev]
            lines.append(f'- {c}: {self.codes[c]} — 참고: {" / ".join(ev) if ev else "없음"}')
        note = f"\n현장 설명(사용자 입력): {site_note}" if site_note else ""
        user = f"""기기: {e["standard_name"]}{note}

위험요인 후보(코드: 이름 — 참고 자료 발췌):
{chr(10).join(lines)}

할 일: 위 후보를 이 기기와 관련 높은 순으로 정렬한다. 이 기기와 관련 없는 후보는 뺀다.
규칙:
1. 위 후보 코드만 쓴다. 같은 code를 두 번 쓰지 않는다.
2. reason은 참고 자료에 근거해 이 기기에 해당하는 이유를 한국어 한 문장으로 쓴다.
3. 위험도·등급·점수는 쓰지 않는다.
출력은 아래 틀의 JSON 하나만 쓴다(고른 후보 수만큼 원소를 늘린다):
{{"ranked":[{{"code":"","reason":""}}]}}"""
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]

    # ------------------------------------------------------------ 대책(C1·C2 재사용)
    def _d(self, eid: str, code: str, summary: str | None) -> dict:
        name = self.em.equipment[eid]["standard_name"]
        hz = summary or f"{name} {self.codes[code]}"
        return {"work": f"{name} 사용·관리", "hazard": hz, "accident_type": self.codes[code], "cause": hz,
                "description": hz, "unit_eq_ids": [eid], "unit_id": f"hitl:{eid}", "item_key": f"{eid}:{code}"}

    def _summary(self, eid: str, code: str) -> str | None:
        return next((h["summary"] for h in self.em.equipment[eid]["related_hazards"] if h["code"] == code), None)

    def c1_call(self, eid: str, code: str) -> dict:
        return self.pipe.c1_call(self._d(eid, code, self._summary(eid, code)))

    def measures(self, eid: str, code: str, c1_replies: dict | None) -> tuple[list[dict], str]:
        d = self._d(eid, code, self._summary(eid, code))
        if c1_replies is not None:
            call = self.pipe.c1_call(d)
            content = c1_replies.get(call["unit_id"])
            if content is not None:
                m = re.search(r"\{.*\}", content, re.S)
                try:
                    ids = json.loads(m.group(0)).get("recommended_row_ids") if m else None
                except (json.JSONDecodeError, AttributeError):
                    ids = None
                if isinstance(ids, list):
                    ids = list(dict.fromkeys(x.strip() for x in ids if isinstance(x, str) and x.strip()))
                    if len(ids) == 3 and all(x in call["candidates_c1"] for x in ids):
                        rec = self.pipe._measures_from_ids(ids)
                        if len(rec) == 3:
                            return rec, "c1"
                c1_replies.setdefault("_invalid", []).append(call["unit_id"])
        self.pipe.recommend_staged(d, "c2")
        return d["rec"], ("c2" if d["rec_status"] == "ok" else "c2_failed")

    # ------------------------------------------------------------ 응답 해석
    def parse_A(self, content: str | None) -> tuple[list[dict], dict]:
        st = {"parse_ok": False, "invalid_code": 0, "dup_code": 0, "empty": 0}
        m = re.search(r"\{.*\}", content or "", re.S)
        try:
            arr = json.loads(m.group(0)).get("candidates") if m else None
        except (json.JSONDecodeError, AttributeError):
            arr = None
        if not isinstance(arr, list):
            return [], st
        st["parse_ok"] = True
        out = []
        for x in arr:
            if not isinstance(x, dict):
                continue
            c = str(x.get("code", "")).strip()
            if c not in self.codes:
                st["invalid_code" if c else "empty"] += 1
                continue
            if c in [o["hazard_code"] for o in out]:
                st["dup_code"] += 1
                continue
            out.append({"hazard_code": c, "hazard_text": str(x.get("hazard", "")).strip(),
                        "reason": str(x.get("reason", "")).strip(), "origin": "llm_only", "source_ids": []})
        return out, st

    def parse_B(self, content: str | None, pool: list[dict]) -> tuple[list[dict], dict]:
        st = {"parse_ok": False, "outside_pool": 0, "dup_code": 0, "empty": 0}
        allowed = {p["hazard_code"]: p for p in pool}
        m = re.search(r"\{.*\}", content or "", re.S)
        try:
            arr = json.loads(m.group(0)).get("ranked") if m else None
        except (json.JSONDecodeError, AttributeError):
            arr = None
        if not isinstance(arr, list):
            return [], st
        st["parse_ok"] = True
        out = []
        for x in arr:
            if not isinstance(x, dict):
                continue
            c = str(x.get("code", "")).strip()
            if not c:
                st["empty"] += 1
                continue
            if c not in allowed:
                st["outside_pool"] += 1
                continue
            if c in [o["hazard_code"] for o in out]:
                st["dup_code"] += 1
                continue
            p = allowed[c]
            out.append({"hazard_code": c, "hazard_text": p.get("master_summary") or "", "reason": str(x.get("reason", "")).strip(),
                        "origin": "rag_llm_ranked", "source_ids": p.get("source_ids", [])})
        return out, st

    # ------------------------------------------------------------ 조립
    def response(self, req: dict, method: str, ranked: dict[str, list[dict]], c1_replies, model_version: str | None,
                 warnings: list[str]) -> dict:
        eqs = []
        for eid in req["equipment_ids"]:
            cands = []
            for i, c in enumerate(ranked.get(eid, [])):
                if "v2_measures" in c:
                    kw = self.pipe.cfg["measures"]["control_type_keywords"]
                    from s04_pipeline import control_type_of
                    rec = [{"measure_id": "rm-" + m["source_ids"][0], "text": clean_measure_text(m["text"]),
                            "control_type": control_type_of(m["text"], kw)} for m in c["v2_measures"]]
                    how = "index_v2"
                else:
                    rec, how = self.measures(eid, c["hazard_code"], c1_replies)
                text = c.get("hazard_text") or self._summary(eid, c["hazard_code"]) or ""
                cands.append({
                    "rank": i + 1, "hazard_code": c["hazard_code"], "hazard_name": self.codes[c["hazard_code"]],
                    "hazard_text": text, "reason": c.get("reason") or "", "origin": c["origin"],
                    "source_ids": [s for s in c.get("source_ids", []) if s in self.kb.rows or s in self.kb.chunks or c["origin"] == "index_v2"],
                    "measure_candidates": [{"row_id": r["measure_id"][3:], "text": r["text"], "control_type": r["control_type"]}
                                           for r in rec],
                    "measure_method": how,
                    "user_decision": {"selected": None, "likelihood": None, "severity": None},
                })
            e = self.em.equipment[eid]
            eqs.append({"equipment_id": eid, "standard_name": e["standard_name"], "candidates": cands})
        return {
            "request_id": req["request_id"], "method": method, "generated_at": now_kst(),
            "pipeline_version": self.cfg["version"], "model_version": model_version,
            "risk_scale_status": self.cfg["risk_scale_status"],
            "risk_level_rule": "사용자가 고른 발생 가능성·중대성으로 규칙 계산(척도 미확정). AI는 신호·위험도를 출력하지 않는다.",
            "equipment_master_version": self.em.version, "equipment": eqs, "warnings": warnings,
        }


# ---------------------------------------------------------------- 입력·호출 묶음
def eval_requests(rec: HitlRecommender) -> list[dict]:
    """평가용: 기기마다 요청 하나(현장 설명 없음). 데모: TC01 기기 묶음 + 현장 설명."""
    reqs = [{"request_id": f"hitl-eq-{eid}", "equipment_ids": [eid], "site_note": None} for eid in rec.em.equipment]
    reqs.append(json.loads((ROOT / "inputs" / "hitl" / "HT01_tc01.json").read_text(encoding="utf-8")))
    return reqs


def build_calls(rec: HitlRecommender, reqs: list[dict]) -> list[dict]:
    calls, seen = [], set()
    for req in reqs:
        for eid in req["equipment_ids"]:
            note = req.get("site_note")
            tag = "note" if note else "plain"
            pool = rec.pool_for_B(rec.retrieve(eid)["R_index"])
            for variant, msgs, key in (("A_llm", rec.prompt_A(eid, note), "candidates"),
                                        ("B_rag", rec.prompt_B(eid, pool, note), "ranked")):
                uid = f"{variant}:{eid}:{tag}"
                if uid in seen:
                    continue
                seen.add(uid)
                calls.append({"variant": variant, "request_id": req["request_id"], "unit_id": uid, "messages": msgs,
                              "expect_key": key})
    # C1: 기기마스터 인덱스의 (기기, 코드) 쌍. LLM 결과와 무관하게 미리 만든다.
    for eid in rec.em.equipment:
        for h in rec.em.equipment[eid]["related_hazards"]:
            c = rec.c1_call(eid, h["code"])
            if c["unit_id"] in seen:
                continue
            seen.add(c["unit_id"])
            calls.append({"variant": "C1", "request_id": f"hitl-eq-{eid}", "unit_id": c["unit_id"], "messages": c["messages"],
                          "expect_key": "recommended_row_ids"})
    return calls


def cmd_dump():
    rec = HitlRecommender()
    reqs = eval_requests(rec)
    calls = build_calls(rec, reqs)
    out = {"created_at": now_kst(), "pipeline_version": rec.cfg["version"],
           "prompt_versions": [rec.cfg["llm"]["prompt_version_A"], rec.cfg["llm"]["prompt_version_B"], "c1(3차 라운드)"],
           "calls": calls}
    p = ROOT / "cloud" / "prompts_hitl_v1.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(p.name, len(calls), dict(Counter(c["variant"] for c in calls)))


def cmd_run(cloud_path: str | None):
    """cloud_path가 없으면 검색 방법(R_*)만 만든다. 있으면 A·B도 재생한다."""
    rec = HitlRecommender()
    reqs = eval_requests(rec)
    replies, model_version, meta = {}, None, {}
    if cloud_path:
        d = json.loads(Path(cloud_path).read_text(encoding="utf-8"))
        prompts = {c["unit_id"]: c["messages"] for c in build_calls(rec, reqs)}
        for r in d["results"]:
            if prompts.get(r["unit_id"]) != r["messages"]:
                raise RuntimeError(f'재생 파일의 프롬프트가 현재 프롬프트와 다름: {r["unit_id"]}')
            att = r["attempts"][(r["accepted_attempt"] or 1) - 1]
            replies[r["unit_id"]] = att["content"]
            meta[r["unit_id"]] = {"accepted_attempt": r["accepted_attempt"], "seconds": att["seconds"],
                                  "output_tokens": att["output_tokens"], "hit_max": att["hit_max_new_tokens"]}
        model_version = f'{d["model_id"]}@{d["revision"][:12]}'
        missing = [u for u in prompts if u not in replies]
        if missing:
            raise RuntimeError(f"Cloud 응답 누락 {len(missing)}건: {missing[:3]}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    methods = METHODS if cloud_path else ("R_bm25", "R_index", "R_index_v2")
    ranked_all = {m: {} for m in methods}
    stats = {"A_llm": [], "B_rag": []}
    responses = {m: [] for m in methods}
    c1_replies = {k: v for k, v in replies.items() if k.startswith("c1:")} if cloud_path else None
    for req in reqs:
        tag = "note" if req.get("site_note") else "plain"
        per = {m: {} for m in methods}
        for eid in req["equipment_ids"]:
            r = rec.retrieve(eid)
            per["R_bm25"][eid], per["R_index"][eid], per["R_index_v2"][eid] = r["R_bm25"], r["R_index"], r["R_index_v2"]
            if cloud_path:
                a, sa = rec.parse_A(replies[f"A_llm:{eid}:{tag}"])
                pool = rec.pool_for_B(r["R_index"])
                b, sb = rec.parse_B(replies[f"B_rag:{eid}:{tag}"], pool)
                per["A_llm"][eid], per["B_rag"][eid] = a, b
                per["B_rag_fill"][eid] = b + [dict(p, origin="retrieval_unranked") for p in r["R_index"]
                                              if p["hazard_code"] not in {x["hazard_code"] for x in b}]
                stats["A_llm"].append(dict(sa, unit=f"A_llm:{eid}:{tag}", n=len(a), **meta[f"A_llm:{eid}:{tag}"]))
                stats["B_rag"].append(dict(sb, unit=f"B_rag:{eid}:{tag}", n=len(b), pool=len(pool), **meta[f"B_rag:{eid}:{tag}"]))
        for m in methods:
            warns = []
            if m in ("A_llm", "B_rag", "B_rag_fill"):
                warns.append(f"[Cloud 모델 출력 재생] {model_version} 응답을 로컬에서 후처리했습니다.")
            if m == "A_llm":
                warns.append("LLM 단독 후보는 출처 ID가 없습니다. 대책 후보는 서버 규칙·C1로 붙였습니다.")
            resp = rec.response(req, m, per[m], c1_replies if m != "R_bm25" else None, model_version, warns)
            responses[m].append(resp)
            if req["request_id"].startswith("hitl-eq-"):
                ranked_all[m].update({e["equipment_id"]: [c["hazard_code"] for c in e["candidates"]] for e in resp["equipment"]})
    for m in methods:
        (OUT_DIR / f"responses_{m}.json").write_text(json.dumps(responses[m], ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "ranked_codes.json").write_text(json.dumps({"generated_at": now_kst(), "model_version": model_version,
                                                           "ranked": ranked_all}, ensure_ascii=False, indent=1), encoding="utf-8")
    c1_inv = c1_replies.get("_invalid", []) if c1_replies else []
    summary = {"generated_at": now_kst(), "cloud_file": cloud_path, "model_version": model_version, "methods": list(methods),
               "llm_stats": stats, "c1_invalid_units": sorted(set(c1_inv))}
    (OUT_DIR / "run_stats.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", [f"responses_{m}.json" for m in methods])
    return responses


if __name__ == "__main__":
    if sys.argv[1] == "dump":
        cmd_dump()
    elif sys.argv[1] == "replay":
        cmd_run(sys.argv[2])
    elif sys.argv[1] == "retrieval":
        cmd_run(None)
