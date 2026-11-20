"""9개 HWPX의 조문을 출처·우선순위와 함께 KURE-v1 컬렉션에 적재한다."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import chromadb
import torch
from transformers import AutoModel, AutoTokenizer

ORDER = ("01", "02", "03", "04", "05", "06", "06-02", "07", "08")
ARTICLE = re.compile(r"^(제\d+조(?:의\d+)?)\s*(?:\(([^)]*)\)|(?=삭제))")
PARAGRAPHS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
COLLECTION = "safet-full-nine-kure-v1"


def sections(path):
    lines = []
    with ZipFile(path) as archive:
        parts = sorted((int(m[1]), name) for name in archive.namelist()
                       if (m := re.fullmatch(r"Contents/section(\d+)\.xml", name)))
        for _, name in parts:
            for para in ET.fromstring(archive.read(name)).findall("./{*}p"):
                text = "".join("".join(t.itertext()) for t in para.iterfind(".//{*}t")).strip()
                if text:
                    lines.append(text)
    law = lines[0].split("( 약칭")[0].strip()
    article = title = locator = ""
    part = "본문"
    body = []
    for line in lines:
        heading = ARTICLE.match(line)
        addendum = re.match(r"^부\s*칙(?:\s*<|$)", line)
        paragraph = line[0] in PARAGRAPHS
        chapter = re.match(r"^제\d+(?:편|장|절|관)\s", line)
        if heading or addendum or chapter or paragraph:
            if body:
                yield law, part, article, locator, title, "\n".join(body)
                body = []
        if addendum:
            part = line
            article = locator = "부칙"
            title = ""
        elif heading:
            article, title = heading[1], heading[2] or ""
            rest = line[heading.end():].strip()
            locator = article
            if rest and rest[0] in PARAGRAPHS:
                locator += f"제{PARAGRAPHS.index(rest[0])+1}항"
        elif chapter:
            article = locator = ""
            continue
        elif paragraph and article:
            locator = article + f"제{PARAGRAPHS.index(line[0])+1}항"
        if article:
            body.append(line)
    if body:
        yield law, part, article, locator, title, "\n".join(body)


def encode(tokenizer, model, texts):
    with torch.inference_mode():
        tokens = tokenizer(texts, padding=True, return_tensors="pt").to(model.device)
        return torch.nn.functional.normalize(model(**tokens).last_hidden_state[:, 0]).tolist()


def chunks(path, priority, tokenizer):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for unit, (law, part, article, locator, title, body) in enumerate(sections(path), 1):
        prefix = f"{law} {part} {locator} {title}\n"
        start = 0
        while start < len(body):
            end = min(start + 600, len(body))
            while len(tokenizer(prefix + body[start:end], verbose=False)["input_ids"]) > 512:
                if end - start <= 1:
                    raise ValueError("법령 위치 정보가 토큰 한도를 초과했습니다.")
                end = start + (end - start) * 3 // 4
            key = f"D{priority:02}-U{unit:05}-{start}"
            meta = dict(chunk_id=key, law=law, section=locator, article=article,
                        part=part, priority=priority, source_file=path.name,
                        source_sha256=digest, start=start, end=end,
                        deleted=bool(re.match(r"^제\d+조(?:의\d+)?\s*(?:\([^)]*\))?\s*삭제", body)))
            yield key, prefix + body[start:end], meta
            if end == len(body):
                break
            start = max(start + 1, end - 90)


def build(source, target, weights, device="cpu"):
    paths = sorted(source.glob("*.hwpx"))
    by_id = {p.name.split("_")[0]: p for p in paths}
    if len(paths) != 9 or set(by_id) != set(ORDER):
        raise ValueError("원본 번호 01~08 및 06-02의 HWPX 9개가 필요합니다.")
    target.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    tokenizer = AutoTokenizer.from_pretrained(weights, local_files_only=True)
    model = AutoModel.from_pretrained(weights, local_files_only=True).eval().to(device)
    collection = chromadb.PersistentClient(path=str(target)).get_or_create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"})
    manifest = []
    catalog = []
    fingerprint = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for name in ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"):
        with (weights / name).open("rb") as file:
            fingerprint += hashlib.file_digest(file, "sha256").hexdigest()
    fingerprint += "".join(hashlib.sha256(by_id[k].read_bytes()).hexdigest() for k in ORDER)
    marker = target / "build-id.txt"
    if marker.exists() and marker.read_text() != fingerprint:
        raise ValueError("입력이나 빌더가 바뀌었습니다. 새 출력 폴더를 지정하세요.")
    marker.write_text(fingerprint)
    for priority, doc_id in enumerate(ORDER, 1):
        rows = list(chunks(by_id[doc_id], priority, tokenizer))
        if not rows:
            raise ValueError(f"{doc_id} 원문 추출 실패")
        present = set(collection.get(where={"priority": priority}, include=[])["ids"])
        missing = [r for r in rows if r[0] not in present]
        missing.sort(key=lambda row: len(row[1]))
        for start in range(0, len(missing), 16):
            ids, texts, metas = zip(*missing[start:start+16])
            collection.upsert(ids=list(ids), documents=list(texts), metadatas=list(metas),
                              embeddings=encode(tokenizer, model, list(texts)))
        stored = set(collection.get(where={"priority": priority}, include=[])["ids"])
        if stored != {r[0] for r in rows}:
            raise ValueError(f"{doc_id} 적재 목록 불일치")
        catalog.extend(meta for _, _, meta in rows)
        info = dict(priority=priority, file=by_id[doc_id].name, chunks=len(rows),
                    articles=len({m["article"] for _, _, m in rows if m["part"] == "본문"}),
                    sha256=rows[0][2]["source_sha256"])
        manifest.append(info)
        print(info, flush=True)
    catalog_temp = target / "chunks.tmp"
    with catalog_temp.open("w", encoding="utf8") as out:
        for meta in catalog:
            out.write(json.dumps(meta, ensure_ascii=False) + "\n")
    os.replace(catalog_temp, target / "chunks.jsonl")
    temp = target / "manifest.tmp"
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
    os.replace(temp, target / "manifest.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for arg in ("source", "target", "weights"):
        parser.add_argument(arg, type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    build(args.source, args.target, args.weights, args.device)
