"""위험성평가 추출 어댑터: InputBundle + RetrievalBundle + 카탈로그 → AnalysisBundle.

계약: contracts/assessment_authoring/v1 (assessment-authoring-1).
- 검색 후보를 배치(기본 3개)로 나누어 배치당 구조화 호출 1회를 수행한다.
- 모델 응답의 JSON·스키마·ID·직접 인용을 확인한다. 실패하면 ExtractionError를 던진다.
  잘못된 supported를 unknown으로 바꾸어 성공시키지 않는다.
- 질문·등급을 생성하지 않는다. 위험도 계산·평가표 조립·저장은 compose_assessment 담당이다.

모델 호출 함수는 call_model 인자로 주입한다. 테스트는 mock을 넣고,
서비스는 기본값 exaone_chat(기존 backend EXAONE 연결)을 사용한다.
표준 라이브러리만 사용한다(exaone_chat 내부의 backend·httpx import 제외).
"""
import hashlib
import json
import runpy
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "contracts/assessment_authoring/v1"
PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"
CONTRACT_VERSION = "assessment-authoring-1"
CATALOG_VERSION = "CATALOG-MVP-1.1"
PROMPT_VERSION = "assessment-extraction-2"  # 2: 문장 전체 인용·탐지만 있는 후보 제외 (계약 5a882f6)
DEFAULT_BATCH_SIZE = 3
QUOTE_KINDS = ("text", "voice_transcript")
MAX_RESPONSE_BYTES = 2_000_000

# 공통 계약 검사기의 스키마 검사 함수를 재사용한다(별도 구현으로 갈라지지 않게).
_CONTRACT = runpy.run_path(str(CONTRACT / "validate.py"))
_check = _CONTRACT["check"]
_whole_sentence = _CONTRACT["whole_sentence"]  # 문장 일부 인용(부정·조건 누락) 차단
_SCHEMAS = {name: _CONTRACT["read"]("schemas/" + name + ".schema.json") for name in ("input", "retrieval", "analysis")}


class ExtractionError(Exception):
    """성공 Bundle 대신 기존 오류 경로로 반환할 추출 실패.

    code: INPUT_INVALID | MODEL_REQUEST_FAILED | MODEL_OUTPUT_TRUNCATED |
          MODEL_OUTPUT_INCOMPLETE | MODEL_OUTPUT_INVALID_JSON | MODEL_OUTPUT_SCHEMA |
          MODEL_OUTPUT_REFERENCE
    detail에는 모델 원문을 넣지 않는다.
    """

    def __init__(self, code, detail, batch=None):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.batch = batch


@dataclass
class ExtractionResult:
    analysis: dict
    runs: list = field(default_factory=list)  # 배치별 모델·토큰·종료 사유 기록
    # 검색 후보 중 작업 근거가 없어 analysis에서 빠진 ID. 담당자 작업 확인 대상으로 보존한다.
    work_review_candidates: list = field(default_factory=list)


def load_system_prompt():
    text = PROMPT_PATH.read_text(encoding="utf-8-sig")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 입력 확인

def _validate_inputs(context, retrieval_bundle, catalog_snapshot):
    try:
        _check(context, _SCHEMAS["input"])
        _check(retrieval_bundle, _SCHEMAS["retrieval"])
    except ValueError as e:
        raise ExtractionError("INPUT_INVALID", str(e)) from None
    if not isinstance(catalog_snapshot, dict) or catalog_snapshot.get("policy_version") != CATALOG_VERSION:
        raise ExtractionError("INPUT_INVALID", "catalog policy_version")
    catalog = {s["id"]: s for s in catalog_snapshot.get("scenarios", [])}
    ids = [m["id"] for m in context["media"]]
    if len(ids) != len(set(ids)):
        raise ExtractionError("INPUT_INVALID", "duplicate media id")
    retrieved = [c["scenario_id"] for c in retrieval_bundle["candidates"]]
    if len(retrieved) != len(set(retrieved)):
        raise ExtractionError("INPUT_INVALID", "duplicate retrieval candidate")
    missing = [sid for sid in retrieved if sid not in catalog]
    if missing:
        raise ExtractionError("INPUT_INVALID", "scenario not in catalog: " + ", ".join(missing))
    return catalog


# ---------------------------------------------------------------- 메시지 구성

def build_messages(context, candidates, catalog, system_prompt):
    """배치 하나의 모델 메시지. 등급·심각도·개선대책(plan_text)은 넘기지 않는다."""
    scenarios = []
    for c in candidates:
        s = catalog[c["scenario_id"]]
        scenarios.append({
            "scenario_id": s["id"],
            "title": s["title"],
            "task": s["task"],
            "scenario": s["scenario"],
            "applicability_note": s.get("applicability_note", ""),
            "controls": [{"control_id": x["id"], "critical": x["critical"], "text": x["current_text"]} for x in s["controls"]],
        })
    evidence = [{"scenario_id": c["scenario_id"], "retrieval_status": c["retrieval_status"],
                 "source_refs": c["source_refs"], "legal_refs": c["legal_refs"]} for c in candidates]
    payload = {
        "input": {"media": context["media"], "equipment_ids": context["equipment_ids"]},
        "candidate_scenarios": scenarios,
        "retrieved_evidence": evidence,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


# ---------------------------------------------------------------- 응답 파싱·검사

def parse_model_response(response, batch_ids):
    """call_model 반환값 {'content','finish_reason',...}을 dict로 파싱한다."""
    if not isinstance(response, dict):
        raise ExtractionError("MODEL_REQUEST_FAILED", "response is not an object", batch_ids)
    finish = response.get("finish_reason")
    if finish == "length":
        raise ExtractionError("MODEL_OUTPUT_TRUNCATED", "finish_reason=length", batch_ids)
    if finish not in ("stop", None):
        raise ExtractionError("MODEL_OUTPUT_INCOMPLETE", "finish_reason=" + str(finish), batch_ids)
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ExtractionError("MODEL_OUTPUT_INVALID_JSON", "empty content", batch_ids)
    text = content.strip()
    if text.startswith("```"):  # 코드 울타리 한 겹만 허용한다.
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ExtractionError("MODEL_OUTPUT_INVALID_JSON", "unterminated code fence", batch_ids)
        text = "\n".join(lines[1:-1])
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError("MODEL_OUTPUT_INVALID_JSON", f"line {e.lineno} col {e.colno}", batch_ids) from None
    if not isinstance(data, dict):
        raise ExtractionError("MODEL_OUTPUT_INVALID_JSON", "top level is not an object", batch_ids)
    return data


def check_batch_output(data, context, batch_ids, catalog):
    """스키마·등록 ID·직접 인용을 확인한다. 위반은 모두 오류다."""
    data = dict(data)
    data.setdefault("contract_version", CONTRACT_VERSION)
    try:
        _check(data, _SCHEMAS["analysis"])  # 추가 필드(grade 등)·questions≠[] 차단
    except ValueError as e:
        raise ExtractionError("MODEL_OUTPUT_SCHEMA", str(e), batch_ids) from None

    def fail(detail):
        raise ExtractionError("MODEL_OUTPUT_REFERENCE", detail, batch_ids)

    media = {m["id"]: m for m in context["media"]}
    seen = set()
    for n, c in enumerate(data["candidates"]):
        where = f"candidates[{n}]"
        sid = c["scenario_id"]
        if sid not in batch_ids:
            fail(where + ": scenario outside batch")
        if sid in seen:
            fail(where + ": duplicate scenario")
        seen.add(sid)
        quotes = set()
        for e in c["evidence"]:
            if e["media_id"] not in media:
                fail(where + ": unknown media_id")
            if e["statement"] not in media[e["media_id"]]["text"]:
                fail(where + ": evidence statement is not a direct quote")
            key = (e["media_id"], e["statement"])
            if key in quotes:
                fail(where + ": duplicate evidence")
            quotes.add(key)
        # 작업 근거: 텍스트·전사의 완전한 문장 인용이 최소 1개. 탐지·보유만으로는 행을 만들지 않는다.
        if not any(media[e["media_id"]]["kind"] in QUOTE_KINDS
                   and _whole_sentence(e["statement"], media[e["media_id"]]["text"]) for e in c["evidence"]):
            fail(where + ": work needs a complete text or voice quote")
        known = {x["id"] for x in catalog[sid]["controls"]}
        controls = set()
        for k, e in enumerate(c["control_evidence"]):
            at = f"{where}.control_evidence[{k}]"
            if e["control_id"] not in known:
                fail(at + ": control not in scenario")
            if e["control_id"] in controls:
                fail(at + ": duplicate control")
            controls.add(e["control_id"])
            refs = e["evidence_refs"]
            if len(refs) != len(set(refs)) or not set(refs) <= media.keys():
                fail(at + ": invalid evidence_refs")
            if e["state"] == "unknown":
                continue
            # supported/not_effective: 텍스트·전사 원문의 직접 인용만 인정한다.
            if not refs:
                fail(at + ": missing evidence_refs")
            if any(media[r]["kind"] not in QUOTE_KINDS for r in refs):
                fail(at + ": detection/inventory cannot support control state")
            if not any(_whole_sentence(e["statement"], media[r]["text"]) for r in refs):
                fail(at + ": control statement is not a whole input sentence")
    return data


# ---------------------------------------------------------------- 실행

def run_extraction(context, retrieval_bundle, catalog_snapshot, call_model=None, batch_size=DEFAULT_BATCH_SIZE):
    """extract_analysis와 같고, 배치별 실행 기록(runs)을 함께 반환한다."""
    if batch_size < 1:
        raise ValueError("batch_size")
    catalog = _validate_inputs(context, retrieval_bundle, catalog_snapshot)
    call_model = call_model or exaone_chat
    system_prompt, prompt_sha = load_system_prompt()
    candidates_in = retrieval_bundle["candidates"]
    merged, unmatched, runs = [], list(retrieval_bundle["unmatched"]), []
    for start in range(0, len(candidates_in), batch_size):
        batch = candidates_in[start:start + batch_size]
        batch_ids = [c["scenario_id"] for c in batch]
        messages = build_messages(context, batch, catalog, system_prompt)
        response = call_model(messages)
        data = check_batch_output(parse_model_response(response, batch_ids), context, batch_ids, catalog)
        merged.extend(data["candidates"])
        unmatched.extend(data["unmatched_risks"])
        runs.append({
            "scenario_ids": batch_ids,
            "model": response.get("model"),
            "max_tokens": response.get("max_tokens"),
            "finish_reason": response.get("finish_reason"),
            "usage": response.get("usage"),
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": prompt_sha,
        })
    ids = [c["scenario_id"] for c in merged]
    if len(ids) != len(set(ids)):
        raise ExtractionError("MODEL_OUTPUT_REFERENCE", "duplicate scenario across batches")
    analysis = {
        "contract_version": CONTRACT_VERSION,
        "candidates": merged,
        "unmatched_risks": list(dict.fromkeys(unmatched)),
    }
    _check(analysis, _SCHEMAS["analysis"])
    review = [c["scenario_id"] for c in candidates_in if c["scenario_id"] not in set(ids)]
    return ExtractionResult(analysis=analysis, runs=runs, work_review_candidates=review)


def extract_analysis(context, retrieval_bundle, catalog_snapshot, call_model=None, batch_size=DEFAULT_BATCH_SIZE):
    """AnalysisBundle(analysis.schema.json)을 반환한다. 실패는 ExtractionError."""
    return run_extraction(context, retrieval_bundle, catalog_snapshot, call_model, batch_size).analysis


# ---------------------------------------------------------------- 기존 EXAONE 연결

def exaone_chat(messages):
    """기존 backend 연결(services.catalog_ai)의 설정·인증·토큰 한도를 그대로 사용한다.

    backend 프로세스(작업 디렉터리 backend/)에서 호출한다는 전제다.
    SAFET_AI_BASE_URL(또는 SAFET_AI_GATEWAY_URL)·SAFET_AI_MODEL·SAFET_AI_MAX_TOKENS를 따른다.
    실제 모델 검사 전에는 이 함수를 호출하지 않는다(mock 검사만 수행).
    """
    import httpx
    from services import catalog_ai as svc

    base, model, tokens = svc.configuration()
    headers = svc.model_headers()
    tokens = svc.output_budget(base, model, messages, headers, tokens)  # 입력+출력 4096 이내
    payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": tokens,
               "response_format": {"type": "json_object"}}
    try:
        with httpx.Client(timeout=httpx.Timeout(180, connect=10), follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", base + "/chat/completions", json=payload, headers=headers) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ValueError("response too large")
        body = json.loads(raw)
        choice = body["choices"][0]
        return {"content": choice["message"]["content"], "finish_reason": choice.get("finish_reason"),
                "usage": body.get("usage"), "model": model, "max_tokens": tokens}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        raise ExtractionError("MODEL_REQUEST_FAILED", "chat/completions request failed") from None
