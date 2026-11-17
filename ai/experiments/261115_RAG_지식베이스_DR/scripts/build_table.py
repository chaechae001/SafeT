"""Structured table: 작업(대상)–위험요인–사고유형–현재조치–개선대책, verbatim source text kept.

Sources:
 - RAG용/음식점업 자율안전점검표.pdf (pdftotext -layout, per page)  -> source_type=checklist
 - 261113_restaurant_completed_assessments_DR/261113_실제사업장_위험성평가사례_8건_DR.jsonl (+ 원본 PDF 쪽 대조) -> source_type=case
Rule: fields are filled only with text present in the source. Otherwise null.
"""
import json, re, hashlib

ROOT = r"<LOCAL_WORKSPACE>"
SC = r"<LOCAL_SCRATCH>"
OUT = ROOT + "/261115_RAG_지식베이스_DR/261115_RAG_구조화표_v1_DR.jsonl"
CHK = "RAG용/음식점업 자율안전점검표.pdf"

# accident-type terms; only literal occurrences are recorded
ACC = [("넘어지거나 미끄러지는", "넘어짐·미끄러짐"), ("넘어짐", "넘어짐"), ("미끄러짐", "미끄러짐"), ("미끄럼", None),
       ("떨어질", "떨어짐"), ("떨어짐", "떨어짐"), ("추락", "떨어짐"), ("넘어짐·미끄러짐", "넘어짐·미끄러짐"),
       ("말릴", "끼임(말림)"), ("끼임", "끼임"), ("베임", "베임"), ("찔릴", "찔림"), ("부딪힘", "부딪힘"),
       ("화상", "화상"), ("열상", "열상"), ("화재", "화재"), ("폭발", "폭발"), ("누출", "누출"), ("감전", "감전"),
       ("충돌", "충돌"), ("저체온증", "저체온증"), ("근골격계질환", "근골격계질환"), ("건강장해", "건강장해"),
       ("소음", None), ("조리흄", None)]
HAZ = ["기름기", "물기", "중량물", "가스누출", "가스 누출", "가스", "LPG", "LNG", "인화성", "유해화학물질", "락스", "세제", "세척제",
       "전선", "회전날", "회전체", "칼날", "톱날", "동력전달부", "증기", "고온", "고열", "한랭", "소음", "진동", "조리흄", "전기설비",
       "냉장·냉동고", "냉동․냉장창고", "덤웨이터", "운반대차", "선반", "멀티탭", "콘센트", "분전반", "배관", "출입문"]


def acc_terms(t):
    found = []
    for k, v in ACC:
        if k in t and v and v not in found:
            found.append(v)
    return found


def haz_terms(t):
    return [h for h in HAZ if h in t]


def parse_checklist():
    """pypdf text keeps a trailing space where the source has a real space before a line wrap.
    Join rule: previous line ends with space -> one space; else no space (mid-word wrap)."""
    import pypdf
    r = pypdf.PdfReader(ROOT + "/" + CHK)
    rows, cur, sec, refs = [], None, None, False

    def flush():
        nonlocal cur
        if cur:
            cur["text"] = re.sub(r"[ ]{2,}", " ", cur["buf"]).strip()
            rows.append(cur)
        cur = None

    for pi, page in enumerate(r.pages, 1):
        for raw in (page.extract_text() or "").split("\n"):
            s = raw.strip()
            if not s:
                continue
            m_sec = re.match(r"^(4-\d-\d)\.\s*(.+)$", s)
            if m_sec:
                flush(); refs = False; sec = (m_sec.group(1), m_sec.group(2).strip()); continue
            if re.match(r"^4-\d\.\s", s) or re.match(r"^4\.\s*분야별", s) or s.startswith("1. 사업장 개요"):
                flush(); refs = False; continue
            if s == "2. 위험성평가":
                flush(); refs = False; sec = ("2", "위험성평가"); continue
            if s.startswith("3. 안전 및 보건에 관한 프로그램"):
                flush(); refs = False; sec = ("3", "안전 및 보건에 관한 프로그램(가맹점)"); continue
            if s.startswith("<") and "참고자료" in s:
                flush(); refs = True; continue
            if refs or s.startswith("자가진단 항목") or s == "음식점업 자율안전점검표" or s.startswith(("사업장명", "소 재 지", "근로자수")):
                continue
            m_item = re.match(r"^(\d{1,2})\.\s*(.*)$", s)
            if m_item and sec and sec[0] != "3":
                flush()
                cur = {"sec": sec, "no": int(m_item.group(1)), "page": pi, "buf": m_item.group(2), "tail_space": raw.endswith(" ")}
                continue
            if sec and sec[0] == "3" and cur is None:
                cur = {"sec": sec, "no": 1, "page": pi, "buf": s, "tail_space": raw.endswith(" ")}
                continue
            if cur is not None:
                if s.startswith(("※", "*")):
                    cur["buf"] += " " + s
                else:
                    cur["buf"] += (" " if cur["tail_space"] else "") + s
                cur["tail_space"] = raw.endswith(" ")
    flush()
    return rows


def checklist_rows():
    out = []
    for r in parse_checklist():
        code, title = r["sec"]
        t = r["text"]
        out.append({
            "row_id": f"CHK-{code}-{r['no']:02d}",
            "source_type": "checklist",
            "source_file": CHK,
            "source_pdf_page": r["page"],
            "source_section": f"{code}. {title}" if code[0] == "4" else title,
            "source_item_no": r["no"],
            "source_text": t,
            "work_or_object": title,
            "work_or_object_basis": "점검표 섹션 제목(원문)",
            "hazard_terms_in_text": haz_terms(t),
            "accident_type_terms_in_text": acc_terms(t),
            "current_control": None,
            "improvement_measure": None,
            "checklist_control_item": t,
            "field_note": "점검표 항목은 갖춰야 할 조치 상태를 묻는다. 현재조치·개선대책 구분은 사업장 응답(네/아니요)에 따라 정해지므로 원문 항목은 checklist_control_item에만 둔다.",
            "risk_scores": None,
            "source_text_method": "pypdf 6.21.4 텍스트 추출, 줄바꿈은 줄 끝 공백 유무로 결합",
            "review_status": "전문가 검수 전",
        })
    return out


# --- 8 cases: verbatim text transcribed from source PDF pages ---
# S01: 사업단_page15~20.png (이미지형 페이지, 시각 판독 전사 2026-11-15). S02: pdftotext -layout p42~43.
CASE_SRC = {
    "S01": "261113_restaurant_completed_assessments_DR/261113_노인인력개발원_안전보건관리에센스_원본_DR.pdf",
    "S02": "261113_restaurant_completed_assessments_DR/261113_난정평화교육원_2025_위험성평가결과_원본_DR.pdf",
}
CASE_TEXT = {
    "FOOD_A_01": dict(h="콘센트를 바닥에 놓고 사용하고 있어 콘센트 파손 및 감전사고 및 화재 위험이 있음",
                      c="사용하지 않는 전선은 제거하거나 연결하여 사용할 경우 배관 등을 이용하여 벽에 고정 설치", m="시각 판독 전사(이미지형 페이지)"),
    "FOOD_A_02": dict(h="LPG가스용기 전도방지대책이 실시되어 있지 않아 취급 중 부주의로 가스용기 전도 및 파손 우려가 있고 누출된 가스로 인해 화재·폭발의 위험이 있음",
                      c="가스용기를 전용보관함에 보관하거나, 넘어지지 않도록 바닥을 평평한 곳에 체인 등으로 고정하여 보관", m="시각 판독 전사(이미지형 페이지)"),
    "FOOD_A_03": dict(h="LPG가스용기 전도방지대책이 실시되어 있지 않아 취급 중 부주의로 가스용기 전도 및 파손 우려가 있고 누출된 가스로 인해 화재·폭발의 위험이 있음",
                      c="분전반 외함에 감전주의 및 관계자 외 조작 금지 표지 부착 / 분전반 내부로 이물질이 들어가지 않도록 구멍 틈 밀폐", m="시각 판독 전사(이미지형 페이지)"),
    "FOOD_A_04": dict(h="전선을 가스 배관에 고정하여 사용하고 있는데 가스누출 시 화재 및 폭발의 위험이 있음",
                      c="배관 이음부(곡관, 분기관, 밸브 등)와 전선은 사이 거리를 10cm 이상, 콘센트와는15cm가 되도록 조정", m="시각 판독 전사(이미지형 페이지)"),
    "FOOD_A_05": dict(h="일부 가스배관의 경우, 설치된 가스누설경보차단기가 작동하고 있지 않아 가스 누설 시 화재 및 폭발의 위험이 있음",
                      c="현재 작동 중인 감지기와 차단기는 해당 배관과 별도이므로 해당 배관에 감지기를 설치하고 관리", m="시각 판독 전사(이미지형 페이지)"),
    "CAFE_B_01": dict(h="매장 출입 시 출입문을 보지 못할 경우 문과 충돌 또는 끼임 위험이 있음",
                      c="출입문이 잘 보이도록 표지 부착 / 충돌주의, 끼임주의 표지 부착", m="시각 판독 전사(이미지형 페이지)"),
    "KITCHEN_N_01": dict(h="급식실 내 분전반 감전주의표지 미부착 및 잠금 불이행하여 감전위험",
                         c="① 분전반 감전주의표지 및 잠금 조치 ② 잠금 상태 간헐적 점검", m="pdftotext -layout(표 셀 줄바꿈 결합)"),
    "KITCHEN_N_02": dict(h="급식실 내 벽면 분전반 감전주의표지 미부착하여 감전위험",
                         c="분전반 감전주의표지 부착", m="pdftotext -layout(표 셀 줄바꿈 결합)"),
}
CASE_LABEL = {"S01": "원문 표제: 유해위험요인 / 권고의견", "S02": "원문 표제: 유해･위험요인 / 감소 대책"}
CASE_SCORE_NOTE = {
    "FOOD_A_05": "원문 개선 전 표기: 발생가능성 2, 중대성 4, 위험성 12(곱 8과 불일치). 원문 그대로 둠.",
}


def case_rows():
    out = []
    for line in open(ROOT + "/261113_restaurant_completed_assessments_DR/261113_실제사업장_위험성평가사례_8건_DR.jsonl", encoding="utf-8"):
        d = json.loads(line)
        ct = CASE_TEXT[d["id"]]
        src = d["source_id"]
        is_impl = src == "S02"
        out.append({
            "row_id": f"CASE-{d['id']}",
            "source_type": "case",
            "source_file": CASE_SRC[src],
            "source_pdf_page": d["source_pdf_page"],
            "source_section": f"{d['site']} ({d['evidence_type']})",
            "source_item_no": None,
            "source_text": f"[유해위험요인] {ct['h']} [대책] {ct['c']}",
            "source_text_labels": CASE_LABEL[src],
            "source_text_method": ct["m"],
            "work_or_object": None,
            "work_or_object_basis": "원문에 작업명 표기 없음",
            "hazard_text": ct["h"],
            "hazard_terms_in_text": haz_terms(ct["h"]),
            "accident_type_terms_in_text": acc_terms(ct["h"]),
            "current_control": None,
            "improvement_measure": ct["c"],
            "improvement_measure_status": ("개선 실행 기록(개선날짜·담당자 원문 기재)" if is_impl else "권고의견(실행일·서명 미기록)"),
            "checklist_control_item": None,
            "field_note": "원문에 현재조치 칸이 없다. 8건 JSONL의 hazard_summary/control_summary는 2026-11-13 AI 요약이므로 원문 문장으로 쓰지 않는다.",
            "risk_scores": {"before": d["before"], "after": d["after"],
                             "note": CASE_SCORE_NOTE.get(d["id"])},
            "derived_from": "261113_restaurant_completed_assessments_DR/261113_실제사업장_위험성평가사례_8건_DR.jsonl#" + d["id"],
            "project_review_status": d["project_review_status"],
            "quality_note": d["quality_note"],
            "review_status": "전문가 검수 전",
        })
    return out


def main():
    rows = checklist_rows() + case_rows()
    for r in rows:
        r["source_text_sha1"] = hashlib.sha1(re.sub(r"\s", "", r["source_text"]).encode("utf-8")).hexdigest()
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("rows", len(rows))


if __name__ == "__main__":
    main()
