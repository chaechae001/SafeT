"""국가법령정보센터 HWPX 본문을 조별 JSONL로 분리한다. Python 3.9+."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ARTICLE = re.compile(r"^(제\d+조(?:의\d+)?)\s*(?:\(([^)]*)\)|(삭제))")
APPENDIX = re.compile(r"^부\s*칙(?:\s|<|$)")
SECTION = re.compile(r"Contents/section(\d+)\.xml")


def articles(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    law = edition = None
    row = None
    with ZipFile(path) as archive:
        parts = sorted((int(m[1]), m[0]) for name in archive.namelist()
                       if (m := SECTION.fullmatch(name)))
        if not parts:
            raise ValueError(f"{path.name}: section XML 없음")
        for _, section in parts:
            for number, p in enumerate(ET.fromstring(archive.read(section)).findall("./{*}p"), 1):
                line = "".join("".join(t.itertext()) for t in p.findall("./{*}run/{*}t")).strip()
                if not law and line:
                    law = line.split("( 약칭:")[0].strip()
                if line.startswith("[시행") and edition is None:
                    edition = line
                if APPENDIX.match(line):
                    if row:
                        yield row
                    return
                m = ARTICLE.match(line)
                if m or re.match(r"^제\d+[편장절관]\s", line):
                    if row:
                        yield row
                    row = None
                if m:
                    row = dict(id=f"{digest}:{section}:{number}", law=law, edition=edition,
                               article=m[1], title=m[2], deleted=bool(m[3]), source=path.name,
                               sha256=digest, section=section, paragraph=number,
                               table_review_required=False, paragraphs=[])
                if row is not None:
                    if line:
                        row["paragraphs"].append(line)
                    if p.find(".//{*}tbl") is not None:
                        row["table_review_required"] = True
    if row:
        yield row


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path, help="HWPX 파일 또는 폴더")
    cli.add_argument("output", type=Path, help="새 JSONL 경로")
    args = cli.parse_args()
    files = [args.source] if args.source.is_file() else sorted(args.source.glob("*.hwpx"))
    if not files:
        cli.error("HWPX 파일 없음")
    records = []
    for path in files:
        rows = list(articles(path))
        if not rows or not all(r["edition"] for r in rows):
            raise ValueError(f"{path.name}: 본문 또는 시행본 표기 확인 필요")
        records.extend(rows)
        print(path.name, len(rows))
    with args.output.open("x", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"전체 {len(records)}건")


if __name__ == "__main__":
    main()
