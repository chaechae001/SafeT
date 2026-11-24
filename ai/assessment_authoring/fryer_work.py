"""Separate fryer use, non-use, and work that needs confirmation."""
import re

from .live_text_check import input_segments, resolve_input_citations
from .retrieval_adapter import _fry_work_denied, _mentions

_FRYER_NAME = r"(?:튀김기|프라이어|fryer)"
_FRYER = re.compile(_FRYER_NAME, re.IGNORECASE)
_FRYING_ACTION = re.compile(r"튀김\s*(?:조리|작업|을\s*하)")
_FRYER_COOKING = re.compile(_FRYER_NAME + r"(?:로|에서|에)[^.!?]{0,40}조리", re.IGNORECASE)
_FRYER_OPERATION = re.compile(_FRYER_NAME + r"(?:를|을)?\s*(?:(?:가끔|간헐적으로)\s*)?(?:사용|가동|씁니다|써요|켭니다)", re.IGNORECASE)
_FRYING_OIL = re.compile(_FRYER_NAME + r"(?:의|에서|에 든)?\s*기름|튀김유|튀김\s*기름", re.IGNORECASE)
_HOT_OIL = re.compile(r"(?:달군|가열된|뜨거운|끓는|고온(?:의)?)\s*(?:튀김\s*)?(?:기름|식용유|폐유)|(?:기름|식용유|폐유)[^.!?]{0,12}(?:잔열|뜨거|끓)")
_OIL_HANDLING_HINT = re.compile(r"(?=.*물기)(?=.*(?:긴\s*)?집게)(?=.*(?:투입|넣))")
_OIL_EXPOSURE = re.compile(r"튀(?:었|어|는|어요)|비산|넣|쏟|닿|빼|배유|교체|옮|흘")
# 작업 동사 자체가 부정되면('청소하지 않고', '교체하지 않고') 그 작업의 근거가 아니다.
_NOT_DONE = r"(?!\s*(?:을|를)?\s*(?:하)?지\s*않)"
_OIL_HANDLING = re.compile(r"(?:기름|튀김유)[^.!?]{0,35}(?:교체|교환|버리|빼|배유|옮기|갈아)" + _NOT_DONE + r"|배유" + _NOT_DONE)
_FRYER_CLEANING = re.compile(_FRYER_NAME + r"(?:의?\s*(?:내부|기름통))?(?:를|을)?\s*(?:직접\s*)?(?:세척|청소|닦|배유)" + _NOT_DONE, re.IGNORECASE)
_PERFORMED = re.compile(r"합니|해요|했|하였|하곤|한다|하고 있|교체해|갈아|닦|뺍니|씁니다|써요|켭니다")
_UNCLEAR = re.compile(r"모릅|모르|불명|미확인|확인\s*(?:필요|중)|(?:사용|가동)\s*여부|예정|않으면|한다면|할\s*경우")
# 사용 동사의 부정만 미사용으로 본다. '식지 않은 기름', '끄지 않은 채'는 작업 조건이지 미사용이 아니다.
_NEGATED = re.compile(
    r"(?:쓰|켜|돌리|튀기|(?:사용|가동|작동|이용)(?:하|되)|(?:튀김|조리|작업|사용)\s*(?:을|를|은|는)?\s*하)지\s*않"
    r"|안\s*(?:넣|빼|해|합|하|쓰|튀기)|미사용|보관만"
)
_CONTRAST = re.compile(r"(?:지만|으나|는데|반면)\s*|[,;]\s*")
_FIRE_EXPOSURE = re.compile(r"과열|불꽃|불이\s*붙|착화|탄\s*냄새|연기가\s*나|누출|폭발")


def _statement_state(statement):
    state = "unmentioned"
    for clause in _CONTRAST.split(statement):
        fryer_named = is_fryer(clause)
        frying = _FRYING_ACTION.search(clause)
        verbs = _mentions(clause, ("튀기", "튀깁", "튀겨"))
        if _UNCLEAR.search(clause):
            if fryer_named or frying or verbs or _FRYING_OIL.search(clause):
                state = "unconfirmed"
            continue
        if _NEGATED.search(clause):
            if fryer_named or frying or verbs or _fry_work_denied(clause):
                state = "unused"
            continue
        if any(verdict == "used" and certain for _, _, verdict, certain, _ in verbs):
            return "used"
        if _HOT_OIL.search(clause) and _OIL_EXPOSURE.search(clause):
            return "used"
        if _PERFORMED.search(clause) and (
            frying or _FRYER_COOKING.search(clause) or _FRYER_OPERATION.search(clause)
            or _FRYER_CLEANING.search(clause)
            or _FRYING_OIL.search(clause) and _OIL_HANDLING.search(clause)
        ):
            return "used"
        if state == "unmentioned" and (
            fryer_named or frying or verbs or _FRYING_OIL.search(clause) or _OIL_HANDLING_HINT.search(clause)
        ):
            state = "unconfirmed"
    return state


def decide(context):
    states = set()
    for ref, (_, sentence) in input_segments(context).items():
        state = _statement_state(sentence)
        if state == "used":
            return state, ref
        states.add(state)
    if "unconfirmed" in states:
        return "unconfirmed", None
    if "unused" in states:
        return "unused", None
    if "EQ_FRYER" in context.get("equipment_ids", ()):
        return "unconfirmed", None
    return "unmentioned", None


def enrich(context, retrieval, trace, ranker):
    state, _ = decide(context)
    if state == "used":
        trace["not_applicable_candidates"] = [sid for sid in trace["not_applicable_candidates"] if sid != "FRY"]
        trace["text_candidates"] = sorted(set(trace["text_candidates"]) | {"FRY"})
    elif state == "unused":
        trace["not_applicable_candidates"] = sorted(set(trace["not_applicable_candidates"]) | {"FRY"})
        trace["uncertain_work_candidates"] = [
            sid for sid in trace.get("uncertain_work_candidates", ()) if sid != "FRY"
        ]
    ranker.augment(context, retrieval, trace)
    if state == "used" and not any(row["scenario_id"] == "FRY" for row in retrieval["candidates"]):
        retrieval["candidates"].append(dict(scenario_id="FRY", source_refs=[], legal_refs=[], retrieval_status="no_evidence"))
    if state == "unconfirmed":
        trace["not_applicable_candidates"] = [sid for sid in trace["not_applicable_candidates"] if sid != "FRY"]
        trace["uncertain_work_candidates"] = sorted(set(trace.get("uncertain_work_candidates", ())) | {"FRY"})
    if state in ("unused", "unconfirmed"):
        retrieval["candidates"] = [row for row in retrieval["candidates"] if row["scenario_id"] != "FRY"]


def add_confirmed_work(context, analysis, batch_ids):
    state, ref = decide(context)
    if state == "used" and "FRY" in batch_ids and not any(
        row["scenario_id"] == "FRY" for row in analysis["candidates"]
    ):
        analysis["candidates"].extend(resolve_input_citations(
            {"candidates": [{"scenario_id": "FRY", "work_ref": ref, "controls": []}]}, context
        )["candidates"])
    return analysis


def supports_work(statement):
    return _statement_state(statement) == "used"


def is_fryer(text):
    return bool(_FRYER.search(text or ""))


def fryer_only_suggestion(text):
    return bool((is_fryer(text) or _FRYING_ACTION.search(text or ""))
                and not _FIRE_EXPOSURE.search(text or ""))
