"""8010 판정과 인용 무결성 검사로 최종 출력의 근거 일치를 평가한다."""
import hashlib
import json
from pathlib import Path

KEY = "legal_groundedness_v1"
PROMPT = Path(__file__).with_name("groundedness_prompt.txt").read_text(encoding="utf-8-sig")
CHECKS = ("supported", "relevant", "scope_preserved", "no_violation_assertion", "abstention_appropriate")


def citation_integrity(context, answer):
    sources = {row["chunk_id"]: row for row in context}
    errors = []
    if answer["status"] in ("manual_review", "insufficient") and answer["evidence"]:
        errors.append("보류 상태의 자동 인용이 비어 있지 않습니다.")
    for citation in answer["evidence"]:
        source = sources.get(citation["chunk"])
        if source is None:
            errors.append("검색 후보에 없는 청크를 인용했습니다.")
            continue
        if (citation["law"], citation["locator"]) != (source["law"], source["locator"]):
            errors.append("인용 법령과 조항이 검색 후보와 다릅니다.")
        if not citation.get("quotation") or citation["quotation"] not in source["text"]:
            errors.append("인용문이 검색 원문에서 확인되지 않습니다.")
    return errors


def legal_groundedness_v1(question, context, answer, invoke):
    """invoke는 같은 8010 관문을 호출하며 호출 추적은 실행자가 담당한다."""
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": json.dumps({"question": question,
         "context": context, "answer": answer}, ensure_ascii=False)},
    ]
    response = invoke(messages)
    judged = json.loads(response["choices"][0]["message"]["content"])
    if not isinstance(judged, dict):
        raise ValueError("평가 응답은 JSON 객체여야 합니다.")
    checks = judged.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        raise ValueError("평가 항목이 형식과 다릅니다.")
    if not all(type(checks[key]) is bool for key in CHECKS):
        raise ValueError("평가 항목은 true/false여야 합니다.")
    reason = judged.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise ValueError("구체적인 평가 이유가 없습니다.")
    errors = citation_integrity(context, answer)
    return {"key": KEY, "score": int(all(checks.values()) and not errors),
            "comment": reason.strip() + (" 인용 검사: " + " ".join(errors) if errors else ""),
            "checks": checks, "citation_errors": errors, "judge_model": response["model"],
            "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "target": "postprocessed_answer"}
