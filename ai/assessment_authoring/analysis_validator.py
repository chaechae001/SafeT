"""모델 결과의 계약·소속·입력 인용 검증 및 누락 조치 정규화."""
import copy
import json
from .contracts import check, read, require
from .catalog import catalog_index

def validate_analysis(i, r, a, catalog_snapshot, legal_registry=None):
    CAT = catalog_index(catalog_snapshot)
    a = copy.deepcopy(a)
    for name, value in (("input", i), ("retrieval", r), ("analysis", a)):
        check(value, read("schemas/" + name + ".schema.json"))
    media = {m["id"]: m for m in i["media"]}
    require(len(media) == len(i["media"]), "duplicate media")
    require(len(set(i["equipment_ids"])) == len(i["equipment_ids"]), "duplicate equipment")
    registry = [] if legal_registry is None else legal_registry
    retrieved = [c["scenario_id"] for c in r["candidates"]]
    require(len(retrieved) == len(set(retrieved)), "duplicate retrieval")
    for c in r["candidates"]:
        require(c["scenario_id"] in CAT, "unknown scenario")
        refs = c["source_refs"]
        require(all(ref in CAT[c["scenario_id"]]["source_refs"] for ref in refs), "unverified source")
        require(len({json.dumps(ref, sort_keys=True) for ref in refs}) == len(refs), "duplicate source")
        for ref in c["legal_refs"]:
            require(any(ref["legal_id"] == trusted["legal_id"] and ref["url"] == trusted["url"] and c["scenario_id"] in trusted["scenario_ids"] for trusted in registry), "unverified legal ref")
        expected = "matched" if refs or c["legal_refs"] else "no_evidence"
        require(c["retrieval_status"] == expected, "retrieval status mismatch")
    ids = [c["scenario_id"] for c in a["candidates"]]
    require(len(ids) == len(set(ids)), "duplicate candidate")
    for c in a["candidates"]:
        require(c["scenario_id"] in retrieved, "candidate outside retrieval")
        for e in c["evidence"]:
            require(e["media_id"] in media, "unknown media")
            require(e["statement"] in media[e["media_id"]]["text"], "scenario quote not in input")
        scenario = CAT[c["scenario_id"]]
        known = {x["id"] for x in scenario["controls"]}
        critical = {x["id"] for x in scenario["controls"] if x["critical"]}
        seen, supported = set(), set()
        for e in c["control_evidence"]:
            require(e["control_id"] in known and e["control_id"] not in seen, "invalid/duplicate control")
            seen.add(e["control_id"])
            require(set(e["evidence_refs"]) <= media.keys(), "unknown media")
            require(len(e["evidence_refs"]) == len(set(e["evidence_refs"])), "duplicate evidence")
            if e["state"] != "unknown":
                require(bool(e["evidence_refs"]), "missing control evidence")
                require(any(media[mid]["kind"] in ("text", "voice_transcript") and e["statement"] in media[mid]["text"] for mid in e["evidence_refs"]), "control requires direct input quote")
            if e["state"] == "supported":
                supported.add(e["control_id"])
        existing = {e["control_id"]: e for e in c["control_evidence"]}
        c["control_evidence"] = [existing.get(control["id"], dict(control_id=control["id"],
            state="unknown", evidence_refs=[], statement="입력에서 확인되지 않음"))
            for control in scenario["controls"]]
    return a
