"""카탈로그 직접 매핑과 선택적 기존 RAG 함수 연결. 외부 원문을 계약에 혼입하지 않는다."""
import copy
import json
import re
from pathlib import Path
from .catalog import catalog_index
from .contracts import schema, require

MAPPINGS = json.loads((Path(__file__).parent/"mappings/catalog_links.json").read_text(encoding="utf-8"))

def _positive(text, term):
    # 명시적 부재/미사용의 최소 반례. 복잡한 부정·상충 의미는 추출 단계에서 처리한다.
    for sentence in re.split(r"[.!?\n]", text):
        if term in sentence:
            tail = sentence[sentence.index(term)+len(term):]
            if not re.search(r"^.{0,12}(없|미사용|사용하지 않|쓰지 않)", tail):
                return True
    return False

def retrieve_with_evidence(context, catalog_snapshot, *, rag_provider=None, rag_links=None, legal_registry=None):
    schema("input", context)
    require(len({m["id"] for m in context["media"]}) == len(context["media"]), "duplicate media")
    require(len(set(context["equipment_ids"])) == len(context["equipment_ids"]), "duplicate equipment")
    catalog = catalog_index(catalog_snapshot)
    selected = set()
    unmatched = []
    trace = {"retrieval_mode": "catalog", "rag_response": None}
    for eq in context["equipment_ids"]:
        links = MAPPINGS["equipment"].get(eq, [])
        selected.update(links)
        if not links:
            unmatched.append("기기 매핑 없음: " + eq)
    for media in context["media"]:
        if media["kind"] not in ("text", "voice_transcript"):
            continue
        hits = {sid for sid, terms in MAPPINGS["terms"].items()
                if any(_positive(media["text"], term) for term in terms)}
        selected.update(hits)
        if not hits:
            unmatched.append("검색어 매핑 없음: " + media["id"])
    if rag_provider is not None and context["equipment_ids"]:
        # 기존 services.rag_retrieval.candidates를 주입할 수 있다. 오류를 정상 0건으로 은폐하지 않는다.
        response = rag_provider(context["equipment_ids"], k=None)
        require(isinstance(response, dict) and isinstance(response.get("candidates"), list), "invalid RAG response")
        trace = {"retrieval_mode": "catalog+rag", "rag_response": copy.deepcopy(response)}
        for candidate in response["candidates"]:
            require(isinstance(candidate.get("equipment_ids"), list)
                    and isinstance(candidate.get("hazard_code"), str), "invalid RAG candidate")
            for eq in candidate["equipment_ids"]:
                require(eq in context["equipment_ids"], "RAG equipment outside input")
                key = eq + ":" + candidate["hazard_code"]
                links = (rag_links or {}).get(key, [])
                selected.update(links)
                if not links:
                    unmatched.append("RAG 시나리오 매핑 없음: " + key)
    require(selected <= catalog.keys(), "mapping scenario outside catalog")
    candidates = []
    for sid in sorted(selected):
        refs = copy.deepcopy(catalog[sid].get("source_refs", [])[:2])
        laws = [{"legal_id": ref["legal_id"], "url": ref["url"]} for ref in (legal_registry or [])
                if sid in ref["scenario_ids"]][:2]
        candidates.append(dict(scenario_id=sid, source_refs=refs, legal_refs=laws,
                               retrieval_status="matched" if refs or laws else "no_evidence"))
    bundle = dict(contract_version="assessment-authoring-1", candidates=candidates,
                  unmatched=list(dict.fromkeys(unmatched)))
    schema("retrieval", bundle)
    return bundle, trace

def retrieve_evidence(context, catalog_snapshot, **kwargs):
    return retrieve_with_evidence(context, catalog_snapshot, **kwargs)[0]

def candidate_batches(bundle, size=3):
    require(type(size) is int and size > 0, "invalid batch size")
    return [dict(contract_version=bundle["contract_version"],
                 candidates=copy.deepcopy(bundle["candidates"][start:start+size]),
                 unmatched=copy.deepcopy(bundle["unmatched"]))
            for start in range(0, len(bundle["candidates"]), size)]

