import json, re, collections, glob
import pypdf

ROOT = r"<LOCAL_WORKSPACE>/"
KB = ROOT + "261115_RAG_지식베이스_DR/"
SC = r"<LOCAL_SCRATCH>/"
norm = lambda s: re.sub(r"\s+", "", s or "")
R = {}
ix = json.load(open(KB + "261116_RAG_기기위험요인인덱스_v2_DR.json", encoding="utf-8"))
links = [json.loads(l) for l in open(KB + "261116_RAG_기기위험요인링크_v2_DR.jsonl", encoding="utf-8")]
gold = [json.loads(l) for l in open(KB + "261116_RAG_위험요인추천_정답셋_v2_DR.jsonl", encoding="utf-8")]
d8 = json.load(open(SC + "d8_rows.json", encoding="utf-8"))
master = json.load(open(ROOT + "261115_기기마스터_인식평가셋_DR/261115_기기마스터_v1_DR.json", encoding="utf-8"))

# D8 table rows vs PDF text (spaces removed)
r = pypdf.PdfReader(glob.glob(ROOT + "RAG용/*최종보고서*")[0])
pt = {p: norm(r.pages[p - 1].extract_text()) for p in range(247, 276)}
miss = []
for row in d8:
    joined = "".join(pt[p] for p in row["pages"])
    for t in row["hazards"] + row["measures"]:
        parts = [norm(x) for x in re.split(r"\s*•\s*", t) if x.strip()]
        for x in parts:
            if x not in joined:
                miss.append([row["row_key"], t])
R["d8_rows"] = len(d8)
R["d8_bullets"] = sum(len(x["hazards"]) + len(x["measures"]) for x in d8)
R["d8_bullets_not_found_in_pdf_text"] = miss
R["d8_rows_by_industry"] = dict(collections.Counter(x["industry"] for x in d8))

# links
eqids = {e["equipment_id"] for e in master["equipment"]}
R["links"] = len(links)
R["links_by_source_type"] = dict(collections.Counter(l["source_type"] for l in links))
R["links_by_tier"] = dict(collections.Counter(l["evidence_tier"] for l in links))
R["links_unknown_equipment"] = [l["link_id"] for l in links if l["equipment_id"] not in eqids]
R["links_unknown_hazard_code"] = [l["link_id"] for l in links if l["hazard_code"] not in master["hazard_codes"]]
k = collections.Counter((l["equipment_id"], l["hazard_code"], norm(l["hazard_text"]), l["source_id"]) for l in links)
R["links_duplicate_keys"] = [list(x) for x, n in k.items() if n > 1]
R["links_hazard_code_term_not_in_text"] = [l["link_id"] for l in links if l["hazard_code_term"] not in l["hazard_text"]]
R["equipment_with_links"] = ix["counts"]["equipment_with_links"]
R["equipment_no_evidence"] = [n["equipment_id"] for n in ix["no_evidence"]]
R["hazard_texts_without_code"] = len(ix["hazard_texts_without_code"])
rel = collections.Counter(m["relevance_rank"] for e in ix["index"] for h in e["hazards"] for m in h["measures"])
R["measure_relevance_rank_counts"] = dict(sorted(rel.items()))
mc = ix["master_v1_link_check"]
R["master_v1_hazard_links"] = len(mc)
R["master_v1_supported_by_v2"] = sum(1 for m in mc if m["supported_by_v2_links"])
R["master_v1_not_supported"] = [[m["equipment_id"], m["hazard_code"], m["master_evidence"]] for m in mc if not m["supported_by_v2_links"]]
v2_codes = {(l["equipment_id"], l["hazard_code"]) for l in links}
m_codes = {(m["equipment_id"], m["hazard_code"]) for m in mc}
R["v2_links_not_in_master_v1"] = sorted([list(x) for x in v2_codes - m_codes])

# focus: knife / cutting board / marinator
foc = {}
for eid in ("EQ_KNIFE_BOARD", "EQ_MARINATOR"):
    e = [x for x in ix["index"] if x["equipment_id"] == eid][0]
    foc[eid] = {"hazard_codes": {h["hazard_code"]: {"sources": h["n_sources"], "measures": h["n_measures"],
                                                    "measures_rank1_2": sum(1 for m in h["measures"] if m["relevance_rank"] <= 2)} for h in e["hazards"]},
                "measure_only": len(e["measure_only"])}
R["focus"] = foc

# gold
R["gold_items"] = len(gold)
R["gold_by_tier"] = dict(collections.Counter(g["tier"] for g in gold))
R["gold_default_eval"] = [g["gold_id"] for g in gold if g["use_in_default_eval"]]
R["gold_leakage_high"] = [g["gold_id"] for g in gold if g["leakage_records"]]
R["gold_evidence_records"] = sum(len(g["evidence"]) for g in gold)
# index coverage of gold codes (sanity, not a model metric): with and without CASE-sourced links
cov = []
for g in gold:
    eid = g["query"]["equipment_id"]
    if not eid:
        continue
    allc = {l["hazard_code"] for l in links if l["equipment_id"] == eid}
    noc = {l["hazard_code"] for l in links if l["equipment_id"] == eid and l["source_id"] not in g["eval_exclude_source_ids"]}
    gs = set(g["gold_hazard_codes"])
    cov.append({"gold_id": g["gold_id"], "equipment_id": eid, "gold": sorted(gs),
                "index_codes_all": sorted(allc), "covered_all": sorted(gs & allc),
                "index_codes_without_leaked_case": sorted(noc), "covered_without_leaked_case": sorted(gs & noc)})
R["index_coverage_of_gold_codes"] = cov
json.dump(R, open(KB + "261116_RAG_점검결과_v2_DR.json", "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in R.items() if k not in ("v2_links_not_in_master_v1",)}, ensure_ascii=False, indent=1)[:9000])
