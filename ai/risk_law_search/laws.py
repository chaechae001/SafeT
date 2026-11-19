"""국가법령정보센터 HWPX 본문을 항 단위 검색 조각으로 나눈다.

조문 분리 규칙은 공유 규약(docs/rag-evidence-v1/parse_law_hwpx.py)을 따른다.
- 부칙은 첫 부칙 표제에서 끊어 제외한다.
- 삭제 조문은 deleted로 표시하고 검색에서 뺀다.
- 표가 있는 조문은 table_review_required로 표시한다(표 안 내용은 별도 대조 대상).
검색 단위는 항(①②…)이다. 호(1. 2. …)와 목은 속한 항에 붙인다. 항이 없는 조문은 조문 전체가 한 단위다.
"""
import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ARTICLE = re.compile(r"^(제(\d+)조(?:의(\d+))?)\s*(?:\(([^)]*)\)|(삭제))")
APPENDIX = re.compile(r"^부\s*칙(?:\s|<|$)")
HEADING = re.compile(r"^제\d+([편장절관])(?:의\d+)?\s")
LEVELS = "편장절관"
SECTION = re.compile(r"Contents/section(\d+)\.xml")
FILE_NO = re.compile(r"^(\d+)(?:-(\d+))?_")
EDITION = re.compile(r"^\[시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
FUTURE = re.compile(r"^\[시행일\s*:\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]\s*(.*)$")
REF = re.compile(r"제(\d+)조(?:의(\d+))?")
NOTE = re.compile(r"<(?:개정|신설|전문개정|본조신설|제목개정)[^>]*>|\[(?:[^\]]*(?:이동|본조신설|전문개정|종전)[^\]]*)\]")


def doc_order(name):
    """파일명 앞 번호로 순서를 정한다. 06 → (6, 0), 06-02 → (6, 2)."""
    m = FILE_NO.match(name)
    if not m:
        raise ValueError(f"{name}: 파일명 앞 번호가 없습니다(예: 01_법령명.hwpx)")
    return int(m[1]), int(m[2] or 0)


def doc_no(order):
    return f"{order[0]:02d}" + (f"-{order[1]:02d}" if order[1] else "")


def _lines(path):
    with ZipFile(path) as archive:
        parts = sorted((int(m[1]), m[0]) for name in archive.namelist() if (m := SECTION.fullmatch(name)))
        if not parts:
            raise ValueError(f"{path.name}: section XML 없음")
        for _, section in parts:
            for p in ET.fromstring(archive.read(section)).findall("./{*}p"):
                text = "".join("".join(t.itertext()) for t in p.findall("./{*}run/{*}t")).strip()
                yield text, p.find(".//{*}tbl") is not None


def clean(text):
    """검색용으로 개정 이력 표기만 지운다. 원문은 따로 보존한다."""
    return re.sub(r"\s+", " ", NOTE.sub(" ", text)).strip()


def parse(path):
    """HWPX 한 개 → 문서 정보와 항 단위 조각 목록."""
    path = Path(path)
    raw = path.read_bytes()
    order = doc_order(path.name)
    no = doc_no(order)
    law = edition = effective = None
    heading = []
    articles = []
    current = None
    for line, has_table in _lines(path):
        if not line and not has_table:
            continue
        if law is None and line:
            law = line.split("( 약칭:")[0].strip()
            continue
        if edition is None and line.startswith("[시행"):
            edition = line
            m = EDITION.match(line)
            if m:
                effective = f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"
            continue
        if APPENDIX.match(line):
            break
        fm = FUTURE.match(line)
        if fm:
            # 개정 조문 뒤의 시행일 표시. 같은 번호 조문이 두 번 있으면 뒤의 것이 시행 예정 판이다.
            date = f"{int(fm[1]):04d}-{int(fm[2]):02d}-{int(fm[3]):02d}"
            for n, b in REF.findall(fm[4]):
                same = [a for a in articles if a["number"] == int(n) and a["branch"] == int(b or 0)]
                if len(same) >= 2:
                    same[-1]["future_from"] = date
                elif same:
                    same[-1]["future_note"] = line
            continue
        hm = HEADING.match(line)
        if hm:
            depth = LEVELS.index(hm[1])
            heading = [h for h in heading if LEVELS.index(HEADING.match(h)[1]) < depth] + [line]
            current = None
            continue
        m = ARTICLE.match(line)
        if m:
            current = dict(article=m[1], number=int(m[2]), branch=int(m[3] or 0), title=m[4] or "",
                           deleted=bool(m[5]), heading=" > ".join(heading), lines=[], table=False)
            articles.append(current)
        if current is not None:
            if line:
                current["lines"].append(line)
            current["table"] = current["table"] or has_table
    if not law or not edition:
        raise ValueError(f"{path.name}: 법령명 또는 시행본 표기를 찾지 못했습니다")
    version = (effective or "unknown").replace("-", "")
    doc = dict(doc_id=f"LAW-{no}", doc_no=no, order=order, law_name=law, edition=edition,
               effective_from=effective, file=path.name, sha256=hashlib.sha256(raw).hexdigest(),
               articles=sum(1 for a in articles if not a["deleted"]))
    units = []
    for a in articles:
        if a["deleted"]:
            continue
        groups = []  # 항 단위로 묶는다. 첫 줄(조 제목 포함)은 첫 항이거나 항 없는 본문이다.
        for i, line in enumerate(a["lines"]):
            body = line[len(a["article"]):].lstrip() if i == 0 else line
            if i == 0 and a["title"]:
                body = body[len(a["title"]) + 2:].lstrip() if body.startswith("(" + a["title"] + ")") else body
            if body and body[0] in CIRCLED:
                groups.append([CIRCLED.index(body[0]) + 1, [line]])
            elif groups:
                groups[-1][1].append(line)
            else:
                groups.append([0, [line]])
        art_key = f"art{a['number']}" + (f"-{a['branch']}" if a["branch"] else "")
        future = a.get("future_from")
        for para, lines in groups:
            original = "\n".join(lines)
            locator = a["article"] + (f"제{para}항" if para else "")
            units.append(dict(
                id=f"law:{no}@{version}:{art_key}:p{para}" + (f":f{future.replace('-', '')}" if future else ""),
                doc_id=doc["doc_id"], doc_no=no, order=order,
                law_name=law, article=a["article"], article_title=a["title"], paragraph=para or None,
                locator=locator, heading=a["heading"], quote=original, search_text=clean(original),
                effective_from=future or effective, future_version=bool(future),
                future_note=a.get("future_note"), table_review_required=a["table"]))
    return doc, units


def load_laws(folder):
    """폴더의 HWPX를 파일명 앞 번호 순서로 읽는다."""
    files = sorted(Path(folder).glob("*.hwpx"), key=lambda p: doc_order(p.name))
    if not files:
        raise ValueError(f"{folder}: HWPX 파일이 없습니다")
    docs, units = [], []
    for f in files:
        d, u = parse(f)
        docs.append(d)
        units.extend(u)
    ids = [u["id"] for u in units]
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})[:5]
        raise ValueError(f"법령 조각 ID 중복: {dup}")
    return docs, units
