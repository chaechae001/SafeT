"""Human-in-the-Loop 추천 흐름을 LangGraph로 묶는다. 추천 LLM은 EXAONE-3.5-7.8B-Instruct-AWQ로 고정(사용자 결정 2026-11-17).

흐름(노드):
  propose_equipment → [사람] confirm_equipment → build_request → retrieve → rank_llm → assemble
  → rationale_filter → [사람] select_and_rate → risk_rule → END
- 사람 지점 2곳은 LangGraph interrupt로 멈추고, Command(resume=...)로 사람 입력을 받아 이어 간다.
- 단계마다 계약 v2.1 스키마(equipment_confirmed, hazard_candidates request/response, user_selection, risk_result)로 검증한다.
- LLM은 검색 후보 안에서 정렬·설명만 한다. 신호·위험도는 출력하지 않는다.
- 위험도는 팀 백엔드 정책 CATALOG-MVP-1.0으로 계산한다(팀 결정 2026-11-17, src/catalog_risk.py). 사용자는 카탈로그 시나리오와 현재·계획 조치를 고르고,
  피해 수준은 카탈로그가 정한다. 이전 3×3 규칙(src/risk_rule.py)은 기록용으로만 남긴다.
- LLM 백엔드: replay(Cloud에서 기록한 응답을 재생, 프롬프트 일치 검사) | vllm(Cloud GPU에서 직접 실행).

uv run -q --with langgraph --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/hitl_graph.py demo
  → runs/hitl_graph/ (합성 탐지·합성 사람 입력으로 끝까지 실행한 기록)
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hitl_exaone import (PROMPTS, build_candidates, parse, pool_for, prompt,  # noqa: E402
                         public_links)
from hitl_recommend import HitlRecommender  # noqa: E402
from s04_pipeline import ROOT, now_kst  # noqa: E402

CFG = ROOT / "config" / "hitl_graph_config.json"
V2 = ROOT.parent / "261115_AI출력계약_신호기준_DR" / "schemas_v2_1"   # 계약 v2.1(위험도: 백엔드 정책)
OUT = ROOT / "runs" / "hitl_graph"


# ---------------------------------------------------------------- 계약 검증
_VAL: dict[str, Any] = {}


def validate(schema_file: str, obj: dict) -> list[str]:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
    if schema_file not in _VAL:
        reg = Registry()
        for f in V2.glob("*.schema.json"):
            s = json.loads(f.read_text(encoding="utf-8"))
            reg = reg.with_resource(s["$id"], Resource.from_contents(s))
        sch = json.loads((V2 / schema_file).read_text(encoding="utf-8"))
        _VAL[schema_file] = Draft202012Validator(sch, registry=reg, format_checker=FormatChecker())
    return [f'{"/".join(map(str, e.path))}: {e.message[:160]}' for e in _VAL[schema_file].iter_errors(obj)]


# ---------------------------------------------------------------- LLM 백엔드
def schema_for(pool: list[dict]) -> dict:
    """guided JSON: 후보 코드는 const, 출처 ID는 그 후보의 enum. uniqueItems는 vLLM 0.10.1.1 구조화 출력이 지원하지 않아 넣지 않는다(중복은 assemble에서 제거)."""
    items = [{"type": "object", "additionalProperties": False, "required": ["code", "source_ids", "rationale"],
              "properties": {"code": {"type": "string", "const": p["hazard_code"]},
                             "source_ids": {"type": "array", "minItems": 1,
                                            "items": {"type": "string", "enum": p["source_ids"]}},
                             "rationale": {"type": "string"}}} for p in pool]
    return {"type": "object", "additionalProperties": False, "required": ["ranked"],
            "properties": {"ranked": {"type": "array", "minItems": 1, "maxItems": len(pool), "items": {"anyOf": items}}}}


class ReplayBackend:
    """Cloud에서 실행한 EXAONE 3.5 응답을 재생한다. 같은 프롬프트일 때만 쓴다(불일치면 오류)."""

    def __init__(self, cfg: dict):
        raw = json.loads((ROOT / cfg["llm"]["replay_file"]).read_text(encoding="utf-8"))
        self.by_unit = {r["unit_id"]: r for r in raw["results"]}
        self.model_version = f'{raw["model"]}@{raw["revision"][:8]}(replay of {raw["started_at"]})'

    def __call__(self, eid: str, messages: list[dict], pool: list[dict]) -> dict:
        r = self.by_unit.get(f"E:{eid}")
        if r is None:
            raise RuntimeError(f"재생 응답 없음: {eid}")
        if r["messages"] != messages:
            raise RuntimeError(f"프롬프트 불일치(재생 불가): {eid}")
        att = r["attempts"][(r["accepted_attempt"] or len(r["attempts"])) - 1]
        return {"content": att["content"], "attempts": len(r["attempts"]), "seconds": att["seconds"], "mode": "replay"}


class VllmBackend:
    """Cloud GPU에서 EXAONE 3.5 AWQ를 vLLM으로 실행한다(guided JSON enum, 재시도 최대 max_retries)."""

    def __init__(self, cfg: dict):
        # STT(ctranslate2)가 같은 프로세스에서 CUDA를 먼저 초기화하면 fork한 EngineCore가 GPU를 못 연다(2026-11-17 Cloud 확인) → spawn 사용
        os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
        from huggingface_hub import snapshot_download
        from vllm import LLM
        L = cfg["llm"]
        self.L = L
        self.llm = LLM(model=snapshot_download(L["model"], revision=L["revision"]), **L["vllm"])
        self.model_version = f'{L["model"]}@{L["revision"][:8]}'
        import atexit
        atexit.register(self.close)   # 외부 스크립트에서 import해 써도 종료 시 엔진을 내린다

    def close(self):
        """vLLM 엔진 하위 프로세스(EngineCore)를 내리고 GPU 메모리를 돌려준다. 여러 번 불러도 된다."""
        llm = getattr(self, "llm", None)
        if llm is None:
            return
        self.llm = None
        try:
            core = getattr(getattr(llm, "llm_engine", None), "engine_core", None)
            if core is not None and hasattr(core, "shutdown"):
                core.shutdown()
        except Exception as e:  # 종료 실패는 기록만 하고 계속 정리한다
            print("vLLM engine_core.shutdown 실패:", e, file=sys.stderr)
        del llm
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def __call__(self, eid: str, messages: list[dict], pool: list[dict]) -> dict:
        from vllm import SamplingParams
        from vllm.sampling_params import GuidedDecodingParams
        gd = GuidedDecodingParams(json=schema_for(pool))
        t0, content = time.time(), None
        for a in range(self.L["max_retries"] + 1):
            s = self.L["sampling"]["first" if a == 0 else "retry"]
            sp = SamplingParams(temperature=s["temperature"], max_tokens=s["max_tokens"], seed=a, guided_decoding=gd)
            content = self.llm.chat(messages, sp, use_tqdm=False)[0].outputs[0].text
            if parse(content) is not None:
                break
        return {"content": content, "attempts": a + 1, "seconds": round(time.time() - t0, 3), "mode": "vllm"}


# ---------------------------------------------------------------- 상태
def _ed1(a: str, b: str) -> bool:
    """편집 거리 1 이하."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = j = d = 0
    while i < len(a) and j < len(b):
        if a[i] != b[j]:
            d += 1
            j += 1
            if d > 1:
                return False
        else:
            i += 1
            j += 1
    return True


def match_equipment(names, text: str, aliases: dict, fuzzy_min_len: int = 3) -> list[dict]:
    """텍스트에서 기기 후보를 찾는다. 반환: [{equipment_id, match: exact|alias|fuzzy, term}].
    - exact: 표준명·동의어(공백 무시). 표준명의 '·'·괄호를 나눈 조각도 이름으로 쓴다(2글자 이상).
    - alias: 설정의 추가 별칭(작성자 초안, 팀 확인 전).
    - fuzzy: 3글자 이상 이름과 한 글자 차이(음성 인식 오류 대비). 사용자가 확인 단계에서 거른다."""
    import re
    t = re.sub(r"\s+", "", text or "")
    cand = []
    for n, eid in names:
        n0 = re.sub(r"\s+", "", n)
        cand.append((n0, eid, "exact"))
        for part in re.split(r"[·()（）/]", n0):
            if len(part) >= 2 and part != n0:
                cand.append((part, eid, "exact"))
    for a, eid in (aliases or {}).items():
        cand.append((re.sub(r"\s+", "", a), eid, "alias"))
    cand.sort(key=lambda x: -len(x[0]))
    found, taken = {}, []
    # 2글자 이하 이름(예: 가위, 칼)은 공백을 지우면 낱말 경계를 넘어 잘못 맞는다('다가 위험' → '가위'). 원문 띄어쓰기 기준으로 따로 찾는다.
    raw = re.sub(r"\s+", " ", text or "")
    for n, eid, kind in cand:
        if len(n) <= 2 and re.search(r"(^|\s)" + re.escape(n), raw):
            found.setdefault(eid, {"equipment_id": eid, "match": kind, "term": n})
    for n, eid, kind in cand:
        if len(n) <= 2:
            continue
        for mt in re.finditer(re.escape(n), t):
            sp = (mt.start(), mt.end())
            if any(a <= sp[0] and sp[1] <= b for a, b in taken):
                continue
            taken.append(sp)
            found.setdefault(eid, {"equipment_id": eid, "match": kind, "term": n})
    for n, eid, kind in cand:
        if eid in found or kind != "exact" or len(n) < fuzzy_min_len:
            continue
        L = len(n)
        for k in (L - 1, L, L + 1):
            hit = next((t[i:i + k] for i in range(0, max(0, len(t) - k + 1))
                        if not any(a < i + k and i < b for a, b in taken) and _ed1(t[i:i + k], n)), None)
            if hit:
                found[eid] = {"equipment_id": eid, "match": "fuzzy", "term": n, "heard": hit}
                break
    return list(found.values())


class SttReplayBackend:
    """Cloud에서 기록한 STT 결과를 재생한다(파일 이름 기준)."""

    def __init__(self, cfg: dict):
        raw = json.loads((ROOT / cfg["stt"]["replay_file"]).read_text(encoding="utf-8"))
        self.by_file = {r["file"]: r for r in raw["results"]}
        self.model_version = f'{cfg["stt"]["model"]}@{cfg["stt"]["revision"][:8]}(replay)'

    def __call__(self, audio_path: str) -> dict:
        r = self.by_file.get(Path(audio_path).name)
        if r is None:
            raise RuntimeError(f"재생 STT 결과 없음: {audio_path}")
        return {"text": r["text"], "seconds": r["seconds"], "mode": "replay"}


class SttWhisperBackend:
    """faster-whisper를 같은 프로세스에 상주시킨다(평시 LLM+STT 동시 적재). 16 kHz mono wav를 직접 읽는다."""

    def __init__(self, cfg: dict):
        from faster_whisper import WhisperModel
        from huggingface_hub import snapshot_download
        c = cfg["stt"]
        self.c = c
        self.m = WhisperModel(snapshot_download(c["model"], revision=c["revision"]), device=c["device"], compute_type=c["compute_type"])
        self.model_version = f'{c["model"]}@{c["revision"][:8]}'

    def __call__(self, audio_path: str) -> dict:
        import wave
        import numpy as np
        w = wave.open(audio_path)
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
        w.close()
        t0 = time.time()
        segs, _ = self.m.transcribe(a, language=self.c["language"], beam_size=self.c["beam_size"], **self.c.get("transcribe_options", {}))
        return {"text": "".join(x.text for x in segs).strip(), "seconds": round(time.time() - t0, 3), "mode": "faster_whisper"}

    def close(self):
        self.m = None


class LocalData:
    """로컬 지식베이스·기기마스터에서 바로 읽는다."""

    def __init__(self):
        self.rec = HitlRecommender()
        self.links = public_links()
        self.codes = self.rec.codes
        self.kw = self.rec.pipe.cfg["measures"]["control_type_keywords"]

    def name(self, eid):
        return self.rec.em.equipment[eid]["standard_name"]

    def known(self, eid):
        return eid in self.rec.em.equipment

    def pool(self, eid):
        return pool_for(self.rec, self.links, eid)

    def messages(self, eid, pool):
        return prompt(self.rec, eid, pool)

    def v2(self, eid):
        return {p["hazard_code"]: p for p in self.rec.retrieve_v2(eid)}

    def match(self, text):
        return self.rec.em.match(text)

    def names(self):
        return [(n, eid) for eid, e in self.rec.em.equipment.items() for n in [e["standard_name"]] + e.get("synonyms", []) if n]


class BundleData:
    """미리 만든 묶음 파일(공개 근거·인덱스 v2 엄격 후보만)에서 읽는다. Cloud 실행용."""

    def __init__(self, path):
        b = json.loads(Path(path).read_text(encoding="utf-8"))
        self.meta, self.eq, self.codes, self.kw = b["meta"], b["equipment"], b["codes"], b["control_type_keywords"]

    def name(self, eid):
        return self.eq[eid]["standard_name"]

    def known(self, eid):
        return eid in self.eq

    def pool(self, eid):
        return self.eq[eid]["pool"]

    def messages(self, eid, pool):
        return self.eq[eid]["messages"]

    def v2(self, eid):
        return {p["hazard_code"]: p for p in self.eq[eid]["v2"]}

    def match(self, text):
        """기기 표준명·동의어 포함 검사(긴 이름 우선). 묶음에 synonyms가 없으면 표준명만 쓴다."""
        t, found = (text or "").replace(" ", ""), []
        names = sorted(((n.replace(" ", ""), eid) for eid, e in self.eq.items() for n in [e["standard_name"]] + e.get("synonyms", []) if n),
                       key=lambda x: -len(x[0]))
        for n, eid in names:
            if n in t and eid not in found:
                found.append(eid)
        return found

    def names(self):
        return [(n, eid) for eid, e in self.eq.items() for n in [e["standard_name"]] + e.get("synonyms", []) if n]


def export_bundle(path: Path) -> dict:
    """Cloud에 올릴 묶음: 기기 표준명, 공개 근거 후보, 프롬프트, 인덱스 v2 엄격 후보(대책 포함). 사례(CASE)·회사 원본·정답셋은 넣지 않는다."""
    d = LocalData()
    eq = {}
    for eid in d.rec.em.equipment:
        pool = d.pool(eid)
        eq[eid] = {"standard_name": d.name(eid), "synonyms": d.rec.em.equipment[eid].get("synonyms", []), "pool": pool, "messages": d.messages(eid, pool) if pool else None,
                   "v2": [{k: p[k] for k in ("hazard_code", "hazard_text", "v2_measures")} for p in d.rec.retrieve_v2(eid)]}
    b = {"meta": {"created_at": now_kst(), "kind": "hitl_graph bundle v1", "contents": "기기 표준명·공개 근거 문장·출처 ID·인덱스 v2 엄격 후보·대책 문장"},
         "codes": d.codes, "control_type_keywords": d.kw, "equipment": eq}
    txt = json.dumps(b, ensure_ascii=False, indent=1)
    assert "CASE-" not in txt and "현장 설명" not in txt, "묶음에 사례·현장 설명이 들어감"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(txt, encoding="utf-8")
    return {"equipment": len(eq), "with_pool": sum(bool(v["pool"]) for v in eq.values()), "bytes": len(txt.encode())}


class State(TypedDict, total=False):
    assessment_id: str
    user_input: dict           # {"type": "photo"|"voice"|"text", "audio_path"?: str, "text"?: str}. 사진이면 detection을 함께 넣는다
    transcript: dict           # 음성 → STT 결과(사용자 확인 전 원문)
    input_text: str            # 텍스트 입력 또는 사용자가 확인한 STT 결과
    detection: dict            # 기기 탐지 결과(SAM 3 등). {"detection_request_id", "status", "items":[{detection_id, equipment_id, confidence}]}
    proposed: list[dict]       # 사람에게 보여 줄 기기 후보
    detection_summary: dict    # 탐지 응답 → ai_found 변환 요약(제외 사유별 수, 임계값, 미구현 규칙)
    equipment_confirmed: dict  # 계약 equipment_confirmed.v2
    request: dict              # 계약 hazard_candidates.v2.request
    pools: dict                # 기기별 검색 후보(인덱스 v2 + 공개 근거)
    llm: dict                  # 기기별 LLM 원출력·시도 수·시간
    response: dict             # 계약 hazard_candidates.v2.response
    filter_log: list[dict]
    user_selection: dict       # 계약 user_selection.v2_1
    risk_result: dict          # 계약 risk_result.v2_1
    checks: dict               # 단계별 스키마 검사 결과
    trace: list[str]


class HitlGraph:
    def __init__(self, cfg_path: Path = CFG, backend: str | None = None, bundle: str | None = None):
        self.cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.data = BundleData(bundle) if bundle else LocalData()
        self.backend_name = backend or self.cfg["llm"]["backend"]
        self._backend = None
        self.stt_backend_name = self.cfg.get("stt", {}).get("backend", "replay")
        self._stt = None
        import rationale_filter as rf
        self.rf = rf
        self.rf_cfg = rf.load_cfg()
        from catalog_risk import CatalogRisk
        self.risk = CatalogRisk()

    def close(self):
        """백엔드 자원 정리. vllm 백엔드를 쓴 뒤에는 반드시 부른다(외부 스크립트 포함)."""
        if self._backend is not None and hasattr(self._backend, "close"):
            self._backend.close()
        if self._stt is not None and hasattr(self._stt, "close"):
            self._stt.close()

    @property
    def stt(self):
        if self._stt is None:
            self._stt = (SttReplayBackend if self.stt_backend_name == "replay" else SttWhisperBackend)(self.cfg)
        return self._stt

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def backend(self):
        if self._backend is None:
            self._backend = (ReplayBackend if self.backend_name == "replay" else VllmBackend)(self.cfg)
        return self._backend

    # ------------------------------------------------ 노드
    def intake(self, s: State) -> dict:
        ui = s.get("user_input") or {"type": "photo"}
        if ui["type"] not in self.cfg.get("input_types", ["photo", "voice", "text"]):
            raise ValueError(f"지원하지 않는 입력: {ui['type']}")
        return {"user_input": ui, "trace": s.get("trace", []) + [f"intake: {ui['type']}"]}

    def transcribe(self, s: State) -> dict:
        from langgraph.types import interrupt
        r = self.stt(s["user_input"]["audio_path"])
        ans = interrupt({"step": "confirm_transcript", "message": "음성 인식 결과를 확인·수정하세요.", "text": r["text"]})
        text = (ans or {}).get("text") or r["text"]
        return {"transcript": {**r, "model_version": self.stt.model_version, "edited": text != r["text"]}, "input_text": text,
                "trace": s["trace"] + [f"transcribe({r['mode']}): {r['seconds']}s, edited={text != r['text']}"]}

    def text_to_equipment(self, s: State) -> dict:
        text = s.get("input_text") or s["user_input"].get("text", "")
        tm = self.cfg.get("text_match", {})
        hits = [h for h in match_equipment(self.data.names(), text, tm.get("aliases", {}), tm.get("fuzzy_min_len", 3)) if self.data.known(h["equipment_id"])]
        prop = [{"equipment_id": h["equipment_id"], "display_name": self.data.name(h["equipment_id"]), "origin": "user_added",
                 "detection_refs": [], "match": h["match"], "term": h["term"]} for h in hits]
        det = {"detection_request_id": None, "status": "no_photo", "items": []}
        kinds = {k: sum(h["match"] == k for h in hits) for k in ("exact", "alias", "fuzzy")}
        return {"input_text": text, "proposed": prop, "detection": det,
                "trace": s["trace"] + [f"text_to_equipment: {len(prop)} {kinds}"]}

    def propose_equipment(self, s: State) -> dict:
        det = s["detection"]
        if "response" in det:   # 실제 탐지 응답(SAM 3 등) → 규칙 R1~R8로 ai_found 생성
            from detection_adapter import load_class_map, to_ai_found
            dc = self.cfg["detection"]
            cm = load_class_map(ROOT.parent / dc["class_map"])
            known = {e for e in self.data.eq} if isinstance(self.data, BundleData) else set(self.data.rec.em.equipment)
            r = to_ai_found(det["response"], cm, known, {"master_version": self.cfg["master_version"],
                                                          "class_map_version": dc["expected_class_map_version"]},
                            threshold=det.get("threshold", dc["threshold"]["default"]), use_partial=dc["use_partial"],
                            registered=det.get("registered"), photo_ids=set(det["photo_ids"]) if det.get("photo_ids") else None)
            prop = [{"equipment_id": x["equipment_id"], "display_name": self.data.name(x["equipment_id"]), "origin": "detected",
                     "confidence": round(x["confidence"], 4), "detection_refs": x["detection_refs"]} for x in r["ai_found"]]
            summary = {k: r.get(k) for k in ("usable", "reason", "photos_used", "excluded", "threshold", "notes", "detector")}
            return {"proposed": prop, "detection_summary": summary,
                    "trace": s.get("trace", []) + [f"propose_equipment(detector): {len(prop)} ai_found, excluded={r['excluded']}"]}
        seen, prop = set(), []
        for d in det.get("items", []):
            eid = d["equipment_id"]
            if eid in seen or not self.data.known(eid):
                continue
            seen.add(eid)
            prop.append({"equipment_id": eid, "display_name": self.data.name(eid), "origin": "detected",
                         "detection_refs": [x["detection_id"] for x in det["items"] if x["equipment_id"] == eid]})
        return {"proposed": prop, "trace": s.get("trace", []) + [f"propose_equipment: {len(prop)}"]}

    def confirm_equipment(self, s: State) -> dict:
        from langgraph.types import interrupt
        ans = interrupt({"step": "confirm_equipment", "message": "탐지된 기기를 확인하세요(유지·수정·삭제·추가).",
                         "proposed": s["proposed"]})
        eq = []
        acts = {a["equipment_id"]: a for a in ans.get("actions", [])}
        for p in s["proposed"]:
            a = acts.get(p["equipment_id"], {"action": "kept"})
            origin = p.get("origin", "detected")
            act = "added" if (origin == "user_added" and a["action"] == "kept") else a["action"]
            row = {"equipment_id": a.get("new_equipment_id", p["equipment_id"]), "origin": origin,
                   "user_action": act, "detection_refs": p["detection_refs"]}
            if a["action"] == "relabeled":
                row["original_equipment_id"] = p["equipment_id"]
            row["display_name"] = self.data.name(row["equipment_id"])
            eq.append(row)
        for eid in ans.get("added", []):
            eq.append({"equipment_id": eid, "display_name": self.data.name(eid), "origin": "user_added",
                       "user_action": "added", "detection_refs": []})
        dr = s["detection"].get("response") or s["detection"]
        ec = {"assessment_id": s["assessment_id"], "detection_request_id": dr.get("detection_request_id") or dr.get("request_id"),
              "detection_status": dr.get("status", "ok"), "master_version": self.cfg["master_version"],
              "confirmed_by": "user", "confirmed_at": ans.get("confirmed_at") or now_kst(), "equipment": eq}
        return {"equipment_confirmed": ec, "checks": {**s.get("checks", {}), "equipment_confirmed.v2_1": validate("equipment_confirmed.v2_1.schema.json", ec)},
                "trace": s["trace"] + [f"confirm_equipment: {len(eq)} rows"]}

    def build_request(self, s: State) -> dict:
        eq = [{"equipment_id": e["equipment_id"], "display_name": e["display_name"]}
              for e in s["equipment_confirmed"]["equipment"] if e["user_action"] != "removed"]
        req = {"request_id": str(uuid.uuid4()), "assessment_id": s["assessment_id"], "industry": self.cfg["industry"],
               "kb_version": self.cfg["kb_version"], "equipment": eq}
        return {"request": req, "checks": {**s["checks"], "hazard_candidates.v2_1.request": validate("hazard_candidates.v2_1.request.schema.json", req)},
                "trace": s["trace"] + [f"build_request: {len(eq)} equipment"]}

    def retrieve(self, s: State) -> dict:
        pools = {}
        for e in s["request"]["equipment"]:
            pool = self.data.pool(e["equipment_id"])
            pools[e["equipment_id"]] = {"pool": pool, "messages": self.data.messages(e["equipment_id"], pool) if pool else None}
        n = sum(bool(v["pool"]) for v in pools.values())
        return {"pools": pools, "trace": s["trace"] + [f"retrieve: {n}/{len(pools)} equipment with public evidence"]}

    def rank_llm(self, s: State) -> dict:
        out = {}
        for eid, v in s["pools"].items():
            if not v["pool"]:
                out[eid] = None
                continue
            body = v["messages"][1]["content"]
            assert "CASE-" not in body and "현장 설명" not in body, eid   # 사례·현장 설명은 모델에 넣지 않는다
            pool = [{"hazard_code": p["hazard_code"], "source_ids": [e["source_id"] for e in p["evidence"]]} for p in v["pool"]]
            out[eid] = self.backend(eid, v["messages"], pool)
        n = sum(x is not None for x in out.values())
        return {"llm": out, "trace": s["trace"] + [f"rank_llm({self.backend_name}): {n} calls"]}

    def assemble(self, s: State) -> dict:
        kw = self.data.kw
        st = {k: 0 for k in ("outside_pool_codes", "dup_codes", "invalid_source_ids", "dropped_no_valid_source", "judgement_words")}
        st["parse_fail"] = 0
        groups = []
        for e in s["request"]["equipment"]:
            eid = e["equipment_id"]
            v, r, cands = s["pools"][eid], s["llm"].get(eid), []
            if r is not None:
                d = parse(r["content"])
                if d is None:
                    st["parse_fail"] += 1
                else:
                    pool = [{"hazard_code": p["hazard_code"], "source_ids": [x["source_id"] for x in p["evidence"]]} for p in v["pool"]]
                    cands = build_candidates(self.data, eid, pool, self.data.v2(eid), d, kw, st)
                    for c in cands:   # v2.1: 같은 사고 경로의 카탈로그 시나리오 후보(백엔드 키워드 규칙). 확정은 사용자
                        c["catalog_scenario_ids"] = self.risk.match(e["display_name"], c["hazard"])
            groups.append({"equipment_id": eid, "display_name": e["display_name"],
                           "group_status": "ok" if cands else "no_source_found", "candidates": cands})
        status = "ok" if all(g["candidates"] for g in groups) else ("partial" if any(g["candidates"] for g in groups) else "failed")
        resp = {"request_id": s["request"]["request_id"], "call": "hazard_candidates_v2", "status": status,
                "model_version": getattr(self.backend, "model_version", self.cfg["llm"]["model"]),
                "kb_version": self.cfg["kb_version"], "generated_at": now_kst(), "groups": groups}
        return {"response": resp, "checks": {**s["checks"], "hazard_candidates.v2_1.response": validate("hazard_candidates.v2_1.response.schema.json", resp),
                                              "postprocess": st},
                "trace": s["trace"] + [f"assemble: status={status}, candidates={sum(len(g['candidates']) for g in groups)}"]}

    def rationale_filter(self, s: State) -> dict:
        fc = self.cfg["rationale_filter"]
        res, log = self.rf.apply(self.rf_cfg, [s["response"]], tuple(fc["groups"]), fc["option"], {})
        resp = res[0]
        return {"response": resp, "filter_log": log,
                "checks": {**s["checks"], "hazard_candidates.v2_1.response(after_filter)": validate("hazard_candidates.v2_1.response.schema.json", resp)},
                "trace": s["trace"] + [f"rationale_filter({fc['option']}): {len(log)} flagged"]}

    def select_and_rate(self, s: State) -> dict:
        """사람: 후보를 고르고, 카탈로그 시나리오와 현재·계획 조치를 고른다. 피해 수준은 카탈로그가 정한다(사용자·AI 입력 아님)."""
        from langgraph.types import interrupt
        cands = [(g, c) for g in s["response"]["groups"] for c in g["candidates"]]
        sids = sorted({sid for _, c in cands for sid in c.get("catalog_scenario_ids", [])})
        ans = interrupt({"step": "select_and_rate",
                         "message": "후보를 고르고, 맞는 위험 상황(카탈로그)과 현재 시행 중인 조치를 고르세요. 위험도는 정해진 기준으로 자동 계산됩니다(AI가 정하지 않습니다).",
                         "policy_version": self.risk.policy,
                         "scenarios": {sid: {"title": self.risk.scenarios[sid]["title"], "severity": self.risk.scenarios[sid]["severity"],
                                             "controls": self.risk.controls(sid)} for sid in sids},
                         "candidates": [{"candidate_id": c["candidate_id"], "hazard": c["hazard"], "accident_type": c["accident_type"],
                                         "rationale": c["rationale"], "measures": [m["measure_id"] for m in c["measure_candidates"]],
                                         "catalog_scenario_ids": c.get("catalog_scenario_ids", [])} for _, c in cands],
                         "flagged": [x["candidate_id"] for x in s.get("filter_log", [])]})
        cmap = {c["candidate_id"]: (g["equipment_id"], c) for g, c in cands}
        sels = []
        for i, a in enumerate(ans["selections"], 1):
            eid, c = cmap[a["candidate_id"]]
            ms = {m["measure_id"]: m for m in c["measure_candidates"]}
            sid = a.get("catalog_scenario_id")
            if sid is not None and sid not in self.risk.scenarios:
                raise ValueError(f"카탈로그에 없는 시나리오: {sid}")
            known = {x["id"] for x in self.risk.controls(sid)} if sid else set()
            cur, plan = a.get("current_control_ids", []), a.get("plan_control_ids", [])
            if (set(cur) | set(plan)) - known:
                raise ValueError(f"시나리오 {sid}에 없는 조치 ID: {sorted((set(cur) | set(plan)) - known)}")
            sels.append({"selection_id": f"sel-{i}", "equipment_id": eid,
                         "origin": "ai_candidate", "candidate_id": c["candidate_id"], "hazard": c["hazard"], "hazard_edited": False,
                         "accident_type": c["accident_type"], "source_refs": c["source_refs"],
                         "catalog_scenario_id": sid, "current_control_ids": cur,
                         "no_current_controls": bool(a.get("no_current_controls", False)), "plan_control_ids": plan,
                         "custom_current_measures": a.get("custom_current_measures", []),
                         "selected_measures": [{"measure_id": mid, "text": ms[mid]["text"], "source": "ai_candidate"} for mid in a.get("measure_ids", [])],
                         "owner_name": None, "due_date": None, "decided_by": "user", "decided_at": ans.get("decided_at") or now_kst()})
        us = {"assessment_id": s["assessment_id"], "policy_version": self.risk.policy,
              "candidates_request_id": s["request"]["request_id"], "selections": sels}
        return {"user_selection": us, "checks": {**s["checks"], "user_selection.v2_1": validate("user_selection.v2_1.schema.json", us)},
                "trace": s["trace"] + [f"select_and_rate: {len(sels)} selections"]}

    def risk_rule(self, s: State) -> dict:
        """백엔드 정책(CATALOG-MVP-1.0)으로 현재·예상 위험도를 계산한다. 노드 이름은 이전 그래프와 맞추려고 유지."""
        rr = self.risk.compute(s["assessment_id"], s["user_selection"]["selections"], now_kst())
        st: dict[str, int] = {}
        for r in rr["results"]:
            st[r["status"]] = st.get(r["status"], 0) + 1
        return {"risk_result": rr, "checks": {**s["checks"], "risk_result.v2_1": validate("risk_result.v2_1.schema.json", rr)},
                "trace": s["trace"] + [f"risk_rule({rr['policy_version']}): {st}"]}

    # ------------------------------------------------ 그래프
    def build(self, checkpointer=None):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        g = StateGraph(State)
        for n in ("propose_equipment", "confirm_equipment", "build_request", "retrieve", "rank_llm", "assemble",
                  "rationale_filter", "select_and_rate", "risk_rule"):
            g.add_node(n, getattr(self, n))
        for n in ("intake", "transcribe", "text_to_equipment"):
            g.add_node(n, getattr(self, n))
        g.add_edge(START, "intake")
        # 입력 분기: 사진 → 탐지 결과로 기기 후보 / 음성 → STT(사용자 확인) → 텍스트 / 텍스트 → 기기 이름 매칭
        g.add_conditional_edges("intake", lambda s: s["user_input"]["type"],
                                {"photo": "propose_equipment", "voice": "transcribe", "text": "text_to_equipment"})
        g.add_edge("transcribe", "text_to_equipment")
        g.add_edge("text_to_equipment", "confirm_equipment")
        g.add_edge("propose_equipment", "confirm_equipment")
        g.add_edge("confirm_equipment", "build_request")
        g.add_edge("build_request", "retrieve")
        g.add_edge("retrieve", "rank_llm")
        g.add_edge("rank_llm", "assemble")
        # 계약 위반이면 사람 단계로 넘기지 않고 멈춘다
        g.add_conditional_edges("assemble", lambda s: "stop" if s["checks"]["hazard_candidates.v2_1.response"] else "ok",
                                {"ok": "rationale_filter", "stop": END})
        g.add_edge("rationale_filter", "select_and_rate")
        g.add_edge("select_and_rate", "risk_rule")
        g.add_edge("risk_rule", END)
        return g.compile(checkpointer=checkpointer or InMemorySaver())

def synthetic_answer(shown: dict, cand: dict, cur_n: int = 0, plan_rest: bool = False, none: bool = False, measures: int = 0) -> dict:
    """시험용 합성 사람 입력. 첫 번째 연결 시나리오를 고르고, 핵심 조치 앞 cur_n개를 현재 조치로, 나머지를 계획으로 둔다.
    연결 시나리오가 없으면 카탈로그 밖 위험(판단 필요)으로 둔다. 실제 평가 판단이 아니다."""
    sids = cand.get("catalog_scenario_ids", [])
    a = {"candidate_id": cand["candidate_id"], "measure_ids": cand["measures"][:measures]}
    if not sids:
        return {**a, "catalog_scenario_id": None, "current_control_ids": [], "no_current_controls": True, "plan_control_ids": []}
    ctl = shown["scenarios"][sids[0]]["controls"]
    cur = [] if none else [c["id"] for c in ctl if c["critical"]][:cur_n]
    plan = [c["id"] for c in ctl if c["id"] not in cur] if plan_rest else []
    return {**a, "catalog_scenario_id": sids[0], "current_control_ids": cur, "no_current_controls": none, "plan_control_ids": plan}



# ---------------------------------------------------------------- 시연(합성 입력)
def demo(backend: str | None = None, bundle: str | None = None, tag: str = ""):
    """합성 탐지·합성 사람 입력으로 끝까지 실행한다. 사람 입력값은 시험용이며 실제 평가 판단이 아니다."""
    from langgraph.types import Command
    t0 = time.time()
    hg = HitlGraph(backend=backend, bundle=bundle)
    app = hg.build()
    cfg = {"configurable": {"thread_id": "demo-HT01"}}
    det = {"detection_request_id": "det-SYNTH-0001", "status": "ok", "synthetic": True,
           "items": [{"detection_id": "photo-1#d1", "equipment_id": "EQ_FRYER", "confidence": None},
                     {"detection_id": "photo-1#d2", "equipment_id": "EQ_KNIFE_BOARD", "confidence": None},
                     {"detection_id": "photo-2#d1", "equipment_id": "EQ_REFRIGERATOR", "confidence": None},
                     {"detection_id": "photo-2#d2", "equipment_id": "EQ_WALKIN_COOLER", "confidence": None}]}
    log = []
    r = app.invoke({"assessment_id": "A-SYNTH-HT01", "detection": det, "trace": [], "checks": {}}, cfg)
    i1 = r["__interrupt__"][0].value
    log.append({"interrupt": i1["step"], "shown": i1})
    human1 = {"synthetic": True, "actions": [{"equipment_id": "EQ_WALKIN_COOLER", "action": "removed"}], "added": ["EQ_MARINATOR"]}
    log.append({"resume": human1})
    r = app.invoke(Command(resume=human1), cfg)
    i2 = r["__interrupt__"][0].value
    log.append({"interrupt": i2["step"], "shown": i2})
    cands = i2["candidates"]
    human2 = {"synthetic": True, "selections": [synthetic_answer(i2, cands[0], cur_n=1, plan_rest=True, measures=1),
                                                synthetic_answer(i2, cands[1], none=True)]}
    log.append({"resume": human2})
    r = app.invoke(Command(resume=human2), cfg)
    hg.close()
    OUT.mkdir(parents=True, exist_ok=True)
    final = {k: r.get(k) for k in ("equipment_confirmed", "request", "response", "filter_log", "user_selection", "risk_result", "checks", "trace")}
    final["llm_calls"] = {k: (None if v is None else {x: v[x] for x in ("attempts", "seconds", "mode")}) for k, v in (r.get("llm") or {}).items()}
    final["wall_seconds"] = round(time.time() - t0, 2)
    final["backend"] = hg.backend_name
    final["note"] = "합성 탐지·합성 사람 입력(시험용). 위험도는 팀 백엔드 정책 CATALOG-MVP-1.0(MVP 운영 규칙, 전문가 승인 기준 아님)."
    (OUT / f"demo_state{tag}.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"demo_interrupts{tag}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        (OUT / "graph.mmd").write_text(app.get_graph().draw_mermaid(), encoding="utf-8")
    except Exception as e:  # 그림 생성 실패는 실행 결과와 무관
        print("mermaid 생략:", e)
    bad = {k: v for k, v in r["checks"].items() if k != "postprocess" and v}
    print(json.dumps({"trace": r["trace"], "schema_errors": bad, "postprocess": r["checks"]["postprocess"],
                      "risk": [(x["selection_id"], x["phase"], x["catalog_scenario_id"], x["grade"], x["signal"]) for x in r["risk_result"]["results"]],
                      "policy": r["risk_result"]["policy_version"]}, ensure_ascii=False, indent=1))
    sys.exit(1 if bad else 0)


def demo_sam3(group: str = "nene", threshold: float = 0.50):
    """실제 SAM 3 탐지 응답(Cloud 2026-11-16, 평가셋 34장)에서 한 묶음 사진만 골라 그래프를 끝까지 실행한다.
    임계값은 비교 평가에서 쓴 값(서비스 임계값 아님). 사람 입력은 합성(시험용)."""
    from langgraph.types import Command
    src = ROOT.parent / "261116_기기탐지_YOLO전환_DR" / "cloud" / "outputs" / "out_sam3.json"
    resp = json.loads(src.read_text(encoding="utf-8"))["model_output"]
    photos = [p["photo_id"] for p in resp["photos"] if p["photo_id"].split("_")[1] == group]
    hg = HitlGraph()
    app = hg.build()
    cfg = {"configurable": {"thread_id": f"sam3-{group}"}}
    det = {"response": resp, "photo_ids": photos, "threshold": threshold}
    r = app.invoke({"assessment_id": f"A-SAM3-{group}", "detection": det, "trace": [], "checks": {}}, cfg)
    if "__interrupt__" not in r:
        raise SystemExit(f"기기 확인 단계에 도달하지 못함: {r.get('trace')}")
    shown1 = r["__interrupt__"][0].value
    human1 = {"synthetic": True, "actions": [], "added": []}   # 탐지 결과를 그대로 유지(시험)
    r = app.invoke(Command(resume=human1), cfg)
    if "__interrupt__" not in r:
        out = {"stopped_at": "assemble", "checks": r.get("checks"), "trace": r.get("trace")}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        raise SystemExit(1)
    shown2 = r["__interrupt__"][0].value
    cands = shown2["candidates"]
    human2 = {"synthetic": True, "selections": [synthetic_answer(shown2, cands[0], cur_n=1, plan_rest=True, measures=1)]}
    r = app.invoke(Command(resume=human2), cfg)
    hg.close()
    OUT.mkdir(parents=True, exist_ok=True)
    final = {"source": str(src.relative_to(ROOT.parent)), "group": group, "photos": photos, "threshold_used": threshold,
             "threshold_note": "비교 평가에서 쓴 값. 서비스 임계값 아님(문서 Q1 미정)",
             "detection_summary": r.get("detection_summary"), "proposed": shown1["proposed"],
             **{k: r.get(k) for k in ("equipment_confirmed", "response", "filter_log", "user_selection", "risk_result", "checks", "trace")},
             "note": "실제 SAM 3 탐지 + 합성 사람 입력(시험용). LLM은 Cloud enum 응답 재생."}
    (OUT / f"demo_state_sam3_{group}.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = {k: v for k, v in r["checks"].items() if k != "postprocess" and v}
    print(json.dumps({"photos": len(photos), "summary": r.get("detection_summary", {}).get("excluded"),
                      "ai_found": [(p["equipment_id"], p["confidence"], len(p["detection_refs"])) for p in shown1["proposed"]],
                      "trace": r["trace"], "schema_errors": bad,
                      "groups": [(g["equipment_id"], g["group_status"], len(g["candidates"])) for g in r["response"]["groups"]]},
                     ensure_ascii=False, indent=1))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["demo", "bundle", "demo_sam3"])
    ap.add_argument("--group", default="nene")
    ap.add_argument("--threshold", type=float, default=0.50)
    ap.add_argument("--backend", choices=["replay", "vllm"])
    ap.add_argument("--bundle")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.cmd == "bundle":
        print(export_bundle(OUT / "bundle_v1.json"))
    elif a.cmd == "demo_sam3":
        demo_sam3(a.group, a.threshold)
    else:
        try:
            demo(a.backend, a.bundle, a.tag)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        except Exception:
            import traceback
            traceback.print_exc()
            code = 1
        else:
            code = 0
        sys.stdout.flush()
        os._exit(code)   # vLLM 엔진 하위 프로세스가 남아 GPU를 잡지 않도록 즉시 종료
