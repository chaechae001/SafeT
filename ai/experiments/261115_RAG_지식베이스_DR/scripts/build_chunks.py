"""Build RAG chunks from RAG용/ PDFs (restaurant-relevant pages only).

Inputs (read-only): RAG용/*.pdf, scratchpad raw/*.txt (pdftotext 4.00 default mode),
scratchpad ocr5/p0NN.txt (Windows.Media.Ocr ko, file 5 pages 58-73).
Output: <OUT>/261115_RAG_청크_v1_DR.jsonl
"""
import hashlib, json, re, sys, glob, os
import pypdf

ROOT = r"<LOCAL_WORKSPACE>"
RAG = ROOT + "/RAG용"
SC = r"<LOCAL_SCRATCH>"
OUT = ROOT + "/261115_RAG_지식베이스_DR"

FILES = sorted(glob.glob(RAG + "/*.pdf"))  # same order as raw/1..8.txt
assert len(FILES) == 8, FILES

DOC = {
    1: dict(doc_id="D1", title="고용노동부 보도자료(2023.11.15) 서비스업(건물관리·음식업) 위험성평가 실행 안내서 제작·배포", printed_offset=None),
    2: dict(doc_id="D2", title="2023 새로운 위험성평가 안내서", printed_offset=None),
    3: dict(doc_id="D3", title="쉽고 간편한 위험성평가 방법 안내서", printed_offset=None),
    4: dict(doc_id="D4", title="소규모 사업장을 위한 위험성평가 안내서", printed_offset=None),
    5: dict(doc_id="D5", title="서비스업(건물관리, 음식업)을 위한 재해사례 중심 위험성평가 실행 안내서(2023.11)", printed_offset=8),
    6: dict(doc_id="D6", title="민간재해예방기관 종사자 매뉴얼", printed_offset=None),
    7: dict(doc_id="D7", title="음식점업 자율안전점검표", printed_offset=None),
    8: dict(doc_id="D8", title="프랜차이즈 가맹본부의 산재예방 조치 이행 실태조사 및 개선방안 마련 최종보고서(2022.10)", printed_offset=24),
}

# (file, pdf_page, section label, topic, start_marker or None)
SEL = []
SEL += [(1, 1, "보도자료 본문", "제도·자료안내", None), (1, 2, "보도자료 본문", "제도·자료안내", None)]
SEL += [(2, 124, "FAQ: 구내식당 등 도급 시 위험성평가", "제도·FAQ", None)]
SEL += [(4, 112, "안전보건 지원사업: 안전동행 프로그램(음식업 프랜차이즈·단체급식)", "지원제도", None)]
SEL += [(6, 13, "FAQ: 구내식당 등 도급 시 위험성평가", "제도·FAQ", None)]
SEL += [(6, 112, "안전보건 지원사업: 안전동행 프로그램(음식업 프랜차이즈·단체급식)", "지원제도", None)]
SEL += [(5, 12, "서비스업 특성과 재해사례 중심 위험성평가", "평가방법", None)]
D5_SECTIONS = {58: "음식업 11개 위험성평가 대상 주요 업무", 59: "01 이륜차 배달업무", 60: "01 이륜차 배달업무(참고자료)",
               61: "02 차량 배달 작업", 62: "03 계단에서의 작업", 63: "03 계단에서의 작업(참고)", 64: "04 조리·조리작업 중 화재",
               65: "05 바닥에서의 작업", 66: "06 이동식 사다리 작업", 67: "07 음식 운반용 승강기(덤웨이터) 사용 작업",
               68: "08 혼합기(식품가공용) 등 기계 작업", 69: "09 절단용 수공구(칼) 작업", 70: "10 조리 관련 설비, 화학물질 사용 작업",
               71: "10 조리 관련 설비, 화학물질 사용 작업(계속)", 72: "11 식자재 운반 및 보관 작업", 73: "11 식자재 운반 및 보관 작업(계속)"}
SEL += [(5, p, s, "재해사례·위험요인·개선대책", None) for p, s in D5_SECTIONS.items()]
SEL += [(7, p, "음식점업 자율안전점검표", "점검항목", None) for p in range(1, 18)]
SEL += [(8, 36, "음식점업 사고사망 현황(발생형태·기인물)", "재해통계", None),
        (8, 37, "가맹본부 산업재해 예방조치(법 제79조)", "제도", None),
        (8, 63, "도소매업·음식점업 안전보건관리 자율점검 항목", "점검항목", None),
        (8, 71, "외식업 종사자 안전보건 프로그램 절차(국외)", "관리절차", None),
        (8, 96, "국외 공정별 개선안 – 레스토랑 업무", "위험요인·개선대책(국외)", None),
        (8, 97, "국외 공정별 개선안 – 레스토랑 업무", "위험요인·개선대책(국외)", None),
        (8, 120, "법 적용 프랜차이즈 산업재해 분석(요약표)", "재해통계", None)]
# 업종별 현장 가이드(One-page sheet 설명부): pdf 247~275. 업종은 원문 소제목 "(n) 업종명"의 위치로 나눈다.
D8_GUIDE_RANGE = (247, 275)
D8_START_MARKER = "(2) 한식"

ACC_TERMS = ["넘어짐", "넘어져", "미끄러", "떨어짐", "떨어져", "추락", "끼임", "끼여", "말림", "말릴", "베임", "베이", "찔림", "찔릴",
             "화상", "열상", "화재", "폭발", "감전", "교통사고", "충돌", "부딪힘", "근골격계", "요통", "저체온", "질식",
             "피부질환", "이상온도", "낙하", "맞음", "직무스트레스", "소음", "중독", "누출"]
WORK_TERMS = ["배달", "이륜차", "조리", "튀김", "굽기", "밥짓기", "전처리", "설거지", "세척", "청소", "운반", "보관", "입고",
              "검수", "배식", "서빙", "계단", "사다리", "리프트", "덤웨이터", "혼합기", "반죽", "절단", "칼", "가스", "배기후드",
              "냉장", "냉동", "식기세척기", "오븐", "국솥", "화학물질"]


def norm(t):
    t = t.replace("\u00a0", " ").replace("\uf0a7", "•")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def load_pages():
    pages = {}
    for i in range(1, 9):
        if i == 5:
            continue
        ps = open(f"{SC}/raw/{i}.txt", encoding="utf-8").read().split("\f")
        pages[i] = ps
    r = pypdf.PdfReader(FILES[4])
    pages[5] = [p.extract_text() or "" for p in r.pages]
    return pages


def method_for(i, p):
    if i == 5 and p >= 58:
        return "ocr_windows_media_ocr_ko"
    if i == 5:
        return "pypdf_6.21.4"
    return "pdftotext_4.00"


def page_text(pages, i, p):
    if i == 5 and p >= 58:
        return open(f"{SC}/ocr5/p{p:03d}.txt", encoding="utf-8").read()
    return pages[i][p - 1]


def split_chunks(text, maxlen=900, minlen=200):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    chunks, cur = [], ""
    for l in lines:
        if len(cur) + len(l) + 1 > maxlen and len(cur) >= minlen:
            chunks.append(cur)
            cur = l
        else:
            cur = (cur + "\n" + l) if cur else l
        while len(cur) > maxlen * 1.5:  # very long single line
            chunks.append(cur[:maxlen]); cur = cur[maxlen:]
    if cur:
        if chunks and len(cur) < minlen // 2:
            chunks[-1] += "\n" + cur
        else:
            chunks.append(cur)
    return chunks


def main():
    pages = load_pages()
    sel = []
    for i, p, section, topic, marker in SEL:
        sel.append((i, p, section, topic, page_text(pages, i, p), 1))
    # D8 guide: segment by industry headings
    industry, started = None, False
    for p in range(D8_GUIDE_RANGE[0], D8_GUIDE_RANGE[1] + 1):
        raw = pages[8][p - 1]
        if not started:
            raw = raw[raw.index(D8_START_MARKER):]
            started = True
        segs, last = [], 0
        for m in re.finditer(r"\((\d)\) ?([가-힣]{1,8})\n", raw):
            segs.append((industry, raw[last:m.start()]))
            industry, last = m.group(2), m.start()
        segs.append((industry, raw[last:]))
        segno = 0
        for ind, txt in segs:
            if ind is None or len(re.sub(r"\s", "", txt)) < 30:
                continue
            segno += 1
            sel.append((8, p, "업종별 안전보건 현장 가이드: " + ind, "위험요인·예방대책", txt, segno))
    out = []
    for i, p, section, topic, raw, segno in sel:
        t = norm(raw)
        if len(re.sub(r"\s", "", t)) < 30:
            print("SKIP empty", i, p, file=sys.stderr)
            continue
        d = DOC[i]
        parts = split_chunks(t)
        for n, c in enumerate(parts, 1):
            key = re.sub(r"\s", "", c)
            out.append({
                "chunk_id": f"{d['doc_id']}-p{p:03d}-s{segno}-c{n:02d}",
                "doc_id": d["doc_id"],
                "source_file": "RAG용/" + os.path.basename(FILES[i - 1]),
                "doc_title": d["title"],
                "pdf_page": p,
                "printed_page": (p - d["printed_offset"]) if d["printed_offset"] else None,
                "section": section,
                "topic": topic,
                "extraction_method": method_for(i, p),
                "needs_visual_check": method_for(i, p).startswith("ocr"),
                "matched_accident_terms": sorted({w for w in ACC_TERMS if w in c}),
                "matched_work_terms": sorted({w for w in WORK_TERMS if w in c}),
                "char_count": len(c),
                "text_sha1": hashlib.sha1(key.encode("utf-8")).hexdigest(),
                "text": c,
            })
    os.makedirs(OUT, exist_ok=True)
    with open(OUT + "/261115_RAG_청크_v1_DR.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print("chunks", len(out))


if __name__ == "__main__":
    main()
