"""카탈로그 직접 매핑과 선택적 기존 RAG 함수 연결. 외부 원문을 계약에 혼입하지 않는다."""
import copy
import json
import re
from pathlib import Path
from .catalog import catalog_index
from .contracts import schema, require

MAPPINGS = json.loads((Path(__file__).parent/"mappings/catalog_links.json").read_text(encoding="utf-8"))

# Exclude only an explicitly absent device or unused task immediately after the term.
_UNUSED = re.compile(r"^(?:기|\s*작업)?(?:은|는|이|가|을|를)?\s*"
                     r"(?:없(?:다|습니다|어요|음|고|으며)|미사용|사용하지\s*않|하지\s*않|쓰지\s*않|안\s*(?:함|합니다|해요|한다|사용|씁니다|써요|쓴다|씀))")


# Only a direct denial of frying work (or use of the fryer) establishes non-applicability.
# Negated hazards and controls, such as a missing temperature controller, are not work denials.
_FRY_WORK_DENIAL = re.compile(
    r"(?:^|[.!?。！？\n])\s*(?:(?:현재|오늘|지금|요즘|이번\s*주|평소)(?:은|는|에는)?\s+)?"
    r"(?:[0-9가-힣]+(?:[ \t]+[0-9가-힣]+)*에서(?:는)?[ \t]+)?"
    r"(?P<work>튀김(?:\s*(?:작업|조리))?(?:은|는|을|를)?\s*"
    r"(?:안\s*(?:합니다|해요|한다|함)|하지\s*않(?:습니다|아요|는다|음))"
    r"|(?:(?:전기|가스)[ \t]*)?튀김기(?:는|를|가)?\s*"
    r"(?:안\s*(?:씁니다|써요|쓴다|씀)|(?:쓰지|사용하지|가동하지)\s*않(?:습니다|아요|는다|음)))"
    r"\s*(?=[.!?。！？\n]|$)"
)


def text_candidates(media, diagnostics):
    hits = set()
    # 장소 표현 앞에 나오는 작업 언급은 부정 범위에서 제외한다.
    denied_spans = [m.span("work") for m in _FRY_WORK_DENIAL.finditer(media["text"])]
    for sid, terms in MAPPINGS["terms"].items():
        for term in terms:
            for match in re.finditer(re.escape(term), media["text"]):
                fryer_denied = sid == "FRY" and any(start <= match.start() < end for start, end in denied_spans)
                if fryer_denied or _UNUSED.match(media["text"][match.end():]):
                    diagnostics.append(f"명시적 부정: {media['id']} {sid} {term}")
                else:
                    hits.add(sid)
    return hits, bool(denied_spans)


def work_supported(scenario, statement):
    """True when a work statement names the scenario's work or equipment without negating it."""
    if scenario["id"] == "FRY":
        return not _FRY_WORK_DENIAL.search(statement) and any(
            _positive(statement, term) for term in MAPPINGS["terms"]["FRY"]
        )
    terms = {part.strip() for keyword in scenario.get("keywords", [])
             for part in keyword.split("·") if part.strip()}
    return any(_positive(statement, term) for term in terms)


def _positive(text, term):
    return any(not _UNUSED.match(text[m.end():]) for m in re.finditer(re.escape(term), text))


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

