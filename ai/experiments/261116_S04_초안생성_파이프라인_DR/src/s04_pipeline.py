"""Safe-T S04 초안 생성 파이프라인 프로토타입 (v0.1, 2026-11-16).

순서: 입력 정규화 → RAG 검색(BM25) → 위험 항목 생성 → 신호·판단 이유 → 검증된 법령 연결
→ 현재 조치 후보 → 빨강·노랑 추천 대책 3개 → 스키마 검증 → 저장.
각 단계가 끝나면 ProgressEvent(20/40/60/80/100)를 낸다.

표준 라이브러리만 쓴다. 스키마 검증은 jsonschema가 있을 때만 실행한다
(`uv run --with jsonschema --with referencing --with rfc3339-validator --with rfc3987 ...`).
API 키 값은 출력·기록하지 않는다.
"""
from __future__ import annotations

import copy
import hashlib
import datetime as _dt
import json
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

KST = _dt.timezone(_dt.timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent


def now_kst() -> str:
    return _dt.datetime.now(KST).isoformat(timespec="seconds")


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- 검색(BM25)
_WORD = re.compile(r"[0-9A-Za-z가-힣]+")


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    for w in _WORD.findall(text.lower()):
        toks.append(w)
        if len(w) >= 2 and re.search(r"[가-힣]", w):
            toks.extend(w[i:i + 2] for i in range(len(w) - 1))
    return toks


class BM25:
    def __init__(self, docs: list[tuple[str, str]], k1: float = 1.2, b: float = 0.75):
        self.ids = [d[0] for d in docs]
        self.tfs = [Counter(tokenize(d[1])) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.k1, self.b = k1, b

    def search(self, query: str, top_k: int, allow=None) -> list[tuple[str, float]]:
        q = Counter(tokenize(query))
        scored = []
        for i, tf in enumerate(self.tfs):
            if allow is not None and not allow(self.ids[i]):
                continue
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg))
            if s > 0:
                scored.append((self.ids[i], round(s, 3)))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]


# ---------------------------------------------------------------- 지식베이스
class KnowledgeBase:
    def __init__(self, cfg: dict, base: Path):
        p = cfg["paths"]
        r = cfg["retrieval"]
        self.chunks = {c["chunk_id"]: c for c in load_jsonl(base / p["chunks"])}
        rows = load_jsonl(base / p["table"])
        excl = set(r.get("exclude_row_sections", []))
        self.rows = {}
        for row in rows:
            if row["source_section"] in excl:
                continue
            if r.get("exclude_case_rows_from_measures") and row["source_type"] == "case":
                continue
            self.rows[row["row_id"]] = row
        law_doc = json.load(open(base / p["laws"], encoding="utf-8"))
        self.laws = {}
        for v in law_doc["verified"]:
            if v.get("verification_status") != "검증":
                continue
            key = f'{v["law_name"]}|{v["article"]}'
            v = dict(v)
            v["_cited_chunks"] = {c.get("chunk_id") for c in v.get("cited_in", []) if isinstance(c, dict)}
            self.laws[key] = v
        self.unverified_count = len(law_doc.get("unverified", []))
        self.chunk_index = BM25([(k, f'{c["section"]} {c["text"]}') for k, c in self.chunks.items()], r["k1"], r["b"])
        self.row_index = BM25([(k, f'{w["source_section"]} {w["source_text"]}') for k, w in self.rows.items()], r["k1"], r["b"])


# ---------------------------------------------------------------- 스키마 검증
class SchemaValidator:
    """jsonschema가 없으면 available=False로 두고 검증을 '미실행'으로 기록한다."""

    def __init__(self, schema_dir: Path):
        self.available = False
        self.reason = ""
        try:
            import jsonschema  # noqa: F401
            from referencing import Registry, Resource
        except ImportError as e:  # pragma: no cover
            self.reason = f"jsonschema 미설치: {e}"
            return
        import jsonschema
        reg = Registry()
        self.schemas = {}
        for f in schema_dir.glob("*.schema.json"):
            s = json.load(open(f, encoding="utf-8"))
            reg = reg.with_resource(s["$id"], Resource.from_contents(s))
            self.schemas[f.name] = s
        self.registry = reg
        self.fc = jsonschema.Draft202012Validator.FORMAT_CHECKER
        self.checked_formats = sorted(self.fc.checkers.keys())
        self._v = {}
        self.available = True

    def _validator(self, name: str, fragment: str | None = None):
        import jsonschema
        key = (name, fragment)
        if key not in self._v:
            if fragment:
                schema = {"$ref": f'{self.schemas[name]["$id"]}#{fragment}'}
            else:
                schema = self.schemas[name]
            self._v[key] = jsonschema.Draft202012Validator(schema, registry=self.registry, format_checker=self.fc)
        return self._v[key]

    def errors(self, name: str, instance, fragment: str | None = None) -> list[str]:
        if not self.available:
            return []
        v = self._validator(name, fragment)
        return [f'{"/".join(map(str, e.absolute_path)) or "(root)"}: {e.message[:300]}' for e in v.iter_errors(instance)]


# ---------------------------------------------------------------- LLM 클라이언트
class LLMClient:
    """OpenAI 호환 /chat/completions 클라이언트. 엔드포인트·모델 ID는 환경 변수로만 받는다."""

    def __init__(self, llm_cfg: dict):
        self.cfg = llm_cfg
        self.base_url = os.environ.get(llm_cfg["base_url_env"], "").rstrip("/")
        self.model = os.environ.get(llm_cfg["model_env"], "")
        key = os.environ.get(llm_cfg["api_key_env"], "")
        if not key and os.environ.get(llm_cfg["api_key_file_env"]):
            key = Path(os.environ[llm_cfg["api_key_file_env"]]).read_text(encoding="utf-8").strip()
        self._key = key

    def ready(self) -> tuple[bool, str]:
        missing = [n for n, v in (("base_url", self.base_url), ("model", self.model), ("api_key", self._key)) if not v]
        return (not missing, "누락: " + ", ".join(missing) if missing else "")

    def secret_markers(self) -> list[str]:
        return [self._key] if self._key else []

    def chat(self, messages: list[dict]) -> dict:
        body = json.dumps({
            "model": self.model, "messages": messages,
            "temperature": self.cfg["temperature"], "max_tokens": self.cfg["max_tokens"],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"})
        with urllib.request.urlopen(req, timeout=self.cfg["timeout_sec"]) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------- 유틸
def clean_measure_text(text: str, limit: int = 120) -> str:
    t = re.split(r"\s※|\s\*\s", text)[0].strip()
    t = re.sub(r"\*$", "", t).strip()
    if len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return t


def control_type_of(text: str, kw: dict) -> str | None:
    for ctype in ("ppe", "elimination_substitution", "engineering", "administrative"):
        if any(k in text for k in kw.get(ctype, [])):
            return ctype
    return None


def split_equipment(name: str) -> list[str]:
    return [p.strip() for p in re.split(r"[·,/]", name) if p.strip()]


_FOREIGN = re.compile(r"[぀-ヿ一-鿿À-ɏ]|[A-Za-z]{3,}")


def foreign_script(text: str, allow: list[str]) -> bool:
    """한국어 문장에 일본어 가나·한자·라틴 확장 문자나 허용 목록 밖 영어 단어가 섞였는지."""
    for a in allow:
        text = text.replace(a, "")
    return bool(_FOREIGN.search(text))


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]


# ---------------------------------------------------------------- 파이프라인
class S04Pipeline:
    def __init__(self, config_path: Path, mode: str | None = None, criteria_mode: str | None = None,
                 mock_llm_path: Path | None = None):
        self.cfg = json.load(open(config_path, encoding="utf-8"))
        self.base = config_path.resolve().parent.parent
        if mode:
            self.cfg["backend"]["mode"] = mode
        if criteria_mode:
            self.cfg["signal"]["criteria_mode"] = criteria_mode
        self.mode = self.cfg["backend"]["mode"]
        self.kb = KnowledgeBase(self.cfg, self.base)
        self.validator = SchemaValidator(self.base / self.cfg["paths"]["contract_dir"] / "schemas")
        self.validator_v2 = SchemaValidator(self.base / "contract_v2")
        self.llm = LLMClient(self.cfg["backend"]["llm"]) if self.mode == "llm" else None
        self.mock_llm_path = mock_llm_path
        self.replay, self.replay_attempt, self.parse_failed, self.dup_items = None, 0, False, 0
        self.script_rejects, self.parse_fail_calls, self.replay_calls = 0, 0, None
        self.mismatch_detected, self.mismatch_removed, self.mismatch_log = 0, 0, []
        self.c1_invalid, self.c1_collect, self.c1_reasons = 0, None, []
        self._emap = None
        # 사진 분석(v2): 관찰 단계 결과를 밖에서 넣는다(None이면 v1 동작)
        self.observations = None
        self.observation_stage_version = None
        self.events: list[dict] = []
        self.log: list[dict] = []
        self.raw_llm: list[dict] = []
        self.warnings: list[str] = []

    @property
    def emap(self):
        if self._emap is None:
            from equipment_map import EquipmentMap
            self._emap = EquipmentMap(self.kb.rows)
        return self._emap

    # -- 기록
    def _log(self, stage: str, msg: str, **data):
        self.log.append({"at": now_kst(), "stage": stage, "msg": msg, **data})

    def _progress(self, req_id: str, stage: str, state: str = "done"):
        st = next(s for s in self.stages if s["stage"] == stage)
        ev = {"request_id": req_id, "call": "s04_draft", "stage": stage,
              "percent": st["percent"] if state == "done" else 0, "label": st["label"], "state": state}
        errs = self.validator.errors("common.schema.json", ev, "/$defs/ProgressEvent")
        if errs:
            self._log(stage, "진행률 이벤트 스키마 위반", errors=errs)
        self.events.append({"emitted_at": now_kst(), **ev})
        if self.on_progress:
            self.on_progress(ev)

    @property
    def model_version(self) -> str:
        pv = self.cfg["pipeline_version"]
        if self.mode == "llm" and self.llm and self.llm.model:
            return f"{self.llm.model}+{pv}"
        if self.mode == "mock_llm":
            return f"MOCK-LLM+{pv}"
        if self.mode == "replay" and self.replay:
            return f'{self.replay["model_id"]}@{self.replay["revision"][:12]}+{pv}'.replace("/", "_")
        return f"offline-template+{pv}"

    # -- 실행
    def run(self, request: dict, on_progress=None) -> dict:
        self.on_progress = on_progress
        self.stages = json.load(open(self.base / self.cfg["paths"]["contract_dir"] / "schemas" / "progress_stages.json",
                                     encoding="utf-8"))["s04_draft"]["stages"]
        req_id = request.get("request_id", "unknown-request")
        try:
            return self._run(request, req_id)
        except Exception as e:  # 전체 실패: 입력 유지 후 재시도(15쪽)
            self._log("pipeline", "예외로 초안 생성 실패", error=f"{type(e).__name__}: {e}")
            resp = {"request_id": req_id, "call": "s04_draft", "status": "failed",
                    "error": {"code": "ai_error", "message": "초안을 만들지 못했어요. 입력은 그대로 두었으니 다시 시도해 주세요.",
                              "retryable": True}}
            self.events.append({"emitted_at": now_kst(), "request_id": req_id, "call": "s04_draft",
                                "stage": "pipeline", "percent": 0, "label": "실패", "state": "failed"})
            return resp

    def _run(self, request: dict, req_id: str) -> dict:
        # 1) 입력 정규화
        req_validator = self.validator_v2 if ("detections" in request or self.observations is not None) else self.validator
        req_errs = req_validator.errors("s04_draft.request.schema.json", request)
        if req_errs:
            self._log("analyze_input", "요청 스키마 위반", errors=req_errs)
            return {"request_id": req_id, "call": "s04_draft", "status": "failed",
                    "error": {"code": "bad_request", "message": "입력 형식이 올바르지 않아요.", "retryable": False}}
        norm = self.normalize(request)
        self._log("analyze_input", "입력 정규화", sentences=len(norm["sentences"]), equipment=norm["equipment_terms"],
                  photos=len(norm["photos"]))
        self._progress(req_id, "analyze_input")

        # 2) RAG 검색 + 위험 항목 생성
        if self.mode in ("llm", "mock_llm", "replay"):
            drafts = self.generate_llm(norm)
        else:
            drafts = self.generate_offline(norm)
        self._log("generate_items", "항목 생성", count=len(drafts), keys=[d["item_key"] for d in drafts])
        if not drafts:
            self._progress(req_id, "generate_items", state="failed")
            return {"request_id": req_id, "call": "s04_draft", "status": "failed",
                    "error": ({"code": "invalid_output", "message": "AI 응답 형식이 올바르지 않아 초안을 만들지 못했어요. 다시 시도해 주세요.",
                               "retryable": True} if self.parse_failed else
                              {"code": "insufficient_input", "message": "입력에서 위험 항목을 찾지 못했어요. 사진이나 설명을 더해 주세요.",
                               "retryable": True})}
        self._progress(req_id, "generate_items")

        # 3) 신호·판단 이유 → 법령 → 현재 조치 후보
        judged_at = now_kst()
        for d in drafts:
            self.judge_signal(d, judged_at)
            self.attach_laws(d)
            self.current_candidates(d)
        self._progress(req_id, "judge_signal")

        # 4) 추천 대책 → 스키마 검증
        for d in drafts:
            self.recommend(d)
        items = [self.to_item(d) for d in drafts]
        resp = self.assemble(req_id, items)
        resp = self.validate_and_repair(resp)
        self._progress(req_id, "recommend_measures")
        return resp

    # -- 1단계
    def normalize(self, request: dict) -> dict:
        fi = request["field_input"]
        sentences = []
        if fi.get("text"):
            sentences += [("text", s) for s in split_sentences(fi["text"])]
        for v in fi.get("voice_transcripts", []):
            sentences += [(v["audio_id"], s) for s in split_sentences(v["transcript"])]
        photos = [{"photo_id": p["photo_id"], "location_label": p.get("location_label")} for p in fi.get("photos", [])]
        for p in photos:
            if p["location_label"]:
                sentences.append((p["photo_id"], f'사진 장소: {p["location_label"]}'))
        if photos:
            self.warnings.append("프로토타입은 사진 내용을 분석하지 않고 사진별 장소 입력만 사용했습니다.")
        equipment = []
        for e in request.get("equipment", []):
            for term in split_equipment(e["name"]):
                equipment.append({"term": term, "name": e["name"], "equipment_id": e.get("equipment_id"), "origin": e["origin"]})
        # v2: 탐지 결과(탐지 모델 또는 oracle_label)를 기기로 쓴다. VLM은 기기를 판정하지 않는다.
        det_by_eq = {}
        for dct in request.get("detections", []):
            det_by_eq.setdefault(dct["equipment_id"], []).append(dct)
        for eid, dets in det_by_eq.items():
            name = self.emap.equipment[eid]["standard_name"] if eid in self.emap.equipment else eid
            if any(e["name"] == name for e in equipment):
                continue
            for term in split_equipment(name):
                equipment.append({"term": term, "name": name, "equipment_id": eid, "origin": "detected",
                                  "detection_ids": [x["detection_id"] for x in dets],
                                  "photo_ids": sorted({x["photo_id"] for x in dets})})
        if self.observations is not None:
            for o in self.observations:
                if o["hazard_state"] != "none":
                    sentences.append((o["observation_id"], o["text"]))
        return {"industry": request["business"]["industry"], "sentences": sentences, "photos": photos,
                "observations": self.observations or [],
                "equipment": equipment, "equipment_terms": [e["term"] for e in equipment],
                "all_text": " ".join(s for _, s in sentences)}

    # -- 2단계: 오프라인 템플릿
    def _retrieve(self, query: str, sections: list[str] | None):
        r = self.cfg["retrieval"]
        chunks = self.kb.chunk_index.search(query, r["top_k_chunks"])
        allow = (lambda rid: self.kb.rows[rid]["source_section"] in sections) if sections else None
        rows = self.kb.row_index.search(query, r["top_k_rows"], allow)
        return chunks, rows

    def generate_offline(self, norm: dict) -> list[dict]:
        drafts, covered = [], set()
        for t in self.cfg["offline_templates"]["templates"]:
            eq_hit = [e for e in norm["equipment"] if any(k in e["term"] for k in t["triggers"]["equipment"])]
            sent_hit = [(sid, s) for sid, s in norm["sentences"] if any(k in s for k in t["triggers"]["text"])]
            if not eq_hit and not sent_hit:
                continue
            covered.update(s for _, s in sent_hit)
            query = " ".join([t["rag_query"]] + [s for _, s in sent_hit])
            chunks, _ = self._retrieve(query, t["row_sections"])
            mk, secs = t.get("measure_keywords") or [], set(t["row_sections"])
            rows = self.kb.row_index.search(
                query, self.cfg["retrieval"]["top_k_rows"],
                lambda rid, mk=mk, secs=secs: self.kb.rows[rid]["source_section"] in secs
                and (not mk or any(k in self.kb.rows[rid]["source_text"] for k in mk)))
            loc = None
            for p in norm["photos"]:
                if p["location_label"] and any(k in p["location_label"] for k in t["location_keywords"]):
                    loc = p["location_label"]
                    break
            drafts.append({
                "item_key": f"draft-{len(drafts) + 1}", "template": t, "work": t["work"], "hazard": t["hazard"],
                "accident_type": t["accident_type"], "cause": t["cause"], "description": t["description"],
                "location": loc,
                "equipment_refs": sorted({e["equipment_id"] for e in eq_hit if e["equipment_id"]}),
                "input_refs": sorted({sid for sid, _ in sent_hit}) + (["equipment"] if eq_hit else []),
                "input_snippets": [s for _, s in sent_hit][:2],
                "matched_equipment": sorted({e["name"] for e in eq_hit}),
                "chunks": chunks, "rows": rows,
                "level": t.get("provisional_level"), "level_note": t.get("level_note", ""),
                "off_reason_code": t.get("off_reason_code"), "off_reason_text": t.get("off_reason_text"),
                "law_candidates": t.get("law_candidates", []),
            })
            self._log("generate_items", f'템플릿 {t["template_id"]} 적용',
                      equipment_hit=[e["name"] for e in eq_hit], sentence_hit=[s for _, s in sent_hit],
                      chunks=chunks, rows=rows)
        # 템플릿에 맞지 않은 문장 → 검색 결과로 항목, 신호 off
        fb = self.cfg["fallback_generic_item"]
        for sid, s in norm["sentences"]:
            if s in covered or s.startswith("사진 장소:"):
                continue
            chunks, rows = self._retrieve(s, None)
            if not rows or rows[0][1] < fb["min_row_score"]:
                self._log("generate_items", "템플릿·검색 모두 약해 항목을 만들지 않음", sentence=s, top=rows[:1])
                continue
            top = self.kb.rows[rows[0][0]]
            acc = next((a for rid, _ in rows for a in self.kb.rows[rid].get("accident_type_terms_in_text") or []), "미분류")
            work = fb["work_label"]  # 검색 1위 절 이름은 오분류가 잦아(예: 출입문 → 리프트) 작업명으로 쓰지 않는다.
            short = s if len(s) <= 60 else s[:59] + "…"
            drafts.append({
                "item_key": f"draft-{len(drafts) + 1}", "template": None, "work": work, "hazard": short,
                "accident_type": acc, "cause": short, "description": s, "location": None, "equipment_refs": [],
                "input_refs": [sid], "input_snippets": [s], "matched_equipment": [], "chunks": chunks, "rows": rows,
                "level": None, "level_note": "", "off_reason_code": "insufficient_input",
                "off_reason_text": fb["off_reason_text"], "law_candidates": [],
            })
            self._log("generate_items", "범용 항목 생성(신호 off)", sentence=s, rows=rows[:3])
        return drafts

    # -- 2단계: LLM
    def _criteria_text(self) -> str:
        sig = self.cfg["signal"]
        if sig["criteria_mode"] == "strict":
            return "판단기준이 확정되지 않았다. 모든 항목의 level은 \"unknown\"으로 둔다."
        lv = sig["provisional_criteria"]["levels"]
        return ("아래 임시 판단기준(안내서 예시, 팀 미채택)으로만 level을 고른다. 근거가 부족하면 \"unknown\".\n"
                + "\n".join(f'- {k}: {v["text"]}' for k, v in lv.items()))

    _SYSTEM = ("너는 음식점 위험성평가 초안을 돕는 보조 도구다. 주어진 현장 입력과 참고자료 안에서만 답한다. "
               "안전 기준이나 법령을 지어내지 않는다. 사용자가 고를 값(현재 조치 선택, 대책 체크, 담당자, 예정일)은 만들지 않는다. "
               "출력은 JSON 객체 하나만 쓴다.")

    def _llm_prompt(self, norm: dict, chunks, rows, law_keys, focus: str | None = None) -> list[dict]:
        """기준선 프롬프트. focus가 None이면 1차 Cloud 실행(2026-11-16 00:51)과 글자 단위로 같다."""
        ctx_rows = "\n".join(f'- [{rid}] ({self.kb.rows[rid]["source_section"]}) {self.kb.rows[rid]["source_text"][:160]}'
                             for rid, _ in rows)
        ctx_chunks = "\n".join(f'- [{cid}] ({self.kb.chunks[cid]["section"]}) {self.kb.chunks[cid]["text"][:400]}'
                               for cid, _ in chunks)
        ctx_laws = "\n".join(f'- [{k}] {self.kb.laws[k]["article_title"]}: {self.kb.laws[k]["gist"]}' for k in law_keys) or "- (없음)"
        crit = self._criteria_text()
        inputs = "\n".join(f"- [{sid}] {s}" for sid, s in norm["sentences"])
        if focus:
            task = f"작업: 이번에는 {focus}에서 생기는 위험만 다룬다. 위험 항목을 1~3개 만든다. 해당 위험이 없으면 items를 빈 배열로 둔다."
        else:
            task = f'작업: 현장 입력과 기기에서 위험 항목을 최대 {self.cfg["backend"]["llm"]["max_items"]}개 만든다.'
        user = f"""업종: {norm["industry"]}
보유 기기: {", ".join(sorted(set(e["name"] for e in norm["equipment"]))) or "(없음)"}
현장 입력:
{inputs}

참고자료(점검표 행):
{ctx_rows}

참고자료(안내서 청크):
{ctx_chunks}

검증된 법령 후보(이 키만 쓸 수 있음):
{ctx_laws}

판단기준:
{crit}

{task}
JSON 형식:
{{"items":[{{"work":"작업","hazard":"위험요인 제목","accident_type":"사고 유형","cause":"원인(짧게)","description":"위험 설명",
"location":null,"input_evidence":["입력 ID"],"level":"high|medium|low|unknown","level_reason":"판단 이유(2문장 이내)",
"rag_ids":["참고자료 ID"],"law_keys":["법령 키"],"current_measure_row_ids":["점검표 행 ID"],
"recommended_measures":[{{"text":"대책(120자 이내)","control_type":"elimination_substitution|engineering|administrative|ppe","source_ids":["참고자료 ID"]}}]}}]}}
high·medium 항목은 recommended_measures를 정확히 3개 쓴다. low·unknown은 빈 배열로 둔다."""
        return [{"role": "system", "content": self._SYSTEM}, {"role": "user", "content": user}]

    def _llm_prompt_candidates(self, norm: dict, chunks, rows, law_keys, focus: str | None = None) -> list[dict]:
        """개선 B: 점검표 후보 행을 먼저 주고, 모델은 후보 ID를 고르게 한다. 대책 문장은 서버가 후보 원문으로 채운다."""
        cand = "\n".join(f'- {rid} | {self.kb.rows[rid]["source_section"]} | {clean_measure_text(self.kb.rows[rid]["source_text"], 140)}'
                         for rid, _ in rows)
        hints = "\n".join(f'- {self.kb.chunks[cid]["section"]}: {self.kb.chunks[cid]["text"][:250]}' for cid, _ in chunks)
        ctx_laws = "\n".join(f'- {k} | {self.kb.laws[k]["article_title"]}: {self.kb.laws[k]["gist"]}' for k in law_keys) or "- (없음)"
        inputs = "\n".join(f"- {sid}: {s}" for sid, s in norm["sentences"])
        target = f"{focus}에서 생기는 위험" if focus else "현장 입력과 보유 기기에서 생기는 위험"
        n = "1~3개" if focus else f'최대 {self.cfg["backend"]["llm"]["max_items"]}개'
        user = f"""업종: {norm["industry"]}
보유 기기: {", ".join(sorted(set(e["name"] for e in norm["equipment"]))) or "(없음)"}
현장 입력(ID: 문장):
{inputs}

후보 점검표 행(ID | 분류 | 내용). 아래 ID만 쓸 수 있다:
{cand}

참고 설명(사고 사례 요약):
{hints or "- (없음)"}

검증된 법령 후보(키 | 조항). 아래 키만 쓸 수 있다:
{ctx_laws}

판단기준:
{self._criteria_text()}

작업: {target}을 {n} 만든다. 해당 위험이 없으면 items를 빈 배열로 둔다.
- source_row_ids: 이 위험의 근거가 된 후보 행 ID(1개 이상).
- current_row_ids: 매장에서 이미 하고 있을 수 있는 조치에 해당하는 후보 행 ID(0~4개).
- recommended_row_ids: high·medium이면 대책으로 쓸 후보 행 ID를 서로 다르게 정확히 3개 고른다. low·unknown이면 빈 배열.
- 대책 문장은 직접 쓰지 않는다. 모든 문장은 한국어로 쓴다.
JSON 형식:
{{"items":[{{"work":"작업","hazard":"위험요인 제목","accident_type":"사고 유형","cause":"원인(짧게)","description":"위험 설명",
"input_evidence":["입력 ID"],"level":"high|medium|low|unknown","level_reason":"판단 이유(2문장 이내)",
"source_row_ids":["후보 ID"],"current_row_ids":["후보 ID"],"recommended_row_ids":["후보 ID"],"law_keys":["법령 키"]}}]}}"""
        return [{"role": "system", "content": self._SYSTEM}, {"role": "user", "content": user}]

    def _llm_prompt_candidates_v2(self, norm: dict, chunks, rows, law_keys, focus: str | None = None) -> list[dict]:
        """개선 B 2판(2026-11-16 01:30 이후): 1판에서 모델이 'high|medium|low|unknown', '작업', 호출 대상 문구를
        그대로 베낀 문제를 줄이려고 값 규칙을 문장으로 따로 쓰고 JSON 틀에는 빈 값만 둔다."""
        cand = "\n".join(f'- {rid} | {self.kb.rows[rid]["source_section"]} | {clean_measure_text(self.kb.rows[rid]["source_text"], 140)}'
                         for rid, _ in rows)
        hints = "\n".join(f'- {self.kb.chunks[cid]["section"]}: {self.kb.chunks[cid]["text"][:250]}' for cid, _ in chunks)
        ctx_laws = "\n".join(f'- {k} | {self.kb.laws[k]["article_title"]}: {self.kb.laws[k]["gist"]}' for k in law_keys) or "- (없음)"
        inputs = "\n".join(f"- {sid}: {s}" for sid, s in norm["sentences"])
        ids = ", ".join(sid for sid, _ in norm["sentences"])
        target = f"{focus}에서 생기는 위험" if focus else "현장 입력과 보유 기기에서 생기는 위험"
        n = "1~2개" if focus else f'최대 {self.cfg["backend"]["llm"]["max_items"]}개(서로 다른 위험만)'
        lv = self.cfg["signal"]["provisional_criteria"]["levels"]
        user = f"""업종: {norm["industry"]}
보유 기기: {", ".join(sorted(set(e["name"] for e in norm["equipment"]))) or "(없음)"}
현장 입력(ID: 문장):
{inputs}

후보 점검표 행(ID | 분류 | 내용):
{cand}

참고 설명(사고 사례 요약):
{hints or "- (없음)"}

검증된 법령 후보(키 | 조항):
{ctx_laws}

할 일: {target}을 {n} 만든다. 해당 위험이 없으면 {{"items":[]}}만 쓴다.

값 규칙:
1. work: 실제 작업 이름을 2~8글자로 쓴다. 예: 튀김 조리, 재료 손질, 식자재 운반.
2. hazard: 무엇 때문에 어떤 사고가 나는지 한 문장으로 쓴다. 예: 뜨거운 기름이 튀어 화상.
3. accident_type: 화상, 베임, 끼임, 넘어짐, 화재, 폭발, 감전, 근골격계 질환, 부딪힘, 기타 중 하나.
4. input_evidence: 근거가 된 입력 ID. 쓸 수 있는 값: {ids}.
5. level: high, medium, low, unknown 중 정확히 한 단어. 기준(임시, 안내서 예시):
   high = {lv["high"]["text"]} / medium = {lv["medium"]["text"]} / low = {lv["low"]["text"]}. 근거가 부족하면 unknown.
6. source_row_ids: 위 후보 점검표 행 ID 중 이 위험과 관련된 것 1~3개.
7. current_row_ids: 후보 ID 중 매장에서 이미 하고 있을 수 있는 조치 0~3개.
8. recommended_row_ids: level이 high나 medium이면 후보 ID 중 이 위험을 줄이는 대책 정확히 3개(서로 다르게). low나 unknown이면 빈 배열.
9. law_keys: 위 법령 키 중 관련 있는 것만. 없으면 빈 배열.
10. 모든 문장은 한국어로만 쓴다. 대책 문장은 쓰지 않는다.

출력은 아래 틀의 JSON 하나만 쓴다(빈 값을 위 규칙대로 채운다):
{{"items":[{{"work":"","hazard":"","accident_type":"","cause":"","description":"","input_evidence":[],"level":"","level_reason":"","source_row_ids":[],"current_row_ids":[],"recommended_row_ids":[],"law_keys":[]}}]}}"""
        return [{"role": "system", "content": self._SYSTEM}, {"role": "user", "content": user}]

    def _mapped_rows(self, eq_ids: list[str], queries: list[str], top: int):
        """기기마스터 매핑 행(점검표 절·참조 행) + 그 기기 위험요인 코드 낱말이 든 행을 BM25로 정렬."""
        em = self.emap
        pool = set(em.rows_for(eq_ids)) | set(em.rows_with_codes(list(em.codes(eq_ids))))
        q = " ".join(queries + [em.describe(e) for e in eq_ids])
        return self.kb.row_index.search(q, top, lambda rid: rid in pool)

    def _llm_prompt_items_v3(self, norm: dict, chunks, rows, law_keys, focus=None, eq_ids=None) -> list[dict]:
        """3판(2026-11-16 09시대): A(단위 분할) + B2 값 규칙. 대책은 이 호출에서 고르지 않는다(C1·C2 단계에서 처리).
        기기마스터의 관련 위험요인(초안)을 참고로 준다."""
        cand = "\n".join(f'- {rid} | {self.kb.rows[rid]["source_section"]} | {clean_measure_text(self.kb.rows[rid]["source_text"], 140)}'
                         for rid, _ in rows)
        hints = "\n".join(f'- {self.kb.chunks[cid]["section"]}: {self.kb.chunks[cid]["text"][:250]}' for cid, _ in chunks)
        ctx_laws = "\n".join(f'- {k} | {self.kb.laws[k]["article_title"]}: {self.kb.laws[k]["gist"]}' for k in law_keys) or "- (없음)"
        inputs = "\n".join(f"- {sid}: {s}" for sid, s in norm["sentences"])
        ids = ", ".join(sid for sid, _ in norm["sentences"])
        eqh = "\n".join(f"- {self.emap.equipment[e]['standard_name']}: {self.emap.describe(e)}" for e in (eq_ids or [])) or "- (해당 없음)"
        target = f"{focus}에서 생기는 위험" if focus else "현장 입력과 보유 기기에서 생기는 위험"
        lv = self.cfg["signal"]["provisional_criteria"]["levels"]
        if self.cfg["backend"]["llm"].get("item_prompt") == "v4_items":
            # 4판(3차 2회): 3판의 예시 문장('튀김 조리', '뜨거운 기름이 튀어 화상')을 모델이 그대로 베껴 모든 기기에
            # 같은 항목이 나왔다. 예시를 없애고 이 기기와의 관련만 요구한다.
            task_rules = (f"할 일: {target}을 1~2개 만든다. 위 '이 기기에서 알려진 위험요인' 중에서 현장 입력과 맞는 것만 고른다. "
                          "다른 기기에서 생기는 위험은 쓰지 않는다. 맞는 위험이 없으면 {\"items\":[]}만 쓴다.\n\n"
                          "값 규칙:\n"
                          "1. work: 이 기기로 하는 작업 이름. 현장 입력에 나온 낱말로 짧게 쓴다.\n"
                          "2. hazard: 이 기기 때문에 생기는 원인과 사고를 한 문장으로 쓴다.")
        else:
            task_rules = (f"할 일: {target}을 1~2개 만든다. 이 기기에서 알려진 위험요인과 현장 입력에 맞는 것만 쓴다. "
                          "해당 위험이 없으면 {\"items\":[]}만 쓴다.\n\n"
                          "값 규칙:\n"
                          "1. work: 실제 작업 이름을 2~8글자로 쓴다. 예: 튀김 조리, 재료 손질, 식자재 운반.\n"
                          "2. hazard: 무엇 때문에 어떤 사고가 나는지 한 문장으로 쓴다. 예: 뜨거운 기름이 튀어 화상.")
        user = f"""업종: {norm["industry"]}
보유 기기: {", ".join(sorted(set(e["name"] for e in norm["equipment"]))) or "(없음)"}
현장 입력(ID: 문장):
{inputs}

이 기기에서 알려진 위험요인(기기마스터 초안, 참고):
{eqh}

후보 점검표 행(ID | 분류 | 내용):
{cand or "- (없음)"}

참고 설명(사고 사례 요약):
{hints or "- (없음)"}

검증된 법령 후보(키 | 조항):
{ctx_laws}

{task_rules}
3. accident_type: 화상, 베임, 끼임, 넘어짐, 화재, 폭발, 감전, 근골격계 질환, 부딪힘, 기타 중 하나.
4. input_evidence: 근거가 된 입력 ID. 쓸 수 있는 값: {ids}.
5. level: high, medium, low, unknown 중 정확히 한 단어. 기준(임시, 안내서 예시):
   high = {lv["high"]["text"]} / medium = {lv["medium"]["text"]} / low = {lv["low"]["text"]}. 근거가 부족하면 unknown.
6. source_row_ids: 위 후보 점검표 행 ID 중 이 위험과 관련된 것 1~3개.
7. current_row_ids: 후보 ID 중 매장에서 이미 하고 있을 수 있는 조치 0~3개.
8. law_keys: 위 법령 키 중 관련 있는 것만. 없으면 빈 배열.
9. 모든 문장은 한국어로만 쓴다. 대책은 쓰지 않는다.

출력은 아래 틀의 JSON 하나만 쓴다(빈 값을 위 규칙대로 채운다):
{{"items":[{{"work":"","hazard":"","accident_type":"","cause":"","description":"","input_evidence":[],"level":"","level_reason":"","source_row_ids":[],"current_row_ids":[],"law_keys":[]}}]}}"""
        return [{"role": "system", "content": self._SYSTEM}, {"role": "user", "content": user}]

    def _measure_pool(self, d: dict) -> tuple[list[str], list[str]]:
        """대책 후보: 1순위 = 항목 기기의 매핑 행 중 항목 위험요인 코드 낱말이 든 행, 2순위 = 코드 낱말이 든 전체 행."""
        em = self.emap
        codes = em.classify(" ".join([d["hazard"], d["accident_type"], d["cause"]]))
        if not codes:
            return [], []
        kws = [k for c in codes for k in em.code_keywords[c]]
        tier1 = [r for r in em.rows_for(d.get("unit_eq_ids", [])) if any(k in self.kb.rows[r]["source_text"] for k in kws)]
        tier2 = [r for r in em.rows_with_codes(codes) if r not in tier1]
        return tier1, tier2

    def _rank(self, d: dict, ids: list[str], top: int) -> list[str]:
        if not ids:
            return []
        allow = set(ids)
        q = " ".join([d["hazard"], d["cause"], d["description"]])
        ranked = [rid for rid, _ in self.kb.row_index.search(q, top, lambda r: r in allow)]
        if self.cfg["backend"]["llm"].get("rank_keep_unscored", False):
            ranked += [r for r in ids if r not in ranked]   # 3차 2회(A3)부터: 점수 0인 풀 행을 버리지 않는다
        return ranked[:top]

    def c1_call(self, d: dict) -> dict:
        t1, t2 = self._measure_pool(d)
        cands = (self._rank(d, t1, 10) + self._rank(d, t2, 10))[:10]
        if len(cands) < 3:
            cands = cands + [r for r, _ in self.kb.row_index.search(d["hazard"] + " " + d["cause"], 10) if r not in cands]
            cands = cands[:10]
        lst = "\n".join(f'- {rid}: {clean_measure_text(self.kb.rows[rid]["source_text"], 140)}' for rid in cands)
        user = f"""위험 항목:
- 작업: {d["work"]}
- 위험요인: {d["hazard"]}
- 사고 유형: {d["accident_type"]}
- 원인: {d["cause"]}

대책 후보(ID: 내용):
{lst}

할 일: 이 위험을 줄이는 데 가장 맞는 대책 후보 3개를 고른다.
규칙: 위 후보 ID만 쓴다. 서로 다른 ID 3개를 쓴다. 빈 칸을 남기지 않는다. 설명을 쓰지 않는다.
출력은 아래 틀의 JSON 하나만 쓴다(각 칸에 후보 ID를 하나씩 넣는다):
{{"recommended_row_ids":["","",""]}}"""
        key = hashlib.sha1(f'{d["work"]}|{d["hazard"]}|{d["accident_type"]}'.encode("utf-8")).hexdigest()[:10]
        return {"unit_id": f'c1:{d["unit_id"]}:{key}', "candidates_c1": cands,
                "messages": [{"role": "system", "content": self._SYSTEM}, {"role": "user", "content": user}]}

    def _measures_from_ids(self, ids: list[str]) -> list[dict]:
        kw = self.cfg["measures"]["control_type_keywords"]
        rec, seen_t = [], set()
        for rid in ids:
            txt = clean_measure_text(self.kb.rows[rid]["source_text"])
            if txt in seen_t:
                continue
            seen_t.add(txt)
            rec.append({"measure_id": f"rm-{rid}", "text": txt, "control_type": control_type_of(txt, kw)})
        return rec

    def recommend_staged(self, d: dict, stage: str) -> bool:
        """C1·C2 대책 단계. 처리했으면 True."""
        want = self.cfg["measures"]["recommended_count"]
        if stage == "c2":
            t1, t2 = self._measure_pool(d)
            picked = self._rank(d, t1, 10) + [r for r in self._rank(d, t2, 30)]
            rec = self._measures_from_ids(picked)[:want]
            d["measure_tiers"] = {"tier1": len(t1), "tier2": len(t2)}
            if len(rec) == want:
                d.update(rec_status="ok", rec=rec)
            else:
                self._log("recommend_measures", "C2 규칙 후보 부족 → failed", item=d["item_key"], found=len(rec))
                d.update(rec_status="failed", rec=[])
            return True
        if stage == "c1":
            call = self.c1_call(d)
            if self.c1_collect is not None:
                self.c1_collect.append({"unit_id": call["unit_id"], "messages": call["messages"], "expect_key": "recommended_row_ids"})
                d.update(rec_status="failed", rec=[])
                return True
            content, raw = self._content_for(call)
            self.raw_llm.append({"at": now_kst(), "unit_id": call["unit_id"], "messages": call["messages"], "response": raw})
            m = re.search(r"\{.*\}", content or "", re.S)
            reason = None
            try:
                ids = json.loads(m.group(0)).get("recommended_row_ids") if m else None
            except (json.JSONDecodeError, AttributeError):
                ids = None
            if not isinstance(ids, list):
                reason = "형식 오류"
            else:
                ids = [x.strip() for x in ids if isinstance(x, str) and x.strip()]
                if not ids:
                    reason = "빈 배열"
                elif any(x not in call["candidates_c1"] for x in ids):
                    reason = "후보 밖 ID"
                elif len(set(ids)) != want:
                    reason = f"서로 다른 ID {len(set(ids))}개"
            rec = self._measures_from_ids(list(dict.fromkeys(ids))) if reason is None else []
            if reason is None and len(rec) != want:
                reason = "같은 문장 중복"
            if reason:
                self.c1_invalid += 1
                self.c1_reasons.append(reason)
                self._log("recommend_measures", f"C1 대책 선택 실패({reason}) → failed", item=d["item_key"])
                d.update(rec_status="failed", rec=[])
            else:
                d.update(rec_status="ok", rec=rec)
            return True
        return False

    def _multi_query(self, queries: list[str], top_c: int, top_r: int, per_q_c: int = 3, per_q_r: int = 5):
        best_c: dict[str, float] = {}
        best_r: dict[str, float] = {}
        for q in queries:
            for cid, s in self.kb.chunk_index.search(q, per_q_c):
                best_c[cid] = max(s, best_c.get(cid, 0))
            for rid, s in self.kb.row_index.search(q, per_q_r):
                best_r[rid] = max(s, best_r.get(rid, 0))
        chunks = sorted(best_c.items(), key=lambda x: -x[1])[:top_c]
        rows = sorted(best_r.items(), key=lambda x: -x[1])[:top_r]
        cited = {cid for cid, _ in chunks}
        law_keys = [k for k, v in self.kb.laws.items() if v["_cited_chunks"] & cited]
        return chunks, rows, law_keys

    def build_units(self, norm: dict) -> list[dict]:
        """개선 A: 기기 하나 또는 작업(문장) 하나를 호출 단위로 나눈다."""
        if self.cfg["backend"]["llm"].get("strategy", "single") != "split":
            queries = [s for _, s in norm["sentences"]] + [f'{norm["industry"]} {t}' for t in norm["equipment_terms"]]
            return [{"unit_id": "all", "focus": None, "queries": queries}]
        llm_map = bool(self.cfg["backend"]["llm"].get("equipment_mapping"))
        units, groups = [], {}
        for e in norm["equipment"]:
            groups.setdefault(e["name"], []).append(e["term"])
        for name, terms in groups.items():
            rel = [s for _, s in norm["sentences"] if any(t in s for t in terms)]
            photo_ids = {pid for e in norm["equipment"] if e["name"] == name for pid in e.get("photo_ids", [])}
            rel += [o["text"] for o in norm.get("observations", []) if o["photo_id"] in photo_ids and o["text"] not in rel
                    and o["hazard_state"] != "none"]
            units.append({"unit_id": f"eq:{name}", "focus": f"보유 기기 '{name}'을(를) 쓰는 작업",
                          "queries": [f'{norm["industry"]} {t}' for t in terms] + rel,
                          "eq_ids": self.emap.match(name) if llm_map else []})
        if groups:
            units.append({"unit_id": "site", "focus": "기기와 직접 관련 없는 현장 위험(바닥·통로 이동, 식자재 운반 등)",
                          "queries": [s for _, s in norm["sentences"]]})
        else:
            for i, (sid, s) in enumerate(norm["sentences"]):
                units.append({"unit_id": f"s{i + 1}:{sid}", "focus": f'현장 입력 "{s}"', "queries": [s],
                              "eq_ids": self.emap.match(s) if llm_map else []})
        return units

    def build_calls(self, norm: dict) -> list[dict]:
        llm = self.cfg["backend"]["llm"]
        split = llm.get("strategy", "single") == "split"
        cand = bool(llm.get("candidates"))
        calls = []
        for u in self.build_units(norm):
            if not split and not cand:
                chunks, rows, law_keys = self._multi_query(u["queries"], 12, 36)       # 기준선과 같은 값
            elif split:
                chunks, rows, law_keys = self._multi_query(u["queries"], 4, 15, 2, 6)
            else:
                chunks, rows, law_keys = self._multi_query(u["queries"], 6, 24)
            if cand and llm.get("candidate_prompt_version", 1) == 2:
                fn = self._llm_prompt_candidates_v2
            else:
                fn = self._llm_prompt_candidates if cand else self._llm_prompt
            v3 = llm.get("item_prompt") in ("v3_items", "v4_items")
            if llm.get("equipment_mapping") and u.get("eq_ids"):
                rows = self._mapped_rows(u["eq_ids"], u["queries"], 15)
            if llm.get("item_prompt") == "v4_items":
                v3 = True
            msgs = (self._llm_prompt_items_v3(norm, chunks, rows, law_keys, u["focus"], u.get("eq_ids")) if v3
                    else fn(norm, chunks, rows, law_keys, u["focus"]))
            calls.append({**u, "chunks": chunks, "rows": rows, "law_keys": law_keys, "candidates": cand or v3,
                          "messages": msgs})
        return calls

    def build_llm_context(self, norm: dict):  # 1차 실행용 단일 호출 인터페이스(호환)
        c = self.build_calls(norm)[0]
        return c["chunks"], c["rows"], c["law_keys"], c["messages"]

    def dump_prompt(self, request: dict) -> dict:
        norm = self.normalize(request)
        calls = self.build_calls(norm)
        return {"request_id": request["request_id"],
                "calls": [{"unit_id": c["unit_id"], "messages": c["messages"]} for c in calls],
                "messages": calls[0]["messages"]}

    @staticmethod
    def parse_model_json(content: str):
        """모델 응답에서 JSON 객체를 꺼낸다. 실패하면 (None, 오류). Cloud 재시도 판정과 같은 규칙."""
        m = re.search(r"\{.*\}", content or "", re.S)
        if not m:
            return None, "JSON 객체 없음"
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return None, str(e)[:200]
        if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
            return None, "items 배열 없음"
        return parsed, None

    def _content_for(self, call: dict):
        if self.mode == "mock_llm":
            content = Path(self.mock_llm_path).read_text(encoding="utf-8")
            note = "[모의 응답] 실제 모델 호출이 아니라 저장된 응답 파일로 LLM 경로를 재현했습니다."
            if note not in self.warnings:
                self.warnings.append(note)
            return content, {"mock": True, "source_file": str(self.mock_llm_path), "content": content}
        if self.mode == "replay":
            calls = self.replay_calls or {"all": {"messages": self.replay["messages"], "attempts": self.replay["attempts"],
                                                  "use_attempt": self.replay_attempt}}
            rc = calls.get(call["unit_id"])
            if rc is None or rc["messages"] != call["messages"]:
                raise RuntimeError(f'재생 파일의 프롬프트가 현재 파이프라인 프롬프트와 다름(단위 {call["unit_id"]})')
            att = rc["attempts"][rc["use_attempt"]]
            note = f'[Cloud 모델 출력 재생] {self.replay["model_id"]}@{self.replay["revision"][:12]} 응답을 로컬에서 후처리했습니다.'
            if note not in self.warnings:
                self.warnings.append(note)
            return att["content"], {"replay": True, "unit_id": call["unit_id"], "attempt": att}
        ok, why = self.llm.ready()
        if not ok:
            raise RuntimeError(f"LLM 설정 미완료({why})")
        raw = self.llm.chat(call["messages"])
        return raw["choices"][0]["message"]["content"], raw

    def _is_dup(self, work: str, hazard: str, acc: str, kept: list) -> bool:
        def bg(t):
            return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}
        thr = self.cfg["backend"]["llm"]["postprocess"].get("near_dup_jaccard", 0.5)
        for w, h, a in kept:
            if (w, h) == (work, hazard):
                return True
            if acc and acc == a:
                x, y = bg(re.sub(r"\s", "", hazard)), bg(re.sub(r"\s", "", h))
                if x and y and len(x & y) / len(x | y) >= thr:
                    return True
        return False

    def generate_llm(self, norm: dict) -> list[dict]:
        calls = self.build_calls(norm)
        self._log("generate_items", "LLM 호출 단위", units=[c["unit_id"] for c in calls])
        drafts, kept = [], []
        for call in calls:
            self._log("generate_items", "LLM 요청 준비", unit=call["unit_id"], chunks=call["chunks"], rows=call["rows"],
                      law_keys=call["law_keys"])
            content, raw = self._content_for(call)
            self.raw_llm.append({"at": now_kst(), "unit_id": call["unit_id"], "messages": call["messages"], "response": raw})
            parsed, err = self.parse_model_json(content)
            if parsed is None:
                self._log("generate_items", "모델 응답 JSON 파싱 실패", unit=call["unit_id"], error=err)
                self.parse_failed = True
                self.parse_fail_calls += 1
                continue
            drafts += self._drafts_from_items(parsed["items"], call, norm, kept, len(drafts))
        return drafts

    def _drafts_from_items(self, items, call: dict, norm: dict, kept: list, offset: int) -> list[dict]:
        rows, chunks, law_keys = call["rows"], call["chunks"], call["law_keys"]
        row_ids, chunk_ids = {rid for rid, _ in rows}, {cid for cid, _ in chunks}
        pp = self.cfg["backend"]["llm"].get("postprocess", {})
        input_ids = {sid for sid, _ in norm["sentences"]} | {p_["photo_id"] for p_ in norm["photos"]}

        def nid(x):
            if not isinstance(x, str):
                return ""
            if pp.get("normalize_ids"):
                m_ = re.match(r"\s*\[([^\]]+)\]", x)
                return (m_.group(1) if m_ else x).strip()
            return x.strip() if pp.get("strip_ids") else x

        out = []
        for it in items[: self.cfg["backend"]["llm"]["max_items"]]:
            if not isinstance(it, dict):
                continue
            for k_ in ("input_evidence", "rag_ids", "current_measure_row_ids", "law_keys",
                       "source_row_ids", "current_row_ids", "recommended_row_ids"):
                v_ = it.get(k_)
                it[k_] = [nid(x) for x in (v_ if isinstance(v_, list) else []) if isinstance(x, str)]
            if pp.get("filter_input_ids"):
                it["input_evidence"] = [x for x in it["input_evidence"] if x in input_ids]
            work, hazard = str(it.get("work") or "").strip(), str(it.get("hazard") or "").strip()
            acc = str(it.get("accident_type") or "").strip()
            if not all([work, hazard, acc, str(it.get("cause") or "").strip(), str(it.get("description") or "").strip()]):
                self._log("generate_items", "LLM 항목 필수값 누락으로 제외", unit=call["unit_id"], item=str(it)[:300])
                continue
            if call.get("eq_ids") and pp.get("mismatch_check"):
                item_codes = self.emap.classify(f"{hazard} {acc}")
                allowed = self.emap.codes(call["eq_ids"])
                if item_codes and not set(item_codes) & set(allowed):
                    self.mismatch_detected += 1
                    self.mismatch_log.append({"unit": call["unit_id"], "work": work, "hazard": hazard, "accident_type": acc,
                                              "item_codes": item_codes, "equipment_codes": allowed})
                    self._log("generate_items", "기기-위험 불일치(기기마스터 관련 위험요인에 없음)", unit=call["unit_id"],
                              hazard=hazard, item_codes=item_codes, equipment_codes=list(allowed))
                    if pp.get("mismatch_filter"):
                        self.mismatch_removed += 1
                        continue
            if pp.get("dedupe"):
                if self._is_dup(work, hazard, acc, kept):
                    self._log("generate_items", "중복 항목 제외", unit=call["unit_id"], work=work, hazard=hazard)
                    self.dup_items += 1
                    continue
                kept.append((work, hazard, acc))
                ms, seen_m = [], set()
                for m_ in it.get("recommended_measures") or []:
                    t_ = m_.get("text") if isinstance(m_, dict) else None
                    if t_ and t_.strip() not in seen_m:
                        seen_m.add(t_.strip())
                        ms.append(m_)
                it["recommended_measures"] = ms
            if pp.get("script_gate"):
                allow = pp.get("script_allow", [])
                bad_f = [k_ for k_ in ("work", "hazard", "accident_type", "cause", "description")
                         if foreign_script(str(it.get(k_) or ""), allow)]
                if bad_f:
                    self._log("generate_items", "외국 문자 섞인 항목 → off(invalid_output)", fields=bad_f, hazard=hazard[:60])
                    self.script_rejects += 1
                    it["level"], it["_invalid"] = "unknown", True
                    it["recommended_measures"], it["recommended_row_ids"] = [], []
                kept_m = [m_ for m_ in it.get("recommended_measures") or []
                          if not (isinstance(m_, dict) and foreign_script(str(m_.get("text") or ""), allow))]
                if len(kept_m) != len(it.get("recommended_measures") or []):
                    self._log("generate_items", "외국 문자 섞인 대책 제외", dropped=len(it["recommended_measures"]) - len(kept_m))
                    self.script_rejects += 1
                it["recommended_measures"] = kept_m
            lvl = it.get("level") if it.get("level") in ("high", "medium", "low") else None
            if it.get("_invalid"):
                lvl = None
            obs_refs = [x for x in it["input_evidence"] if x.startswith("obs-")]
            if self.observations is not None and norm["photos"] and not obs_refs and \
                    self.cfg["backend"]["llm"].get("require_observation_evidence", True):
                it["_no_obs"] = True
                lvl = None
            d = {
                "item_key": f"draft-{offset + len(out) + 1}", "template": None, "unit_id": call["unit_id"],
                "unit_eq_ids": call.get("eq_ids", []),
                "work": work, "hazard": hazard, "accident_type": acc,
                "cause": str(it.get("cause") or "").strip(), "description": str(it.get("description") or "").strip(),
                "location": it.get("location") if isinstance(it.get("location"), str) else None,
                "equipment_refs": [], "input_refs": it["input_evidence"], "input_snippets": [], "matched_equipment": [],
                "chunks": [(c, 0.0) for c in it.get("rag_ids", []) if c in chunk_ids],
                "rows": [(x, 0.0) for x in (it["current_row_ids"] if call["candidates"] else it["current_measure_row_ids"])
                         if x in row_ids],
                "level": lvl, "level_note": str(it.get("level_reason") or ""),
                "off_reason_code": ("invalid_output" if it.get("_invalid") else None if lvl else "insufficient_input"),
                "off_reason_text": ("AI 응답 문장이 올바르지 않아 판단하지 못했어요. 다시 판단해 주세요." if it.get("_invalid") else
                                    "사진에서 이 위험의 근거가 되는 상태를 찾지 못해 판단하지 못했어요. 현장을 확인해 주세요."
                                    if it.get("_no_obs") else
                                    "모델이 근거 부족으로 판단하지 못했어요. 사진이나 설명을 더해 주세요."),
                "observation_refs": obs_refs,
                "detection_refs": sorted({x for e in norm["equipment"] if e["name"] in (call.get("focus") or "")
                                          for x in e.get("detection_ids", [])}),
                "law_candidates": [k for k in it.get("law_keys", []) if k in law_keys],
            }
            if call["candidates"]:
                d["source_rows"] = [x for x in dict.fromkeys(it["source_row_ids"]) if x in row_ids]
                d["llm_rec_rows"] = [x for x in dict.fromkeys(it["recommended_row_ids"]) if x in row_ids]
            else:
                d["llm_measures"] = it.get("recommended_measures", [])
            out.append(d)
        return out

    # -- 3단계
    def judge_signal(self, d: dict, judged_at: str):
        sig = self.cfg["signal"]
        d["judged_at"] = judged_at
        if sig["criteria_mode"] == "strict":
            d.update(signal="off", off_code="criteria_not_set",
                     reason="신호 판단기준이 아직 정해지지 않아 판단하지 못했어요.", basis=None)
            return
        if d["level"] is None:
            d.update(signal="off", off_code=d.get("off_reason_code") or "insufficient_input",
                     reason=d.get("off_reason_text") or "판단 근거가 부족해 판단하지 못했어요.",
                     basis={"method": "three_level", "level": None, "frequency": None, "severity": None,
                            "tolerable": None, "matched_rules": []})
            return
        pc = sig["provisional_criteria"]
        lv = pc["levels"][d["level"]]
        evid = ""
        if d["input_snippets"]:
            evid = f' 현장 입력 "{d["input_snippets"][0][:50]}"을(를) 반영했어요.'
        elif d["matched_equipment"]:
            evid = f' 보유 기기({", ".join(d["matched_equipment"])})에서 나온 항목이며, 현장 상태 확인이 필요해요.'
        reason = f'{sig["reason_prefix_provisional"]}"{lv["text"]}"(안내서 예시)에 해당한다고 보았어요. {d["level_note"]}.{evid}'
        d.update(signal=lv["signal"], off_code=None, reason=reason[:400],
                 basis={"method": pc["method"], "level": d["level"], "frequency": None, "severity": None,
                        "tolerable": pc["tolerable"][d["level"]], "matched_rules": [lv["rule_id"]]})

    def attach_laws(self, d: dict):
        chunk_ids = {c for c, _ in d["chunks"]}
        laws = []
        for key in d["law_candidates"]:
            v = self.kb.laws.get(key)
            if not v:
                self._log("judge_signal", "검증 목록에 없는 법령 후보 제외", item=d["item_key"], law=key)
                continue
            if self.mode == "offline_template" and not (v["_cited_chunks"] & chunk_ids):
                self._log("judge_signal", "검색 청크가 이 조항을 인용하지 않아 제외", item=d["item_key"], law=key)
                continue
            laws.append({
                "law_id": None, "law_name": v["law_name"], "article_no": v["article"],
                "article_title": v["article_title"], "summary": v["gist"][:200], "source_url": v["url"],
                "verified": True, "verified_at": f'{v["retrieved_date"]}T00:00:00+09:00',
            })
        d["laws"] = laws

    def current_candidates(self, d: dict):
        n = self.cfg["measures"]["max_current_candidates"]
        out, seen = [], set()
        for rid, _ in d["rows"]:
            txt = clean_measure_text(self.kb.rows[rid]["source_text"])
            if txt in seen:
                continue
            seen.add(txt)
            out.append({"candidate_id": f"cm-{rid}", "text": txt})
            if len(out) >= n:
                break
        d["current"] = out

    # -- 4단계
    def recommend(self, d: dict):
        want = self.cfg["measures"]["recommended_count"]
        if d["signal"] == "off" or (d["signal"] == "green" and not self.cfg["signal"]["green_recommendations"]):
            d.update(rec_status="not_applicable", rec=[])
            return
        stage = self.cfg["backend"]["llm"].get("measure_stage", "none")
        if self.mode in ("llm", "mock_llm", "replay") and stage != "none" and self.recommend_staged(d, stage):
            return
        if "llm_rec_rows" in d:
            kw = self.cfg["measures"]["control_type_keywords"]
            rec, seen_t = [], set()
            for rid in d["llm_rec_rows"]:
                txt = clean_measure_text(self.kb.rows[rid]["source_text"])
                if txt in seen_t:
                    continue
                seen_t.add(txt)
                rec.append({"measure_id": f"rm-{rid}", "text": txt, "control_type": control_type_of(txt, kw)})
            if len(rec) == want:
                d.update(rec_status="ok", rec=rec)
            else:
                self._log("recommend_measures", "후보 선택 대책 개수 불일치 → failed", item=d["item_key"], count=len(rec))
                d.update(rec_status="failed", rec=[])
            return
        if "llm_measures" in d:
            rec = []
            for i, m in enumerate(d["llm_measures"]):
                if isinstance(m, dict) and m.get("text"):
                    ct = m.get("control_type") if m.get("control_type") in (
                        "elimination_substitution", "engineering", "administrative", "ppe") else None
                    rec.append({"measure_id": f"rm-{d['item_key']}-{i + 1}", "text": str(m["text"])[:120], "control_type": ct})
            if len(rec) == want:
                d.update(rec_status="ok", rec=rec)
            else:
                self._log("recommend_measures", "LLM 추천 대책 개수 불일치 → failed", item=d["item_key"], count=len(rec))
                d.update(rec_status="failed", rec=[])
            return
        # 오프라인: 현재 조치 후보로 쓰지 않은 점검표 행 중 대책 유형이 겹치지 않게 고른다.
        kw = self.cfg["measures"]["control_type_keywords"]
        used = {c["candidate_id"][3:] for c in d["current"]}
        t = d["template"]
        query = (t["rag_query"] if t else d["hazard"]) + " " + d["hazard"]
        sections = t["row_sections"] if t else None
        mk = (t.get("measure_keywords") or []) if t else []

        def allow(rid):
            row = self.kb.rows[rid]
            return ((sections is None or row["source_section"] in sections)
                    and (not mk or any(k in row["source_text"] for k in mk)))

        # 현재 조치 후보와 겹쳐도 된다(설계서 18·20쪽 예시도 '보호구 착용'이 양쪽에 있음). 겹치지 않는 행을 먼저 쓴다.
        found = self.kb.row_index.search(query, 30, allow)
        pool = [x for x in found if x[0] not in used] + [x for x in found if x[0] in used]
        picked, types, texts = [], set(), set()
        for diversify in (True, False):
            for rid, _ in pool:
                if len(picked) >= want:
                    break
                txt = clean_measure_text(self.kb.rows[rid]["source_text"])
                ct = control_type_of(txt, kw)
                if txt in texts or (diversify and ct in types):
                    continue
                picked.append({"measure_id": f"rm-{rid}", "text": txt, "control_type": ct})
                types.add(ct)
                texts.add(txt)
        if len(picked) == want:
            d.update(rec_status="ok", rec=picked)
        else:
            self._log("recommend_measures", "근거 행이 부족해 추천 3개를 만들지 못함 → failed", item=d["item_key"], found=len(picked))
            d.update(rec_status="failed", rec=[])

    def to_item(self, d: dict) -> dict:
        evidence = (list(d["input_refs"]) + list(d.get("source_rows", [])) + [c for c, _ in d["chunks"]]
                    + [r for r, _ in d["rows"]])
        item = {
            "item_key": d["item_key"], "work": d["work"], "location": d["location"], "hazard": d["hazard"],
            "accident_type": d["accident_type"], "cause": d["cause"], "description": d["description"],
            "equipment_refs": d["equipment_refs"], "evidence_refs": list(dict.fromkeys(evidence)),
            "signal": d["signal"], "signal_source": "ai", "signal_reason": d["reason"],
            "model_version": self.model_version, "criteria_version": self.cfg["signal"]["criteria_version_output"],
            "judged_at": d["judged_at"], "off_reason_code": d["off_code"],
            "laws": d["laws"], "current_measure_candidates": d["current"],
            "recommendation_status": d["rec_status"], "recommended_measures": d["rec"],
        }
        if d.get("basis") is not None:
            item["basis"] = d["basis"]
        if self.observations is not None:
            item["observation_refs"] = d.get("observation_refs", [])
            item["detection_refs"] = d.get("detection_refs", [])
        return item

    def assemble(self, req_id: str, items: list[dict]) -> dict:
        warnings = list(self.warnings)
        if self.cfg["signal"]["criteria_mode"] != "strict":
            warnings.append("[임시 기준] 신호는 안내서 3단계 판단 기준 예시를 임시로 적용한 결과입니다. 팀·전문가가 기준(C1~C8)을 정하기 전에는 실제 판정으로 쓰지 마세요.")
        if self.mode == "offline_template":
            warnings.append("[오프라인 템플릿] 모델 없이 RAG 검색과 임시 템플릿으로 만든 초안입니다.")
        resp = {"request_id": req_id, "call": "s04_draft", "status": "ok", "model_version": self.model_version,
                "criteria_version": self.cfg["signal"]["criteria_version_output"], "generated_at": now_kst(),
                "items": items, "warnings": warnings}
        if self.observations is not None:
            resp["observations"] = [{k: v for k, v in o.items() if not k.startswith("_") and k != "author_review"}
                                    for o in self.observations]
            resp["analysis_stages"] = [
                {"stage": "detect_equipment", "model_version": "oracle_label(평가셋 라벨, AI 보조·검수 전)", "source": "oracle_label"},
                {"stage": "observe_state", "model_version": self.observation_stage_version or "미확인", "source": "vlm"},
                {"stage": "generate_items", "model_version": self.model_version, "source": "llm"}]
            warnings.append("[탐지 결과 대용] 기기 탐지는 평가셋 라벨(oracle_label)을 넣은 것입니다. 탐지 모델 결과가 아닙니다.")
        self._set_status(resp)
        return resp

    @staticmethod
    def _set_status(resp: dict):
        partial = any(i["signal"] == "off" or i["recommendation_status"] == "failed" for i in resp["items"])
        resp["status"] = "partial" if partial else "ok"

    @property
    def rv(self):
        """응답 검증기: 사진 분석(v2) 결과가 있으면 contract_v2, 아니면 v1 계약."""
        return self.validator_v2 if self.observations is not None else self.validator

    def validate_and_repair(self, resp: dict) -> dict:
        if not self.validator.available:
            self._log("recommend_measures", "스키마 검증 미실행", reason=self.validator.reason)
            resp["warnings"].append("스키마 검증을 실행하지 못했습니다(jsonschema 미설치).")
            return resp
        errs = self.rv.errors("s04_draft.response.schema.json", resp)
        if not errs:
            self._log("recommend_measures", "응답 스키마 통과")
            return resp
        self._log("recommend_measures", "응답 스키마 위반 → 항목별 수리", errors=errs[:20])
        for i, item in enumerate(resp["items"]):
            ie = self.rv.errors("common.schema.json", item, "/$defs/RiskItemAI")
            if ie:
                allowed = ("item_key", "work", "location", "hazard", "accident_type", "cause", "description",
                           "equipment_refs", "evidence_refs", "signal_source", "model_version", "criteria_version",
                           "judged_at", "laws", "current_measure_candidates", "observation_refs", "detection_refs")
                fixed = {k: copy.deepcopy(item[k]) for k in allowed if k in item}  # 사용자 필드 등 계약 밖 키는 버린다
                fixed.update(signal="off", off_reason_code="invalid_output", recommendation_status="not_applicable",
                             recommended_measures=[], laws=[i_ for i_ in item.get("laws", []) if i_.get("verified") is True],
                             signal_reason="AI 응답 형식이 올바르지 않아 판단하지 못했어요. 다시 판단해 주세요.")
                fixed.pop("basis", None)
                resp["items"][i] = fixed
                self._log("recommend_measures", "항목을 off(invalid_output)로 수리", item=item.get("item_key"), errors=ie[:5])
        self._set_status(resp)
        errs = self.rv.errors("s04_draft.response.schema.json", resp)
        if errs:
            self._log("recommend_measures", "수리 후에도 스키마 위반", errors=errs[:20])
        return resp
