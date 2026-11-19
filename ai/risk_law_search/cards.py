"""위험사례 카드(risk_card_data.md 안의 JSONL)를 읽는다.

지침(docs/chroma/risk-card-data-model-team-guide.md) 기준:
- 원본 객체는 raw로 손실 없이 보존한다.
- 직접 조치(measures)와 보강 조치(measures_extra, 다른 카드 출처)를 나눈다.
- laws가 빈 배열이면 '관련 법령 없음'이 아니라 '미수록'이다.
- machine_names와 machine_codes는 배열 순서로 일대일 연결하지 않는다.
"""
import hashlib
import json
from pathlib import Path

KIND = {"check": "checklist", "case": "case", "reference": "reference"}


def load_cards(path):
    path = Path(path)
    raw = path.read_bytes()
    cards = []
    for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.startswith("{"):
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path.name} {n}행: JSON 오류 {e}") from None
        cards.append(c)
    ids = [c["id"] for c in cards]
    if len(ids) != len(set(ids)):
        raise ValueError("카드 ID 중복")
    known = set(ids)
    out = []
    for c in cards:
        src = c.get("source") or {}
        out.append(dict(
            id=c["id"], kind=KIND.get(c.get("type"), c.get("type")), type=c.get("type"),
            biz=c.get("biz"), section=c.get("section"), section_no=c.get("section_no"),
            target=c.get("target") or "", example_jobs=c.get("example_jobs") or [],
            machine_names=c.get("machine_names") or [], machine_codes=c.get("machine_codes") or [],
            risk_type=c.get("risk_type") or "", title=c.get("title") or "", text=c.get("text") or "",
            measures=list(c.get("measures") or []),
            measures_extra=[dict(text=m["text"], from_card=m.get("from"), from_known=m.get("from") in known)
                            for m in c.get("measures_extra") or []],
            laws=list(c.get("laws") or []), laws_recorded=bool(c.get("laws")),
            deaths_3y=c.get("deaths_3y"),
            source=dict(doc=src.get("doc"), publisher=src.get("publisher"), year=src.get("year"),
                        page=src.get("page"), page_kind="unverified"),
            embed_text=c.get("embed_text") or "", has_stats="stats" in c, raw=c))
    return out, dict(file=path.name, sha256=hashlib.sha256(raw).hexdigest(), cards=len(out))


def card_search_text(c):
    """카드 고유 내용(기기·사고 유형·제목·본문). 의미 검색과 키워드 검색의 주 대상이다.

    구역명·대상 작업·예시 작업(section, target, example_jobs)은 같은 구역 카드들이 그대로 공유한다.
    예: 식재료 전처리 구역 카드는 위험이 제면기 말림이어도 '야채 절단'을 갖는다.
    이런 공통 문구가 카드 고유 위험보다 점수를 끌어올리지 않도록 여기서 뺀다(card_context_text로 따로 약하게 반영).
    대책 문장도 넣지 않는다(일반 문장이라 카드끼리 비슷해짐).
    """
    parts = [" ".join(c["machine_names"]), c["risk_type"], c["title"], c["text"]]
    return " ".join(p for p in parts if p)


def card_context_text(c):
    """구역 공통 문구. 키워드 점수에만 낮은 비중으로 더한다."""
    parts = [c["section"] or "", c["target"], " ".join(c["example_jobs"])]
    return " ".join(p for p in parts if p)


def card_law_text(c):
    """카드와 가까운 법령을 찾을 때 쓰는 문장. 법령은 의무(조치)를 적으므로 직접 조치를 포함한다."""
    return card_search_text(c) + " " + " ".join(c["measures"])
