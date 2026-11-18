"""RAG 근거를 별도 문헌 필드로 전달한다. 현장 관찰 근거로 승격하지 않는다."""
import copy
import hashlib
import json
from .contracts import require

def evidence_by_scenario(response, links, scenario_ids, equipment_ids):
    result = {sid: [] for sid in scenario_ids}
    for candidate in response.get("candidates", []):
        codes = [eq + ":" + candidate["hazard_code"] for eq in candidate["equipment_ids"]
                 if eq in equipment_ids]
        targets = {sid for key in codes for sid in links.get(key, [])}
        source_ids = candidate.get("source_ids", [])
        texts = candidate.get("hazard_texts", [])
        require(isinstance(source_ids, list) and all(isinstance(s, str) and s and not s.startswith("CASE-") for s in source_ids),
                "invalid RAG source identifiers")
        require(isinstance(texts, list) and all(isinstance(t, str) and t.strip() for t in texts),
                "invalid RAG evidence text")
        if not source_ids or not texts:
            continue
        record = dict(equipment_ids=copy.deepcopy(candidate["equipment_ids"]),
                      hazard_code=candidate["hazard_code"], hazard_texts=copy.deepcopy(texts),
                      source_ids=copy.deepcopy(source_ids), provenance_granularity="hazard_group",
                      data_version=response.get("data_version"), index_sha256=response.get("index_sha256"))
        if "source_evidence" in candidate:
            details = candidate["source_evidence"]
            require(isinstance(details, list) and all(
                d["source_id"] in source_ids and d["hazard_text"] in texts for d in details),
                "source detail does not match retrieved evidence")
            record["source_evidence"] = copy.deepcopy(details)
            record["provenance_granularity"] = "source_link_row"
        record["evidence_id"] = "RAG-" + hashlib.sha256(
            json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        for sid in targets:
            require(sid in result, "RAG evidence outside selected scenarios")
            if record not in result[sid]:
                result[sid].append(copy.deepcopy(record))
    return result

def attach_document_evidence(rendered, evidence):
    out = copy.deepcopy(rendered)
    for row in out["rows"]:
        row["document_evidence"] = copy.deepcopy(evidence.get(row["scenario_id"], []))
        from .explanations import document_summaries
        row['document_summaries'] = document_summaries(row['document_evidence'])
    return out

