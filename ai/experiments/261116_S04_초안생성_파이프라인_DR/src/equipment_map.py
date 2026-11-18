"""기기 → equipment_id → 관련 위험요인 코드 → 점검표(구조화 표) 행 매핑.

근거: ../261115_기기마스터_인식평가셋_DR/261115_기기마스터_v1_DR.json (v1-draft, 전문가·팀 검수 전).
- 기기 인식: standard_name + synonyms 문자열 포함(긴 이름 우선).
- 위험요인 코드: 기기마스터 related_hazards(근거있음/제안 표시를 그대로 유지).
- 점검표 행: 기기마스터 sources·refs의 CHK 위치자. 'CHK-4-2-3 …' 같은 절 코드는 그 절 전체,
  'CHK-4-2-3-01' 같은 행 ID는 그 행, 절 코드가 없는 위치자('운반대차', '선반' 등)는 그 낱말이 들어간 행.
- 위험 분류 키워드: 기기마스터 hazard_codes 명칭을 '·'와 꼬리말(노출·부담·위험·접촉)로 나눈 낱말 +
  기기마스터 요약문에 나오는 같은 뜻 낱말(EXTRA, 출처를 주석으로 남김). 안전 기준이 아니라 문자열 분류 보조다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MASTER = Path(__file__).resolve().parent.parent.parent / "261115_기기마스터_인식평가셋_DR" / "261115_기기마스터_v1_DR.json"

# 기기마스터 요약문에 실제로 나오는 표현만 추가한다(괄호 안은 나오는 기기 예).
EXTRA = {
    "slip": ["미끄럼", "미끄러"],                 # '미끄러움'(취반기), 점검표 '미끄럼방지화'
    "cut": ["찔림", "말림", "감김", "협착"],       # 칼·도마 '찔림', 혼합기 '말림', 제면기 '감김·협착'
    "falling": ["부딪힘", "떨어"],                 # 오븐 '부딪힘', 배기후드 '떨어짐'
    "electric": ["누전"],                          # 혼합기·제면기 '누전'
    "ergonomic": ["요통"],                         # 국솥 '요통'
    "heat_cold": ["저온", "저체온"],               # 냉장고 '저온 작업', 냉동창고 '저체온'
    "respiratory": ["CO", "중독"],                 # 가스레인지 'CO 발생·중독'
}


class EquipmentMap:
    def __init__(self, kb_rows: dict, master_path: Path = MASTER):
        self.path = master_path
        m = json.loads(master_path.read_text(encoding="utf-8"))
        self.version, self.status = m.get("version"), m.get("status")
        self.code_names = m["hazard_codes"]
        self.equipment = {e["equipment_id"]: e for e in m["equipment"]}
        names = []
        for eid, e in self.equipment.items():
            for n in [e["standard_name"]] + e.get("synonyms", []):
                for part in [n] + [p for p in re.split(r"[·,/]", n) if p != n]:
                    part = part.strip()
                    if len(part) >= 1:
                        names.append((part, eid))
        self.names = sorted(set(names), key=lambda x: -len(x[0]))
        self.code_keywords = {}
        for code, name in self.code_names.items():
            kws = []
            for p in re.split(r"[·]", name):
                p = re.sub(r"\s*(노출|부담|위험|접촉)$", "", p.strip())
                if p:
                    kws.append(p)
            self.code_keywords[code] = kws + EXTRA.get(code, [])
        # '냉장·냉동실 갇힘'을 '·'로 나누면 '냉장'이 생겨 냉장고 전체가 갇힘으로 분류된다. 핵심 낱말만 쓴다.
        if "entrapment" in self.code_keywords:
            self.code_keywords["entrapment"] = ["갇힘"]
        self.kb_rows = kb_rows

    # -- 인식
    def match(self, text: str) -> list[str]:
        found, taken = [], []
        for n, eid in self.names:
            if len(n) < 2:
                continue
            for mt in re.finditer(re.escape(n), text):
                span = (mt.start(), mt.end())
                if any(a <= span[0] and span[1] <= b for a, b in taken):
                    continue
                taken.append(span)
                if eid not in found:
                    found.append(eid)
        return found

    # -- 위험요인 코드
    def codes(self, eids: list[str]) -> dict[str, str]:
        out = {}
        for eid in eids:
            for h in self.equipment[eid]["related_hazards"]:
                if out.get(h["code"]) != "근거있음":
                    out[h["code"]] = h["evidence"]
        return out

    def classify(self, text: str) -> list[str]:
        return [c for c, kws in self.code_keywords.items() if any(k in text for k in kws)]

    # -- 점검표 행
    def rows_for(self, eids: list[str], codes: list[str] | None = None) -> list[str]:
        locs = []
        for eid in eids:
            e = self.equipment[eid]
            locs += [s["locator"] for s in e.get("sources", []) if s.get("src") == "CHK"]
            for h in e["related_hazards"]:
                if codes is None or h["code"] in codes:
                    locs += [r["locator"] for r in h.get("refs", []) if r.get("src") == "CHK" and r.get("locator")]
        out = []
        for loc in locs:
            m_row = re.match(r"(CHK-\d+(?:-\d+)+)", loc)
            if m_row and m_row.group(1) in self.kb_rows:
                ids = [m_row.group(1)]
            elif m_row:
                sec = m_row.group(1)[4:]  # '4-2-3'
                ids = [rid for rid, r in self.kb_rows.items() if r["source_section"].startswith(sec + ".")]
            else:
                kw = re.sub(r"\(.*?\)", "", loc).strip()
                ids = [rid for rid, r in self.kb_rows.items() if kw and kw in r["source_text"]]
            out += [i for i in ids if i not in out]
        return out

    def rows_with_codes(self, codes: list[str]) -> list[str]:
        kws = [k for c in codes for k in self.code_keywords.get(c, [])]
        return [rid for rid, r in self.kb_rows.items() if any(k in r["source_text"] for k in kws)]

    def describe(self, eid: str) -> str:
        e = self.equipment[eid]
        return "; ".join(f'{self.code_names.get(h["code"], h["code"])}({h["evidence"]}): {h["summary"]}' for h in e["related_hazards"])
