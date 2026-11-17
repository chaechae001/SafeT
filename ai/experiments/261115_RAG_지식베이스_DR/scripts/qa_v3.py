"""independent re-read of v3 outputs: evidence text exists in the source text, ids and counts are consistent"""
import json, re, csv, collections, pypdf
ROOT = r"<LOCAL_WORKSPACE>/"
KB = ROOT + "261115_RAG_지식베이스_DR/"
norm = lambda s: re.sub(r"\s+", "", s or "")
Q = [json.loads(l) for l in open(KB + "261116_RAG_위험요인추천_정답셋_v3_DR.jsonl", encoding="utf-8")]
H = json.load(open(KB + "261116_RAG_정답셋_v3_holdout제외목록_DR.json", encoding="utf-8"))
rows = list(csv.DictReader(open(KB + "261116_RAG_정답셋_v3_검수표_DR.csv", encoding="utf-8-sig")))
links = {json.loads(l)["link_id"]: json.loads(l) for l in open(KB + "261116_RAG_기기위험요인링크_v2_DR.jsonl", encoding="utf-8")}
tb = {json.loads(l)["row_id"]: json.loads(l) for l in open(KB + "261115_RAG_구조화표_v1_DR.jsonl", encoding="utf-8")}
d8 = {r["row_key"]: r for r in json.load(open(KB + "261116_RAG_D8표복원행_v2_DR.json", encoding="utf-8"))}
pdf_cache = {}
def pdf_text(f, p):
    k = (f, p)
    if k not in pdf_cache:
        pdf_cache[k] = norm(pypdf.PdfReader(ROOT + f).pages[p - 1].extract_text())
    return pdf_cache[k]
txt = {"KOSHA24_OKGYE": norm(open(ROOT + "261113_restaurant_completed_assessments_DR/261113_KOSHA_2024_위험성평가우수사례_원본_DR.txt", encoding="utf-8").read()),
       "NJ_CAFE_SINK": norm(open(ROOT + "261113_restaurant_completed_assessments_DR/난정_추출.txt", encoding="utf-8").read()),
       "P14": norm(open(ROOT + "261113_본사컨설팅_평가완료표_조사_DR/261113_학교급식_안전보건관리대책_2014_공개원문_DR.txt", encoding="utf-8").read())}
R = {"queries": len(Q), "evidence_checked": 0, "by_method": collections.Counter(), "not_found": []}
for q in Q:
    for g in q["gold"] + [dict(n, role="neg") for n in q["hard_negatives"]]:
        for ev in g["evidence"]:
            sid, t = ev["source_id"], ev.get("text") or ""
            R["evidence_checked"] += 1
            if ev.get("link_id"):
                ok = norm(links[ev["link_id"]]["hazard_text"]) == norm(t); m = "v2 link hazard_text"
            elif sid.startswith("CASE-"):
                ok = norm(tb[sid]["hazard_text"]) == norm(t); m = "v1 table case row"
            elif sid.startswith("D8T-"):
                ok = any(norm(t) in norm(h) or norm(h) in norm(t) for h in d8[sid]["hazards"]); m = "D8 restored row"
            elif sid.startswith("CHK-"):
                ok = norm(t) == norm(tb[sid]["source_text"]); m = "v1 checklist row"
            elif sid.startswith("D5V-"):
                ok = None; m = "D5 visual transcription (no text layer; v2 log)"
            elif sid.startswith("P14"):
                ok = norm(t)[:12] in txt["P14"]; m = "2014 txt (first 12 chars)"
            else:
                ok = norm(t)[:25] in txt[sid]; m = "record txt (first 25 chars)"
            R["by_method"][m] += 1
            if ok is False:
                R["not_found"].append([q["query_id"], sid, t[:60]])
# D5V: compare against the v2 links of the same unit
d5 = collections.defaultdict(set)
for l in links.values():
    if l["source_id"].startswith("D5V-"):
        d5[l["source_id"]].add(norm(l["hazard_text"]))
R["d5_evidence_not_in_v2_links_or_unit"] = [[q["query_id"], ev["source_id"], ev["text"]] for q in Q for g in q["gold"] for ev in g["evidence"]
                                            if ev["source_id"].startswith("D5V-") and not ev.get("link_id") and g["role"] != "context"]
R["csv_rows"] = len(rows)
R["csv_roles"] = dict(collections.Counter(r["role"] for r in rows))
R["csv_status_all_ai_unreviewed"] = all(r["status"] == "AI 보조, 검수 전" for r in rows)
R["csv_query_ids_match"] = sorted({r["query_id"] for r in rows}) == sorted(q["query_id"] for q in Q)
R["csv_gold_rows_equal_jsonl"] = sum(1 for r in rows if r["role"].startswith("정답")) == sum(len(q["gold"]) for q in Q)
R["csv_negative_rows_equal_jsonl"] = sum(1 for r in rows if r["role"].startswith("함정")) == sum(len(q["hard_negatives"]) for q in Q)
R["holdout_ids_match_splits"] = sorted(H["test_query_ids"] + H["dev_query_ids"]) == sorted(q["query_id"] for q in Q)
ex = set(H["exclude"]["v2_link_source_ids"])
R["test_g_anchor_not_in_holdout"] = [q["query_id"] for q in Q if q["split"] == "test" and q["tier"] == "G"
                                     for s in q["provenance"]["anchor_sources"] if s in {l["source_id"] for l in links.values()} and s not in ex]
R["by_method"] = dict(R["by_method"])
print(json.dumps(R, ensure_ascii=False, indent=1))
