"""Conservative fryer work states for the isolated authoring rollout."""
import re

from .live_text_check import input_segments
from .retrieval_adapter import _mentions

_FRYER = re.compile(r"튀김기|프라이어|fryer", re.IGNORECASE)
_FRIED_WORK = re.compile(r"튀김\s*조리|튀기|튀깁|튀겨")
_FRYER_COOKING = re.compile(r"(?:튀김기|프라이어)[^.!?]{0,40}조리")
_HOT_OIL = re.compile(r"(?:달군|가열된|뜨거운|끓는|고온(?:의)?)\s*(?:튀김\s*)?(?:기름|식용유|폐유)|(?:기름|식용유|폐유)[^.!?]{0,12}(?:잔열|뜨거|끓)")
_OIL_HANDLING_HINT = re.compile(r"(?=.*물기)(?=.*(?:긴\s*)?집게)(?=.*(?:투입|넣))")
_OIL_EXPOSURE = re.compile(r"튀(?:었|어|었|는|어요)|비산|넣|쏟|닿|빼|배유|교체|옮|흘")
_HANDLING = re.compile(r"기름[^.!?]{0,35}(?:교체|교환|버리|빼|배유|옮기)|(?:세척|청소|배유)(?:을|를)?\s*(?:합니|해요|했|하였|하곤|한다|하는 작업)")
_PERFORMED = re.compile(r"합니|해요|했|하였|하곤|한다|하고 있|교체해|갈아|닦")
_UNCLEAR = re.compile(r"모릅|모르|불명|미확인|확인\s*(?:필요|중)|예정|않으면|한다면|할\s*경우")
_UNUSED = re.compile(r"(?:(?:전혀|실제로)\s*)?(?:쓰|사용하|가동하)지\s*않|미사용|보관만")
_CONTRAST = re.compile(r"(?:지만|으나|는데|반면)\s*|[,;]\s*")
_FIRE_EXPOSURE = re.compile(r"과열|불꽃|불이\s*붙|착화|탄\s*냄새|연기가\s*나|누출|폭발")

def decide(context):
    segments = input_segments(context)
    text = " ".join(sentence for _, sentence in segments.values())
    for ref, (_, sentence) in segments.items():
        for clause in _CONTRAST.split(sentence):
            if (_HOT_OIL.search(clause) and _OIL_EXPOSURE.search(clause)
                    and not (_UNCLEAR.search(clause) or _UNUSED.search(clause)
                             or re.search(r"(?:지|하지)\s*않|안\s*(?:넣|빼|하)", clause))):
                return "used", ref
    if not _FRYER.search(text) and "EQ_FRYER" not in context.get("equipment_ids", ()):
        if any(_OIL_HANDLING_HINT.search(sentence) for _, sentence in segments.values()):
            return "unconfirmed", None
        return "unmentioned", None
    for ref, (_, sentence) in segments.items():
        for clause in _CONTRAST.split(sentence):
            if _UNCLEAR.search(clause) or _UNUSED.search(clause) or re.search(r"하지\s*않|안\s*(?:해|합|하)", clause):
                continue
            if (_HANDLING.search(clause) and _PERFORMED.search(clause)
                    or (_FRIED_WORK.search(clause) or _FRYER_COOKING.search(clause)) and _PERFORMED.search(clause)
                    or any(v == "used" and c for _, _, v, c, _ in _mentions(clause, ("튀기", "튀깁", "튀겨")))):
                return "used", ref
    if any(_FRYER.search(sentence) and _UNUSED.search(sentence) and not _UNCLEAR.search(sentence)
           for _, sentence in segments.values()):
        return "unused", None
    return "unconfirmed", None

def enrich(context, retrieval, trace, ranker):
    state, _ = decide(context)
    if state == "used":
        trace["not_applicable_candidates"] = [sid for sid in trace["not_applicable_candidates"] if sid != "FRY"]
        trace["text_candidates"] = sorted(set(trace["text_candidates"]) | {"FRY"})
    if state == "unused":
        trace["not_applicable_candidates"] = sorted(set(trace["not_applicable_candidates"]) | {"FRY"})
        trace["uncertain_work_candidates"] = [
            sid for sid in trace.get("uncertain_work_candidates", ()) if sid != "FRY"
        ]
    ranker.augment(context, retrieval, trace)
    if state == "used" and not any(row["scenario_id"] == "FRY" for row in retrieval["candidates"]):
        retrieval["candidates"].append(dict(scenario_id="FRY", source_refs=[], legal_refs=[], retrieval_status="no_evidence"))
    if state == "unconfirmed" and any(row["scenario_id"] == "FRY" for row in retrieval["candidates"]):
        trace["uncertain_work_candidates"] = sorted(set(trace.get("uncertain_work_candidates", ())) | {"FRY"})
    if state in ("unused", "unconfirmed"):
        retrieval["candidates"] = [row for row in retrieval["candidates"] if row["scenario_id"] != "FRY"]

def guard_output(context, checked, batch_ids):
    from .live_text_check import resolve_input_citations

    state, ref = decide(context)
    if state == "unmentioned":
        return checked
    candidates = checked["candidates"]
    if state in ("unused", "unconfirmed"):
        candidates = [
            row for row in candidates
            if any(not (_FRYER.search(quote["statement"]) or _FRIED_WORK.search(quote["statement"])
                        or _UNCLEAR.search(quote["statement"]) or re.search(r"하지\s*않", quote["statement"]))
                   or _FIRE_EXPOSURE.search(quote["statement"]) for quote in row["evidence"])
        ]
    if state == "used" and "FRY" in batch_ids and not any(
            row["scenario_id"] == "FRY" and row["evidence"][0]["statement"] == input_segments(context)[ref][1]
            for row in candidates):
        candidates = [row for row in candidates if row["scenario_id"] != "FRY"]
        candidates.extend(resolve_input_citations(
            {"candidates": [{"scenario_id": "FRY", "work_ref": ref, "controls": []}]}, context
        )["candidates"])
    checked["candidates"] = [
        row for row in candidates if row["scenario_id"] != "FIRE" or
        any(_FIRE_EXPOSURE.search(quote["statement"]) or
            not (_FRYER.search(quote["statement"]) or _FRIED_WORK.search(quote["statement"]))
            for quote in row["evidence"])
    ]
    return checked

def is_fryer(text):
    return bool(_FRYER.search(text or ""))

def fryer_only_suggestion(text):
    return bool((_FRYER.search(text or "") or _FRIED_WORK.search(text or ""))
                and not _FIRE_EXPOSURE.search(text or ""))