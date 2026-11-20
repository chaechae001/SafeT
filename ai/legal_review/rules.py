"""Conservative evidence filtering for the topics covered by the HWPX9 experiment."""
import re

SAFETY = "산업안전보건기준에 관한 규칙"
TRAFFIC = "도로교통법"
TOPICS = (
    ("site_record", (r"근무표|점검일지|배달 기록|기록은 제공", r"직원|근무|점검")),
    ("license_scope", (r"면허", r"배기량|출력|차종|종류별|운전 가능 범위")),
    ("helmet", (r"안전모|헬멧", r"배달|이륜|오토바이")),
    ("driver_license", (r"면허", r"운행|운전|배달")),
    ("wet_road", (r"빗길|우천|젖은\s*(?:도로|노면)|비가\s*내", r"운전|충돌|이륜|제동")),
    ("aisle", (r"통로", r"걸려|적치|장애물|방치")),
    ("grinder", (r"분쇄기|분쇄하는 기계", r"끼이|말려|투입|방호|덮개")),
    ("electrical", (r"전기|감전", r"누전차단기|누전 차단기")),
    ("floor", (r"바닥|작업장|조리실", r"미끄러|헛디")),
)
RULES = {
    "helmet": ((SAFETY, (r"(?:이륜자동차|원동기장치자전거)", r"배달", r"승차용 안전모")),),
    "driver_license": (
        (TRAFFIC, (r"면허를 받지 아니하거나", r"운전하여서는 아니 된다")),
        (TRAFFIC, (r"자동차등을 운전하려는 사람", r"운전면허를 받아야 한다")),
    ),
    "wet_road": ((TRAFFIC, (r"도로의 교통상황", r"위험과 장해를 주는 속도나 방법")),),
    "aisle": ((SAFETY, (r"통로면으로부터", r"장애물이 없도록")),),
    "floor": ((SAFETY, (r"미끄러지는 등의 위험", r"바닥 등을 안전하고 청결")),),
}
MANUAL_RULES = {
    "grinder": (
        (r"분쇄기|분쇄하는 기계", r"덮개를 설치", r"보조기구"),
        "분쇄기 투입·배출 부위의 예외와 실제 방호 상태를 함께 확인해야 합니다.",
    ),
    "electrical": (
        (r"감전방지용 누전차단기", r"전기기계", r"대지전압|습윤장소"),
        "장소·기구와 전압 조건이 원문의 적용 요건에 해당하는지 확인해야 합니다.",
    ),
}
NOTES = {
    "site_record": "사업장의 근무·작업 기록이 제공되지 않아 확인할 수 없습니다.",
    "license_scope": "면허별 운전 가능 차종을 직접 정한 표 또는 조문이 필요합니다.",
    "helmet": "승차용 안전모의 세부 기준은 이 발췌가 참조하는 시행규칙에서 확인해야 합니다.",
    "driver_license": "실제 보유 면허나 차량에 맞는 면허인지 여부는 이 발췌만으로 확인할 수 없습니다.",
    "wet_road": "제공된 발췌로는 빗길 감속 수치와 실제 위반 여부를 확인할 수 없습니다.",
}


def matches(patterns, text):
    return all(re.search(pattern, text) for pattern in patterns)


def review(question, candidates, model_result):
    topic = next((name for name, patterns in TOPICS if matches(patterns, question)), "unsupported")
    selected = {item["chunk"] for item in (model_result["selection"] or {}).get("citations", [])}
    # 기존 자동 인용 규칙 밖에서도 실제 검색·선택된 조항은 검토할 수 있다.
    if topic == "unsupported":
        proposals = [row for row in candidates if row["chunk_id"] in selected]
        if proposals:
            return dict(topic=topic, status="manual_review", status_label="수동 검토 필요",
                        limitation="검색된 조항의 적용 조건을 확인해 주세요.", evidence=[],
                        review_candidates=proposals, removed_model_citations=sorted(selected))
    candidates = [row for row in candidates if row.get("part", "본문") == "본문"]
    if topic in MANUAL_RULES:
        patterns, limitation = MANUAL_RULES[topic]
        candidate = next((row for row in candidates if row["law"] == SAFETY
                          and matches(patterns, row["text"])), None)
        if candidate is not None:
            return {
                "topic": topic, "status": "manual_review", "status_label": "수동 검토 필요",
                "limitation": limitation, "evidence": [],
                "review_candidates": [candidate],
                "removed_model_citations": sorted(selected),
            }
    evidence = []
    criteria = RULES.get(topic, ())
    for law, patterns in criteria:
        for candidate in candidates:
            if candidate["law"] != law:
                continue
            quotation = candidate["text"]
            if topic == "helmet":
                quotation = next((line for line in quotation.splitlines() if matches(patterns, line)), "")
            if not matches(patterns, quotation):
                continue
            chunk = candidate["chunk_id"]
            evidence.append({
                "chunk": chunk, "law": law, "locator": candidate["locator"], "quotation": quotation,
                **{k: candidate[k] for k in ("source_file", "source_sha256", "priority") if k in candidate},
                "origin": "retained_citation" if chunk in selected else "recovered_from_candidate",
            })
            break
    kept = {item["chunk"] for item in evidence}
    if not evidence:
        status = "insufficient"
        limitation = NOTES.get(topic) if not criteria else None
        limitation = limitation or "제공된 검색 후보에서 질문을 직접 뒷받침하는 근거를 확인하지 못했습니다."
    else:
        limitation = NOTES.get(topic, "")
        if len(evidence) < len(criteria):
            limitation = "질문에 필요한 근거 일부를 후보에서 확인하지 못했습니다. " + limitation
        status = "conditional" if limitation else "answered"
    return {
        "topic": topic, "status": status, "limitation": limitation, "evidence": evidence,
        "review_candidates": [],
        "removed_model_citations": sorted(selected - kept),
    }
