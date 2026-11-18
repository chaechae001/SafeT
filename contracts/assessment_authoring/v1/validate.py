"""Contract examples only; Python 3.11+, no dependencies or model calls.

Checks the JSON Schema subset used by this kit, references and calculation.
This is not a general JSON Schema validator or a semantic evidence verifier.
"""
import copy
import hashlib
import json
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def check(value, schema, path="$"):
    if "const" in schema:
        require(value == schema["const"], path + ": const")
    if "enum" in schema:
        require(value in schema["enum"], path + ": enum")
    kind = schema.get("type")
    if kind == "object":
        require(isinstance(value, dict), path + ": object")
        require(set(schema.get("required", [])) <= value.keys(), path + ": required")
        props = schema["properties"]
        if schema.get("additionalProperties") is False:
            require(value.keys() <= props.keys(), path + ": extra field")
        for key, child in value.items():
            if key in props:
                check(child, props[key], path + "." + key)
    elif kind == "array":
        require(isinstance(value, list), path + ": array")
        require(schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100000), path + ": length")
        for n, child in enumerate(value):
            check(child, schema["items"], path + "[" + str(n) + "]")
    elif kind == "string":
        require(isinstance(value, str) and len(value.strip()) >= schema.get("minLength", 0), path + ": string")
    elif kind == "integer":
        require(type(value) is int and value >= schema.get("minimum", -100000), path + ": integer")


CAT = {s["id"]: s for s in read("reference/catalog.json")["scenarios"]}
POLICY = runpy.run_path(str(ROOT / "reference/risk_policy.py"))


def verify_sources():
    source = read("reference/SOURCE.json")
    require(len(source["base_commit"]) == 40 and all(c in "0123456789abcdef" for c in source["base_commit"]), "source commit")
    for name, expected in source["reference_sha256"].items():
        raw = (ROOT / "reference" / name).read_bytes().replace(b"\r\n", b"\n")
        require(hashlib.sha256(raw).hexdigest() == expected, "snapshot changed: " + name)
    ids = read("schemas/input.schema.json")["properties"]["equipment_ids"]["items"]["enum"]
    require(sorted(ids) == sorted(read("reference/equipment_ids.json")), "equipment ID enum mismatch")
    repo = ROOT.parents[2]
    live = repo / "backend/domain/risk_policy.py"
    if live.is_file():
        require(runpy.run_path(str(live))["MATRIX"] == POLICY["MATRIX"], "live matrix differs")
        require(json.loads((repo / source["path"]).read_text(encoding="utf-8-sig")) == read("reference/catalog.json"), "live catalog differs")


def whole_sentence(quote, source):
    # A quote cannot drop an initial negation or a qualifying clause at its end.
    sentences = re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", source.strip())
    return quote.strip() in [sentence.strip() for sentence in sentences]


def validate_bundles(i, r, a, catalog, registry):
    for name, value in (("input", i), ("retrieval", r), ("analysis", a)):
        check(value, read("schemas/" + name + ".schema.json"))
    media = {m["id"]: m for m in i["media"]}
    require(len(media) == len(i["media"]), "duplicate media")
    require(len(set(i["equipment_ids"])) == len(i["equipment_ids"]), "duplicate equipment")
    retrieved = [c["scenario_id"] for c in r["candidates"]]
    require(len(retrieved) == len(set(retrieved)), "duplicate retrieval")
    for c in r["candidates"]:
        require(c["scenario_id"] in catalog, "unknown scenario")
        refs = c["source_refs"]
        require(all(ref in catalog[c["scenario_id"]]["source_refs"] for ref in refs), "unverified source")
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
        require(any(media[e["media_id"]]["kind"] in ("text", "voice_transcript")
                    and whole_sentence(e["statement"], media[e["media_id"]]["text"])
                    for e in c["evidence"]), "work needs a complete text or voice quote")
        scenario = catalog[c["scenario_id"]]
        known = {x["id"] for x in scenario["controls"]}
        seen = set()
        for e in c["control_evidence"]:
            require(e["control_id"] in known and e["control_id"] not in seen, "invalid/duplicate control")
            seen.add(e["control_id"])
            require(set(e["evidence_refs"]) <= media.keys(), "unknown media")
            require(len(e["evidence_refs"]) == len(set(e["evidence_refs"])), "duplicate evidence")
            if e["state"] != "unknown":
                require(bool(e["evidence_refs"]), "missing control evidence")
                require(all(media[mid]["kind"] in ("text", "voice_transcript") for mid in e["evidence_refs"]), "control references must be text or voice")
                require(any(whole_sentence(e["statement"], media[mid]["text"]) for mid in e["evidence_refs"]), "control requires a whole input sentence")


def validate_assessment(result, catalog):
    check(result, read("schemas/assessment.schema.json"))
    review_ids = [c["scenario_id"] for c in result["review_candidates"]]
    require(len(review_ids) == len(set(review_ids)), "duplicate review candidate")
    require(set(review_ids) <= catalog.keys(), "unknown review candidate")
    require(not set(review_ids).intersection(row["scenario_id"] for row in result["items"]),
            "review candidate already graded")


def validate(i, r, a, legal_registry=None, *, review_candidates=()):
    registry = read("reference/legal_registry.json") if legal_registry is None else legal_registry
    validate_bundles(i, r, a, CAT, registry)
    out = []
    for c in a["candidates"]:
        scenario = CAT[c["scenario_id"]]
        known = {x["id"] for x in scenario["controls"]}
        critical = {x["id"] for x in scenario["controls"] if x["critical"]}
        supported = {e["control_id"] for e in c["control_evidence"] if e["state"] == "supported"}
        band = 3 if not critical <= supported else (1 if known <= supported else 2)
        out.append(dict(scenario_id=scenario["id"], severity=scenario["severity"], control_band=band,
                        grade=POLICY["MATRIX"][scenario["severity"]][band], status="estimated_from_input"))
    unmatched = list(dict.fromkeys(r["unmatched"] + a["unmatched_risks"]))
    result = dict(contract_version="assessment-authoring-1", assessment_mode="input_based",
                  base_policy_version="CATALOG-MVP-1.1", decision_policy_version="CATALOG-MVP-1.1-AUTO-1.0",
                  result_status=("partial" if unmatched else "complete") if out else "no_supported_result",
                  items=out, review_candidates=list(review_candidates), unmatched_risks=unmatched)
    validate_assessment(result, CAT)
    return result


def main():
    verify_sources()
    count = 0
    for name in ("unknown", "critical_supported", "all_supported", "partial", "no_match"):
        prefix = "examples/" + name + "/"
        i, r, a = [read(prefix + n + ".json") for n in ("input", "retrieval", "analysis")]
        require(validate(i, r, a) == read(prefix + "assessment.json"), name)
        count += 1
    photo = read("examples/input_variants/photo.json")
    retrieval = read("examples/unknown/retrieval.json")
    analysis = read("examples/unknown/analysis.json")
    analysis["candidates"][0]["evidence"] = [{"media_id": photo["media"][0]["id"], "statement": photo["media"][0]["text"]}]
    try:
        validate(photo, retrieval, analysis)
    except ValueError:
        count += 1
    else:
        raise ValueError("detection alone produced a graded row")
    original = [read("examples/all_supported/" + n + ".json") for n in ("input", "retrieval", "analysis")]
    mutations = [
        (0, "media", []), (0, "equipment_ids", ["BAD"]),
        (2, "candidates.0.control_evidence.0.control_id", "BAD"),
        (2, "candidates.0.control_evidence.0.evidence_refs", ["MISSING"]),
        (2, "candidates.0.control_evidence.0.evidence_refs", []),
        (2, "candidates.0.control_evidence.0.statement", "invented"),
        (2, "candidates.0.questions", ["question"]),
        (2, "candidates.0.grade", "하"), (2, "candidates.0.evidence", []),
        (2, "candidates.0.evidence.0.statement", "invented"),
        (2, "candidates.0.scenario_id", "BAD"),
        (1, "candidates.0.source_refs.0.document_id", "BAD"),
        (1, "candidates.0.retrieval_status", "no_evidence"),
        (1, "candidates.0.legal_refs", [{"legal_id": "BAD", "url": "https://example.invalid"}]),
        (0, "media.0.kind", "equipment_detection"),
    ]
    original[0]["media"].extend([{"id":"NEG","kind":"text","text":"보호구를 착용하지 않습니다."},
                                 {"id":"PHOTO","kind":"equipment_detection","text":"보호구 탐지"}])
    mutations.append((2, "candidates.0.control_evidence.0.evidence_refs", ["TEXT", "PHOTO"]))
    neg = copy.deepcopy(original)
    neg[2]["candidates"][0]["control_evidence"][0].update(statement="보호구를 착용", evidence_refs=["NEG"])
    try:
        validate(*neg)
    except ValueError:
        count += 1
    else:
        raise ValueError("negation was truncated")
    for target, path, value in mutations:
        case = copy.deepcopy(original)
        cursor = case[target]
        keys = path.split(".")
        for key in keys[:-1]:
            cursor = cursor[int(key) if isinstance(cursor, list) else key]
        cursor[keys[-1]] = value
        try:
            validate(*case)
        except ValueError:
            count += 1
        else:
            raise ValueError("invalid fixture accepted: " + path)
    i, r, a = copy.deepcopy(original)
    critical_id = next(x["id"] for x in CAT["FRY"]["controls"] if x["critical"])
    evidence = next(x for x in a["candidates"][0]["control_evidence"] if x["control_id"] == critical_id)
    evidence.update(state="unknown", evidence_refs=[], statement="자료에서 확인되지 않음")
    require(validate(i, r, a)["items"][0]["control_band"] == 3, "unknown critical")
    count += 1
    evidence.update(state="not_effective", evidence_refs=["TEXT"], statement="현재 핵심 조치가 작동하지 않습니다.")
    i["media"][0]["text"] = "주방에서 튀김 조리를 합니다. " + evidence["statement"] + " " + " ".join(x["statement"] for x in a["candidates"][0]["control_evidence"] if x is not evidence)
    require(validate(i, r, a)["items"][0]["control_band"] == 3, "ineffective critical")
    count += 1
    i, r, a = copy.deepcopy(original)
    r["candidates"][0]["legal_refs"] = [{"legal_id": "SYNTHETIC", "url": "https://example.invalid/test"}]
    registry = [dict(r["candidates"][0]["legal_refs"][0], scenario_ids=["FRY"])]
    validate(i, r, a, registry)
    count += 1
    r["candidates"][0].update(source_refs=[], legal_refs=[], retrieval_status="no_evidence")
    require(validate(i, r, a)["items"][0]["grade"] == "중", "catalog result without documentary evidence")
    count += 1
    expected = {1: ["하", "중", "중"], 2: ["중", "중", "상"], 3: ["상", "상", "상"]}
    for severity, grades in expected.items():
        for band, grade in enumerate(grades, 1):
            require(POLICY["MATRIX"][severity][band] == grade, "matrix regression")
            count += 1
    voice, r, a = copy.deepcopy(original)
    voice["media"][0].update(kind="voice_transcript", text="주방에서 튀김 조리를 합니다")
    a["candidates"][0]["evidence"][0]["statement"] = voice["media"][0]["text"]
    a["candidates"][0]["control_evidence"] = []
    validate(voice, r, a)
    count += 1

    no_rows = read("examples/no_match/assessment.json")
    for reason in ("work_unconfirmed", "input_denies_work"):
        result = dict(no_rows, review_candidates=[{"scenario_id": "FRY", "reason": reason}])
        validate_assessment(result, CAT)
        count += 1
    for result in (
        dict(no_rows, review_candidates=[{"scenario_id": "BAD", "reason": "work_unconfirmed"}]),
        dict(no_rows, review_candidates=[{"scenario_id": "FRY", "reason": "other"}]),
        dict(read("examples/all_supported/assessment.json"),
             review_candidates=[{"scenario_id": "FRY", "reason": "work_unconfirmed"}]),
        dict(no_rows, review_candidates=[{"scenario_id": "FRY", "reason": "work_unconfirmed"}] * 2),
    ):
        try:
            validate_assessment(result, CAT)
        except ValueError:
            count += 1
        else:
            raise ValueError("invalid review candidate accepted")
    print(f"PASS: {count} checks")


if __name__ == "__main__":
    main()
