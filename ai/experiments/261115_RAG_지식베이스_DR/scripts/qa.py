import json, re, collections, difflib, hashlib, os, glob

O = r"<LOCAL_WORKSPACE>/261115_RAG_지식베이스_DR/"
RAG = r"<LOCAL_WORKSPACE>/RAG용/"
ch = [json.loads(l) for l in open(O + "261115_RAG_청크_v1_DR.jsonl", encoding="utf-8")]
tb = [json.loads(l) for l in open(O + "261115_RAG_구조화표_v1_DR.jsonl", encoding="utf-8")]
law = json.load(open(O + "261115_RAG_법령검증목록_v1_DR.json", encoding="utf-8"))
R = {}

# --- chunks
R["chunks_total"] = len(ch)
R["chunks_by_doc"] = dict(sorted(collections.Counter(c["doc_id"] for c in ch).items()))
R["chunks_by_method"] = dict(collections.Counter(c["extraction_method"] for c in ch))
R["chunk_id_unique"] = len({c["chunk_id"] for c in ch}) == len(ch)
req = ["chunk_id", "doc_id", "source_file", "pdf_page", "section", "topic", "extraction_method", "text", "text_sha1"]
R["chunks_missing_required_fields"] = [c["chunk_id"] for c in ch if any(c.get(k) in (None, "") for k in req)]
R["chunks_source_file_exists"] = all(os.path.exists(RAG + c["source_file"].split("/", 1)[1]) for c in ch)
cc = sorted(c["char_count"] for c in ch)
R["chunk_chars_min_median_max"] = [cc[0], cc[len(cc) // 2], cc[-1]]
dup = collections.defaultdict(list)
for c in ch:
    dup[c["text_sha1"]].append(c["chunk_id"])
R["chunks_exact_duplicates"] = [v for v in dup.values() if len(v) > 1]
# near duplicates (same doc, different page) ratio >= 0.9
near = []
for i in range(len(ch)):
    for j in range(i + 1, len(ch)):
        a, b = ch[i], ch[j]
        if abs(len(a["text"]) - len(b["text"])) > 300:
            continue
        r = difflib.SequenceMatcher(None, a["text"], b["text"], autojunk=False).quick_ratio()
        if r >= 0.9:
            r2 = difflib.SequenceMatcher(None, a["text"], b["text"], autojunk=False).ratio()
            if r2 >= 0.8:
                near.append([a["chunk_id"], b["chunk_id"], round(r2, 3)])
R["chunks_near_duplicates_ratio_ge_0.8"] = near
# OCR quality: share of Hangul syllables in non-space chars
def hangul_ratio(t):
    n = len(re.sub(r"\s", "", t)); return round(len(re.findall(r"[가-힣]", t)) / n, 3) if n else 0
R["ocr_chunks_hangul_ratio_min"] = min(hangul_ratio(c["text"]) for c in ch if c["needs_visual_check"])
R["chunks_with_no_accident_terms"] = [c["chunk_id"] for c in ch if not c["matched_accident_terms"]]
pages = collections.defaultdict(set)
for c in ch:
    pages[c["doc_id"]].add(c["pdf_page"])
R["pages_covered"] = {k: sorted(v) for k, v in sorted(pages.items())}
R["expected_pages_missing"] = {
    "D5_58_73": sorted(set(range(58, 74)) - pages["D5"]),
    "D7_1_17": sorted(set(range(1, 18)) - pages["D7"]),
    "D8_247_275": sorted(set(range(247, 276)) - pages["D8"]),
}

# --- table
R["table_total"] = len(tb)
R["table_by_type"] = dict(collections.Counter(t["source_type"] for t in tb))
R["table_row_id_unique"] = len({t["row_id"] for t in tb}) == len(tb)
secs = collections.defaultdict(list)
for t in tb:
    if t["source_type"] == "checklist":
        secs[t["source_section"]].append(t["source_item_no"])
R["checklist_items_by_section"] = {k: len(v) for k, v in secs.items()}
R["checklist_numbering_gaps"] = {k: [n for n in range(1, max(v) + 1) if n not in v] for k, v in secs.items() if sorted(v) != list(range(1, len(v) + 1))}
d2 = collections.defaultdict(list)
for t in tb:
    d2[t["source_text_sha1"]].append(t["row_id"])
R["table_duplicate_source_text"] = [v for v in d2.values() if len(v) > 1]
hz = collections.defaultdict(list)
for t in tb:
    if t.get("hazard_text"):
        hz[t["hazard_text"]].append(t["row_id"])
R["case_duplicate_hazard_text"] = [v for v in hz.values() if len(v) > 1]
R["table_empty_source_text"] = [t["row_id"] for t in tb if not t["source_text"].strip()]
R["table_field_fill"] = {f: sum(1 for t in tb if t.get(f)) for f in ["work_or_object", "hazard_text", "hazard_terms_in_text", "accident_type_terms_in_text", "current_control", "improvement_measure", "checklist_control_item"]}
# checklist text vs pdf: every row text (spaces removed) must appear in the pdf text (spaces removed)
import pypdf
pdf = re.sub(r"\s", "", "".join(p.extract_text() for p in pypdf.PdfReader(RAG + "음식점업 자율안전점검표.pdf").pages))
miss = []
for t in tb:
    if t["source_type"] == "checklist":
        parts = re.split(r"\s(?=[※*])", t["source_text"])
        for p in parts:
            if re.sub(r"\s", "", p) not in pdf:
                miss.append(t["row_id"])
R["checklist_text_not_found_in_pdf"] = sorted(set(miss))
# --- law
R["law_verified"] = law["counts"]["verified"]
R["law_unverified"] = law["counts"]["unverified"]
R["law_verified_by_law"] = dict(collections.Counter(v["law_name"] for v in law["verified"]))
ids = {c["chunk_id"] for c in ch}
R["law_cited_chunk_missing"] = [c["chunk_id"] for v in law["verified"] for c in v["cited_in"] if c["chunk_id"] not in ids]
# source file hashes (originals untouched check reference)
R["source_sha256"] = {os.path.basename(f): hashlib.sha256(open(f, "rb").read()).hexdigest() for f in sorted(glob.glob(RAG + "*.pdf"))}
json.dump(R, open(O + "261115_RAG_점검결과_v1_DR.json", "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in R.items() if k not in ("source_sha256", "pages_covered", "chunks_with_no_accident_terms")}, ensure_ascii=False, indent=1))
