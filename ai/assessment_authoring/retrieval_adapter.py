"""카탈로그 직접 매핑과 선택적 기존 RAG 함수 연결. 외부 원문을 계약에 혼입하지 않는다."""
import copy
import json
import re
from pathlib import Path
from .catalog import catalog_index
from .contracts import schema, require
from .negation import denied

MAPPINGS = json.loads((Path(__file__).parent/"mappings/catalog_links.json").read_text(encoding="utf-8"))

# 튀김 작업 자체를 가리키는 기준어. 이 단어가 미사용으로 진술되면 FRY를 해당 없음 후보로 둔다.
# "기름 교체"처럼 작업 일부를 하지 않는다는 진술은 튀김 작업 미사용이 아니다.
_FRY_WORK_TERMS = ("튀김", "튀기", "튀깁", "튀겨")


# 어간만 적은 기준어 중 다른 동사의 명사형과 겹치는 것은 어미가 바로 붙을 때만 인정한다.
# "튀기"는 "튀기고·튀기는·튀기기"(튀기다)만 인정하고, "소스가 튀기 시작"(튀다)은 제외한다.
_TERM_PATTERNS = {"튀기": r"튀기(?=[가-힣])"}


def _term_matches(term, text):
    return re.finditer(_TERM_PATTERNS.get(term, re.escape(term)), text)


def _affirmed(sid, text, terms, diagnostics=None, media_id=""):
    """True when a term appears at least once without being stated as unused or absent."""
    found = False
    for term in terms:
        for match in _term_matches(term, text):
            if denied(text, *match.span()):
                if diagnostics is not None:
                    diagnostics.append(f"명시적 부정: {media_id} {sid} {term}")
            else:
                found = True
    return found


def _fry_work_denied(text):
    return any(denied(text, *m.span()) for term in _FRY_WORK_TERMS for m in _term_matches(term, text))


def text_candidates(media, diagnostics):
    hits = {sid for sid, terms in MAPPINGS["terms"].items()
            if _affirmed(sid, media["text"], terms, diagnostics, media["id"])}
    return hits, _fry_work_denied(media["text"])


def _name_parts(name):
    return [part.strip() for part in re.split(r"[·()]", name) if part.strip()]


def _equipment_names():
    """시나리오에 연결된 기기의 표준명·동의어(기기 마스터 v1)."""
    from .contracts import ROOT, read
    source = ROOT / read("reference/SOURCE.json")["equipment_source_path"]
    names = {}
    for row in json.loads(source.read_text(encoding="utf-8-sig"))["equipment"]:
        for sid in MAPPINGS["equipment"].get(row["equipment_id"], []):
            names.setdefault(sid, set()).update(_name_parts(row["standard_name"]) + row["synonyms"])
    return names


_EQUIPMENT_NAMES = _equipment_names()


def work_terms(scenario):
    """작업 근거로 인정하는 단어: 매핑 기준어, 카탈로그 작업명, 연결 기기의 이름.

    카탈로그 keywords는 위험·조치 단어("가열", "세척", "문 개방")를 함께 담고 있어
    무관한 작업 문장도 근거로 통과시키므로 쓰지 않는다.
    """
    sid = scenario["id"]
    return {*MAPPINGS["terms"].get(sid, []), scenario["task"], *_EQUIPMENT_NAMES.get(sid, ())}


def work_supported(scenario, statement):
    """True when a work statement names the scenario's work or equipment without negating it."""
    return _affirmed(scenario["id"], statement, work_terms(scenario))


def _positive(text, term):
    return any(not denied(text, *m.span()) for m in _term_matches(term, text))


def retrieve_with_evidence(context, catalog_snapshot, *, rag_provider=None, rag_links=None, legal_registry=None):
    schema("input", context)
    require(len({m["id"] for m in context["media"]}) == len(context["media"]), "duplicate media")
    require(len(set(context["equipment_ids"])) == len(context["equipment_ids"]), "duplicate equipment")
    catalog = catalog_index(catalog_snapshot)
    equipment_candidates = set()
    text_matches = set()
    denied_work = set()
    diagnostics = []
    trace = {"retrieval_mode": "catalog", "rag_response": None, "diagnostics": diagnostics}
    for eq in context["equipment_ids"]:
        links = MAPPINGS["equipment"].get(eq, [])
        equipment_candidates.update(links)
        if not links:
            diagnostics.append("기기 매핑 없음: " + eq)
    for media in context["media"]:
        if media["kind"] not in ("text", "voice_transcript"):
            continue
        hits, fryer_denied = text_candidates(media, diagnostics)
        text_matches.update(hits)
        if fryer_denied:
            denied_work.add("FRY")
        if not hits:
            diagnostics.append("검색어 매핑 없음: " + media["id"])
    if rag_provider is not None and context["equipment_ids"]:
        # 기존 services.rag_retrieval.candidates를 주입할 수 있다. 오류를 정상 0건으로 은폐하지 않는다.
        response = rag_provider(context["equipment_ids"], k=None)
        require(isinstance(response, dict) and isinstance(response.get("candidates"), list), "invalid RAG response")
        require(response.get("enabled") is not False, "RAG is disabled; not an empty search result")
        trace.update(retrieval_mode="catalog+rag", rag_response=copy.deepcopy(response))
        for candidate in response["candidates"]:
            require(isinstance(candidate.get("equipment_ids"), list)
                    and isinstance(candidate.get("hazard_code"), str), "invalid RAG candidate")
            for eq in candidate["equipment_ids"]:
                require(eq in context["equipment_ids"], "RAG equipment outside input")
                key = eq + ":" + candidate["hazard_code"]
                links = (rag_links or {}).get(key, [])
                equipment_candidates.update(links)
                if not links:
                    diagnostics.append("RAG 시나리오 매핑 없음: " + key)
    selected = equipment_candidates | text_matches
    # When input contains both positive and negative indications, retain the candidate for review.
    not_applicable = denied_work - text_matches
    trace["equipment_candidates"] = sorted(equipment_candidates)
    trace["text_candidates"] = sorted(text_matches)
    trace["not_applicable_candidates"] = sorted(not_applicable)
    selected -= not_applicable
    require(selected <= catalog.keys(), "mapping scenario outside catalog")
    candidates = []
    for sid in sorted(selected):
        refs = copy.deepcopy(catalog[sid].get("source_refs", [])[:2])
        laws = [{"legal_id": ref["legal_id"], "url": ref["url"]} for ref in (legal_registry or [])
                if sid in ref["scenario_ids"]][:2]
        candidates.append(dict(scenario_id=sid, source_refs=refs, legal_refs=laws,
                               retrieval_status="matched" if refs or laws else "no_evidence"))
    bundle = dict(contract_version="assessment-authoring-1", candidates=candidates,
                  unmatched=[])
    schema("retrieval", bundle)
    from .document_evidence import evidence_by_scenario
    trace["scenario_evidence"] = evidence_by_scenario(
        trace["rag_response"] or {}, {k:[sid for sid in v if sid not in not_applicable] for k,v in (rag_links or {}).items()}, selected, context["equipment_ids"])
    return bundle, trace

def retrieve_evidence(context, catalog_snapshot, **kwargs):
    return retrieve_with_evidence(context, catalog_snapshot, **kwargs)[0]

def candidate_batches(bundle, size=3):
    require(type(size) is int and size > 0, "invalid batch size")
    return [dict(contract_version=bundle["contract_version"],
                 candidates=copy.deepcopy(bundle["candidates"][start:start+size]),
                 unmatched=copy.deepcopy(bundle["unmatched"]))
            for start in range(0, len(bundle["candidates"]), size)]

