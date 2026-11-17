"""v3 gold set for hazard recommendation (harder and larger than v2).

Every query is anchored to a set of gold source units (a guide table row, a checklist item, a guide page, or a real record).
  gold                 : hazard codes that the anchored source evaluates for the query equipment (rule lexicon, same as index v2)
                         + 'context' codes when the query's site note quotes a source sentence that adds a hazard.
  acceptable_extra     : codes the v2 index supports for the query equipment from other sources (not counted wrong in lenient precision)
  hard_negatives       : codes that look plausible (they are in the same source, or the equipment word appears inside another word)
                         but the source attributes them to something else AND no v2 link supports them for the query equipment.
  unverified_master    : codes only the equipment master v1 lists (no v2 evidence). Neither gold nor negative.
Tiers  R = real assessment record, P = published example assessment table (2014), G = derived from guide / checklist text.
No hazard, criterion, or threshold is invented. Query sentences are templates (AI-written wrapper); site notes quote sources verbatim.
"""
import json, re, csv, collections, hashlib

ROOT = r"<LOCAL_WORKSPACE>/"
KB = ROOT + "261115_RAG_지식베이스_DR/"
SC = r"<LOCAL_SCRATCH>/"
PIPE_RANKED = ROOT + "261116_S04_초안생성_파이프라인_DR/runs/hitl_recommend/ranked_codes.json"
OUT_JSONL = KB + "261116_RAG_위험요인추천_정답셋_v3_DR.jsonl"
OUT_HOLD = KB + "261116_RAG_정답셋_v3_holdout제외목록_DR.json"
OUT_CSV = KB + "261116_RAG_정답셋_v3_검수표_DR.csv"
OUT_QA = KB + "261116_RAG_정답셋_v3_점검결과_DR.json"

# ---- reuse index v2 definitions and evidence units (no files are written by this part)
src = open(SC + "build_index_v2.py", encoding="utf-8").read().split("# ---------------- aggregate index ----------------")[0]
ns = {}
exec(src, ns)
UNITS, MEM_LINKS = ns["UNITS"], ns["links"]
codes, eq_hits, MATCH, EQ, HZ = ns["codes"], ns["eq_hits"], ns["MATCH"], ns["EQ"], ns["HZ"]
split_components, SECTION_EQ = ns["split_components"], ns["SECTION_EQ"]
norm = lambda s: re.sub(r"\s+", "", s or "")

LINKS = [json.loads(l) for l in open(KB + "261116_RAG_기기위험요인링크_v2_DR.jsonl", encoding="utf-8")]
IX = json.load(open(KB + "261116_RAG_기기위험요인인덱스_v2_DR.json", encoding="utf-8"))
CHUNKS = [json.loads(l) for l in open(KB + "261115_RAG_청크_v1_DR.jsonl", encoding="utf-8")]
TB = {json.loads(l)["row_id"]: json.loads(l) for l in open(KB + "261115_RAG_구조화표_v1_DR.jsonl", encoding="utf-8")}
MASTER = json.load(open(ROOT + "261115_기기마스터_인식평가셋_DR/261115_기기마스터_v1_DR.json", encoding="utf-8"))
QA = {}
key = lambda l: (l["equipment_id"], l["hazard_code"], l["source_id"], norm(l["hazard_text"]))
QA["links_reproduced_equal_saved"] = sorted(map(key, MEM_LINKS)) == sorted(map(key, LINKS))
UNIT = {u["source_id"]: u for u in UNITS if not u.get("excluded")}

# ---- v2 index as a retrieval target: S[eid][code][source_id] = best tier
S = collections.defaultdict(lambda: collections.defaultdict(dict))
for l in LINKS:
    d = S[l["equipment_id"]][l["hazard_code"]]
    d[l["source_id"]] = min(d.get(l["source_id"], "Z"), l["evidence_tier"])
IX_ORDER = {e["equipment_id"]: [h["hazard_code"] for h in e["hazards"]] for e in IX["index"]}


def retrieve(eids, excl=frozenset()):
    """Same rule as the pipeline's R_index_v2: CASE-* sources dropped, tier A first, then more sources.
    Multi-equipment: per code, best tier and the number of distinct sources over the query equipment."""
    agg, order = {}, []
    for e in eids:
        for c in IX_ORDER.get(e, []):
            srcs = {s: t for s, t in S[e][c].items() if not s.startswith("CASE-") and s not in excl}
            if not srcs:
                continue
            if c not in agg:
                agg[c] = {}; order.append(c)
            for s, t in srcs.items():
                agg[c][s] = min(agg[c].get(s, "Z"), t)
    return sorted(order, key=lambda c: (min(agg[c].values()), -len(agg[c])))


pipe = json.load(open(PIPE_RANKED, encoding="utf-8"))["ranked"]["R_index_v2"]
QA["retrieval_replica_vs_pipeline_R_index_v2"] = {
    "equal": sum(1 for e, r in pipe.items() if retrieve([e]) == r), "total": len(pipe),
    "differs": {e: {"pipeline": r, "replica": retrieve([e])} for e, r in pipe.items() if retrieve([e]) != r}}


def supported(eid, code, excl=frozenset(), with_case=True):
    return any((with_case or not s.startswith("CASE-")) and s not in excl for s in S[eid].get(code, {}))


# ---- per-unit hazard attribution (same rule as the link generation)
def unit_hazards(u):
    task_eq = [] if u.get("task_label_usable") is False else (SECTION_EQ.get(u["task"]) or eq_hits(u["task"], u["source_id"]))
    hz = [c for h in u["hazards"] for c in (split_components(h) if u["source_type"] == "d5_visual" else [h])]
    out = []
    for h in hz:
        cs = [c for c, _ in codes(h)]
        named = [e for e, _ in eq_hits(h, u["source_id"])]
        out.append({"text": h, "codes": cs, "named_eq": named, "task_eq": [e for e, _ in task_eq]})
    return out


UNIT_LINKS = collections.defaultdict(list)
for l in LINKS:
    UNIT_LINKS[l["source_id"]].append(l)

# ---- sources -> retrieval artefacts (for leakage flags and the holdout list)
CHUNK_BY_PAGE = collections.defaultdict(list)
for c in CHUNKS:
    CHUNK_BY_PAGE[(c["source_file"], c["pdf_page"])].append(c["chunk_id"])
CH_NORM = {c["chunk_id"]: norm(c["text"]) for c in CHUNKS}
MASTER_REFS = []  # (equipment_id, code, evidence, locator, src, page)
for e in MASTER["equipment"]:
    for h in e["related_hazards"]:
        for r in h["refs"]:
            MASTER_REFS.append((e["equipment_id"], h["code"], h["evidence"], r.get("locator") or "", r.get("src"), r.get("page")))
DOC_OF = {c["source_file"]: c["doc_id"] for c in CHUNKS}


def artefacts(sid):
    """retrieval artefacts that carry this source unit's text"""
    a = {"v2_link_source_id": sid if sid in UNIT_LINKS else None, "v2_link_ids": [l["link_id"] for l in UNIT_LINKS.get(sid, [])],
         "v1_table_row_ids": [sid] if sid in TB else [], "v1_chunk_ids": [], "master_v1_refs": []}
    u = UNIT.get(sid)
    if u:
        for p in u["pages"]:
            a["v1_chunk_ids"] += CHUNK_BY_PAGE.get((u["source_file"], p), [])
        doc = DOC_OF.get(u["source_file"])
        for (e, c, ev, loc, s, p) in MASTER_REFS:
            if loc == sid or loc in a["v1_chunk_ids"] or (doc and s == doc and p in u["pages"]):
                a["master_v1_refs"].append(f"{e}/{c}/{loc or f'{s} p{p}'}")
    a["v1_chunk_ids"] = sorted(set(a["v1_chunk_ids"]))
    a["master_v1_refs"] = sorted(set(a["master_v1_refs"]))
    return a


def text_in_chunks(t):
    k = norm(t)[:20]
    return sorted(cid for cid, x in CH_NORM.items() if k and k in x)


# ---- lexical near-misses: an equipment word inside another word or another machine (documented on v2 review)
LOOSE = {"EQ_KNIFE_BOARD": (r"알칼리|칼날|칼슘", "'칼'이 다른 낱말 안에 있음"),
         "EQ_DUMBWAITER": (r"리프트", "'리프트'가 다른 문맥(사다리 등)에 쓰임"),
         "EQ_MIXER": (r"원두 분쇄기|얼음 분쇄기", "'분쇄기'가 커피·얼음 분쇄 기계를 가리킴"),
         "EQ_GAS_RANGE": (r"전자레인지", "'레인지'가 전자레인지를 가리킴")}
NEAR_MISS = collections.defaultdict(list)  # eid -> [(sid, text, codes, why)]
for sid, u in UNIT.items():
    for h in unit_hazards(u):
        for e, (rx, why) in LOOSE.items():
            if re.search(rx, h["text"]) and e not in h["named_eq"] and e not in h["task_eq"]:
                NEAR_MISS[e].append((sid, h["text"], h["codes"], why))

IND = {"chicken": "치킨", "bunsik": "분식", "cafe": "카페", "korean": "한식", "other": "기타"}
D8_IND = {"한식": "korean", "치킨": "chicken", "커피": "cafe", "중식": "other", "피자": "other", "제과제빵": "other"}
M_IND = {e["equipment_id"]: [x["industry"] for x in e.get("industry_lists") or e.get("industries") or []] for e in MASTER["equipment"]}
for e in MASTER["equipment"]:
    M_IND[e["equipment_id"]] = [x["industry"] for x in (e.get("industries") or [])] or M_IND[e["equipment_id"]]
MASTER_CODES = {e["equipment_id"]: {h["code"]: h["evidence"] for h in e["related_hazards"]} for e in MASTER["equipment"]}


def ev_unit(sid, h=None):
    u = UNIT[sid]
    return {"source_id": sid, "source_type": u["source_type"], "source_file": u["source_file"], "pdf_pages": u["pages"],
            "task_or_section": u["task"], "text": h}


Q = []


def add(tier, types, eids, surfaces, gold_ev, industry, industry_basis, note=None, work=None, extra=None, prov=None):
    """gold_ev: list of (code, role, evidence dict)"""
    gold, gb = collections.OrderedDict(), collections.defaultdict(set)
    for c, role, ev in gold_ev:
        g = gold.setdefault(c, {"hazard_code": c, "hazard_name": HZ[c], "role": role, "evidence": []})
        if role == "equipment":
            g["role"] = "equipment"
        if ev not in g["evidence"]:
            g["evidence"].append(ev)
        for e in ev.get("_eq", []):
            gb[e].add(c)
    for g in gold.values():
        for ev in g["evidence"]:
            ev.pop("_eq", None)
    q = {"tier": tier, "types": list(dict.fromkeys(types)), "industry": industry, "industry_name": IND.get(industry, industry),
         "industry_basis": industry_basis, "query": {"equipment_ids": eids, "surface_terms": surfaces, "site_note": note, "work_label": work},
         "gold": list(gold.values()), "gold_by_equipment": {e: sorted(v) for e, v in gb.items()}, "provenance": prov or {}}
    q.update(extra or {})
    Q.append(q)
    return q


# =============== G tier: one query per linked source unit ===============
per_eq_single = collections.Counter()
SINGLE_CAP = 6
syn_turn = collections.Counter()


def surface_for(e, unit_term, want_syn):
    """standard name, or a master synonym that differs from the term written in the source"""
    if not want_syn:
        return EQ[e]["standard_name"], None
    syns = [s for s in EQ[e].get("synonyms", []) if norm(s) != norm(unit_term) and norm(s) not in norm(EQ[e]["standard_name"])]
    if not syns:
        return EQ[e]["standard_name"], None
    s = syns[syn_turn[e] % len(syns)]
    syn_turn[e] += 1
    return s, {"surface": s, "origin": "기기마스터 v1 동의어", "source_term": unit_term,
               "matches_index_regex": bool(re.search(MATCH[e], s))}


common_turn = collections.Counter()
order = sorted(UNIT_LINKS, key=lambda s: (UNIT[s]["source_type"] if s in UNIT else "zz", s))
for sid in order:
    if sid.startswith("CASE-") or sid not in UNIT:
        continue
    u, ls = UNIT[sid], UNIT_LINKS[sid]
    eids = list(dict.fromkeys(l["equipment_id"] for l in ls))
    hz = unit_hazards(u)
    if len(eids) > 4:  # keep the 4 equipment with most distinct codes in this unit
        eids = sorted(eids, key=lambda e: -len({l["hazard_code"] for l in ls if l["equipment_id"] == e}))[:4]
    if len(eids) == 1 and per_eq_single[eids[0]] >= SINGLE_CAP:
        continue
    types = ["single_equipment" if len(eids) == 1 else "multi_equipment"]
    gold_ev = []
    for l in ls:
        if l["equipment_id"] in eids:
            ev = ev_unit(sid, l["hazard_text"]); ev["link_id"] = l["link_id"]; ev["_eq"] = [l["equipment_id"]]
            gold_ev.append((l["hazard_code"], "equipment", ev))
    combo = [h for h in hz if len(set(h["named_eq"]) & set(eids)) >= 2 and h["codes"]]
    if combo:
        types.append("equipment_combination")
    # context: unit hazards not attributed to any equipment, with codes not yet gold
    gcodes = {c for c, _, _ in gold_ev}
    ctx = [h for h in hz if h["codes"] and not h["named_eq"] and not h["task_eq"] and set(h["codes"]) - gcodes]
    note, ctx_note_src = None, None
    ctx_turn = sum(1 for x in Q if "context_widen" in x["types"] or "_ctx_skipped" in x)
    if ctx and ctx_turn % 2 == 1:
        ctx = []  # leave this one without a site note: the same unattributed hazards become hard-negative candidates
        skipped_ctx = True
    else:
        skipped_ctx = False
    if ctx:
        ctx = ctx[:2]
        note = " / ".join(h["text"] for h in ctx)
        for h in ctx:
            for c in h["codes"]:
                if c not in gcodes:
                    ev = ev_unit(sid, h["text"]); ev["context_quote"] = True
                    gold_ev.append((c, "context", ev))
        types.append("context_widen")
        ctx_note_src = "원문 위험요인 문장 그대로(기기명 없음)"
    elif len(eids) == 1:
        full = retrieve(eids, frozenset({sid}))
        if len(set(full) - gcodes) >= 2 and u.get("task_label_usable") is not False:
            note = u["task"] if u["source_type"] != "checklist" else f'{u["task"]} — {u["hazards"][0]}'
            types.append("context_narrow")
            ctx_note_src = "원문 작업명·점검항목 그대로"
    # surface: alternate standard name / master synonym per equipment
    surfaces, syn_info = [], []
    for e in eids:
        term = next(l["equipment_match"]["term"] for l in ls if l["equipment_id"] == e)
        s, info = surface_for(e, term, want_syn=(per_eq_single[e] + len(Q)) % 2 == 1)
        surfaces.append(s)
        if info:
            syn_info.append(dict(info, equipment_id=e))
    if syn_info:
        types.append("synonym_surface")
    if u["source_type"] == "d8_table":
        ind, basis = D8_IND[u["industry"]], f"D8 업종 표 '{u['industry']}'"
    else:
        cands = [i for i in ("bunsik", "korean", "chicken", "cafe", "other") if all(i in M_IND.get(e, []) for e in eids)] or ["other"]
        ind = min(cands, key=lambda i: common_turn[i]); common_turn[ind] += 1
        basis = "업종 공통 출처(점검표·안내서) + 기기마스터 업종 목록으로 배정(AI 보조)"
    q = add("G", types, eids, surfaces, gold_ev, ind, basis, note=note,
            prov={"gold_source": "안내서·점검표 원문(규칙 라벨)", "anchor_sources": [sid], "site_note_origin": ctx_note_src,
                  "synonym": syn_info or None, "ai_assisted": ["질의 문장 틀", "위험 코드 규칙 라벨"] + (["업종 배정"] if "AI 보조" in basis else [])})
    q["_hz"] = {sid: hz}
    if skipped_ctx:
        q["_ctx_skipped"] = True
    if len(eids) == 1:
        per_eq_single[eids[0]] += 1

# =============== G tier: store scenarios (several equipment from several rows of one industry) ===============
SCEN = [
    ("치킨", ["EQ_FRYER", "EQ_KNIFE_BOARD", "EQ_MOTORCYCLE"]),
    ("치킨", ["EQ_REFRIGERATOR", "EQ_SHELF", "EQ_CART"]),
    ("한식", ["EQ_GAS_RANGE", "EQ_SOUP_KETTLE", "EQ_EXHAUST_HOOD"]),
    ("한식", ["EQ_KNIFE_BOARD", "EQ_RICE_WASHER", "EQ_RICE_COOKER"]),
    ("커피", ["EQ_COFFEE_MACHINE", "EQ_REFRIGERATOR", "EQ_EXHAUST_HOOD"]),
    ("커피", ["EQ_ELECTRIC_PANEL", "EQ_SHELF", "EQ_CART"]),
    ("피자", ["EQ_OVEN", "EQ_DOUGH_MIXER", "EQ_DUMBWAITER"]),
    ("중식", ["EQ_DOUGH_MIXER", "EQ_VEG_CUTTER", "EQ_WASTE_OIL_CONTAINER"]),
    ("제과제빵", ["EQ_OVEN", "EQ_FRYER", "EQ_DOUGH_MIXER"]),
]
for d8ind, eids in SCEN:
    ind = D8_IND[d8ind]
    rows = [s for s, u in UNIT.items() if u["source_type"] == "d8_table" and u["industry"] == d8ind]
    gold_ev, used = [], []
    for s in rows:
        for l in UNIT_LINKS.get(s, []):
            if l["equipment_id"] in eids:
                ev = ev_unit(s, l["hazard_text"]); ev["link_id"] = l["link_id"]; ev["_eq"] = [l["equipment_id"]]
                gold_ev.append((l["hazard_code"], "equipment", ev)); used.append(s)
    have = {ev["_eq"][0] for _, _, ev in gold_ev}
    eids_ok = [e for e in eids if e in have]
    if len(eids_ok) < 2:
        QA.setdefault("scenarios_skipped", []).append({"industry": ind, "equipment": eids, "with_evidence": eids_ok})
        continue
    used = list(dict.fromkeys(used))
    q = add("G", ["multi_equipment", "store_scenario"], eids_ok, [EQ[e]["standard_name"] for e in eids_ok], gold_ev, ind,
            f"D8 업종 표 '{d8ind}' 여러 행. 기기 조합은 AI 보조로 고름",
            prov={"gold_source": "안내서 업종 표 여러 행(규칙 라벨)", "anchor_sources": used, "ai_assisted": ["기기 조합 선택", "질의 문장 틀", "위험 코드 규칙 라벨"]})
    q["_hz"] = {s: unit_hazards(UNIT[s]) for s in used}

# 분식: no industry-specific source. Scenarios from common sources (checklist / D5) for equipment the master lists for 분식.
BUNSIK = [["EQ_FRYER", "EQ_GAS_CYLINDER", "EQ_KNIFE_BOARD"], ["EQ_MIXER", "EQ_DISHWASHER", "EQ_REFRIGERATOR"],
          ["EQ_MOTORCYCLE", "EQ_ELECTRIC_PANEL", "EQ_LADDER"]]
for eids in BUNSIK:
    gold_ev, used = [], []
    for l in LINKS:
        if l["equipment_id"] in eids and l["source_type"] in ("checklist", "d5_visual"):
            ev = ev_unit(l["source_id"], l["hazard_text"]); ev["link_id"] = l["link_id"]; ev["_eq"] = [l["equipment_id"]]
            gold_ev.append((l["hazard_code"], "equipment", ev)); used.append(l["source_id"])
    eids_ok = [e for e in eids if any(l["equipment_id"] == e and l["source_type"] in ("checklist", "d5_visual") for l in LINKS)]
    if len(eids_ok) < 2:
        QA.setdefault("scenarios_skipped", []).append({"industry": "bunsik", "equipment": eids, "with_evidence": eids_ok})
        continue
    used = list(dict.fromkeys(used))
    q = add("G", ["multi_equipment", "store_scenario"], eids_ok, [EQ[e]["standard_name"] for e in eids_ok], gold_ev, "bunsik",
            "분식 전용 출처 없음. 업종 공통 출처(점검표·D5) + 기기마스터 업종 목록(분식). AI 보조 배정",
            prov={"gold_source": "점검표·안내서 업종 공통 항목(규칙 라벨)", "anchor_sources": used,
                  "ai_assisted": ["업종 배정", "기기 조합 선택", "질의 문장 틀", "위험 코드 규칙 라벨"]})
    q["_hz"] = {s: unit_hazards(UNIT[s]) for s in used}

# =============== R tier: real records ===============
S01 = "261113_restaurant_completed_assessments_DR/261113_노인인력개발원_안전보건관리에센스_원본_DR.pdf"
S02 = "261113_restaurant_completed_assessments_DR/261113_난정평화교육원_2025_위험성평가결과_원본_DR.pdf"
S03 = "261113_restaurant_completed_assessments_DR/261113_KOSHA_2024_위험성평가우수사례_원본_DR.pdf"
P14F = "261113_본사컨설팅_평가완료표_조사_DR/261113_학교급식_안전보건관리대책_2014_공개원문_DR.pdf"


def rec(rid, f, pages, text, measure=None, extra=None):
    d = {"source_id": rid, "source_type": "real_record", "source_file": f, "pdf_pages": pages, "text": text, "measure_text": measure}
    d.update(extra or {})
    return d


def case(cid):
    r = TB["CASE-" + cid]
    return rec("CASE-" + cid, r["source_file"], [r["source_pdf_page"]], r["hazard_text"], r["improvement_measure"],
               {"transcription": r["source_text_method"]})


def coded(ev, eids=(), role="equipment", only=None):
    out = []
    for c, _ in codes(ev["text"]):
        if only and c not in only:
            continue
        e = dict(ev); e["_eq"] = list(eids)
        out.append((c, role, e))
    return out


NJ_SINK = rec("NJ_CAFE_SINK", S02, [22, 35, 41], "꽃우물까페 씽크대 물이 너무 뜨거워 화상 위험(청소실무원 의견)",
              "-온수조절기 낮춤으로 조절 -더운물 사용 시 내열성 장갑 착용 권고 (p41: -온수밸브 조절하여 개선 완료)",
              {"transcription": "pdftotext -layout(p22·p35·p41)", "completion": "완료일 25.04.04(p35)"})
OKGYE = rec("KOSHA24_OKGYE", S03, [35, 37],
            "메뉴·공정 축소로 넘어짐·베임사고 예방, 근골격계 질환 예방을 위해 무거운 그릇은 경량화, 조리화 대신 안전화로 미끄러짐 사고를 예방하고 있습니다.",
            "그릇 경량화(624g → 173g) 조리화를 안전화로 교체(p37)",
            {"transcription": "pdftotext 텍스트(p35 요약 문단, p37 개선 사례 제목). 이미지 대조 미실시",
             "site": "고속도로 휴게소 식당(음식 및 숙박업, 29명)"})
R_ITEMS = [
    (["single_equipment", "synonym_surface", "real_record"], ["EQ_ELECTRIC_PANEL"], ["멀티탭"], [case("FOOD_A_01"), case("FOOD_A_04")],
     "other", None, None, "원문 표현 '멀티탭'(기기마스터 동의어). A사업단 음식점"),
    (["single_equipment", "synonym_surface", "real_record"], ["EQ_GAS_CYLINDER"], ["LPG 용기"], [case("FOOD_A_02")],
     "other", None, None, "원문 표현 'LPG 용기'(기기마스터 동의어)"),
    (["multi_equipment", "equipment_combination", "real_record"], ["EQ_ELECTRIC_PANEL", "EQ_GAS_CYLINDER"], ["멀티탭·전선", "LPG 용기"],
     [case("FOOD_A_01"), case("FOOD_A_02"), case("FOOD_A_04")], "other", None, None, "같은 사업장(A사업단) 기록 3건을 묶은 기기 조합 질의"),
    (["work_or_place", "real_record"], [], [], [case("CAFE_B_01")], "cafe", None, "매장 출입문 통행", "기기마스터에 출입문 ID 없음"),
    (["single_equipment", "real_record"], ["EQ_ELECTRIC_PANEL"], ["분전반"], [case("KITCHEN_N_01"), case("KITCHEN_N_02")],
     "other", None, None, "급식실 분전반 기록 2건(같은 사업장)을 질의 1개로"),
    (["single_equipment", "synonym_surface", "real_record"], ["EQ_SINK"], ["씽크대"], [NJ_SINK], "cafe", None, None,
     "원문 표기 '씽크대'는 기기마스터 동의어에 없음(현장 표기)"),
    (["work_or_place", "multi_answer", "real_record"], [], [], [OKGYE], "other", None, "고속도로 휴게소 식당 조리·배식(그릇 운반)",
     "KOSHA 2024 우수사례 요약 문단(평가 결과 개선 내용). 표 형식 원본 아님"),
]
for types, eids, surf, evs, ind, note, work, memo in R_ITEMS:
    gold_ev = [x for ev in evs for x in coded(ev, eids)]
    # FOOD_A_04 names wires and gas piping together: gas code attributed to the combination
    add("R", types, eids, surf, gold_ev, ind, "실제 기록의 사업장 업종", note=note, work=work,
        prov={"gold_source": "실제 위험성평가 기록(규칙 라벨)", "anchor_sources": [e["source_id"] for e in evs], "memo": memo,
              "ai_assisted": ["질의 문장 틀", "위험 코드 규칙 라벨", "기기 ID 대응"]})

# =============== P tier: 2014 published example assessment (school-meal guide, anonymous restaurant) ===============
gs = open(SC + "build_goldset_v2.py", encoding="utf-8").read()
pns = {"P14": P14F}  # p14() rows copied from the v2 script (p77-p78 image-checked, p79-p80 text)
exec(gs[gs.index("# ---- P tier evidence"):gs.index("PI = {")], pns)
P14 = {e["record_id"]: e for e in pns["P"]}


def p14ev(rid):
    e = P14[rid]
    return rec(rid, P14F, [e["pdf_page"]], e["hazard_text"], e["measure_text"],
               {"work_area": e["work_area"], "current_control": e["current_control"], "scores": e["scores"], "transcription": e["transcription"]})


P_ITEMS = [
    (["single_equipment", "synonym_surface"], ["EQ_MIXER"], ["분쇄기"], ["P14-01", "P14-02"], "other", None, None),
    (["single_equipment"], ["EQ_KNIFE_BOARD"], ["칼"], ["P14-13"], "other", None, None),
    (["single_equipment", "synonym_surface"], ["EQ_MOTORCYCLE"], ["오토바이"], ["P14-24"], "other", None, None),
    (["work_or_place", "multi_answer"], [], [], [f"P14-{i:02d}" for i in range(1, 17)], "other", None, "조리실(주방) 작업"),
    (["work_or_place", "multi_answer"], [], [], [f"P14-{i:02d}" for i in range(17, 23)], "other", None, "홀서비스 작업"),
    (["work_or_place", "multi_answer"], [], [], [f"P14-{i:02d}" for i in range(23, 30)], "other", None, "배달 작업"),
    (["multi_equipment", "context_widen"], ["EQ_MIXER", "EQ_KNIFE_BOARD"], ["분쇄기", "칼"], ["P14-01", "P14-02", "P14-13"], "other",
     "물청소시 전기감전 위험 / 물기로 인해 바닥에서 미끄러져 넘어짐", None),
]
for types, eids, surf, rids, ind, note, work in P_ITEMS:
    evs = [p14ev(r) for r in rids]
    gold_ev = [x for ev in evs for x in coded(ev, eids)]
    if note:
        for r in ("P14-06", "P14-05"):
            gold_ev += coded(p14ev(r), (), role="context")
    add("P", types, eids, surf, gold_ev, ind, "공개 예시 평가표(익명 음식점, 2012-08-01 평가)", note=note, work=work,
        prov={"gold_source": "공개 예시 위험성평가표(규칙 라벨). 실제 이행·승인 미확인", "anchor_sources": rids + (["P14-05", "P14-06"] if note else []),
              "site_note_origin": "원문 위험요인 문장 그대로" if note else None,
              "ai_assisted": ["질의 문장 틀", "위험 코드 규칙 라벨", "기기 ID 대응"]})

# =============== negatives, extras, ranks, leakage ===============
# confusable equipment pairs (AI-assisted choice: similar name, similar place, or similar machine). Used only for hard negatives.
_PAIRS = [("EQ_REFRIGERATOR", "EQ_WALKIN_COOLER"), ("EQ_MIXER", "EQ_DOUGH_MIXER"), ("EQ_MIXER", "EQ_COFFEE_GRINDER"), ("EQ_MIXER", "EQ_ICE_CRUSHER"),
          ("EQ_GAS_RANGE", "EQ_MICROWAVE"), ("EQ_GAS_RANGE", "EQ_GAS_CYLINDER"), ("EQ_FRYER", "EQ_WASTE_OIL_CONTAINER"), ("EQ_FRYER", "EQ_GAS_RANGE"),
          ("EQ_SOUP_KETTLE", "EQ_STEAMER"), ("EQ_SOUP_KETTLE", "EQ_RICE_COOKER"), ("EQ_KNIFE_BOARD", "EQ_VEG_CUTTER"), ("EQ_KNIFE_BOARD", "EQ_MEAT_SLICER"),
          ("EQ_KNIFE_BOARD", "EQ_SCISSORS"), ("EQ_SINK", "EQ_DISHWASHER"), ("EQ_LADDER", "EQ_SHELF"), ("EQ_LADDER", "EQ_DUMBWAITER"), ("EQ_CART", "EQ_DUMBWAITER"),
          ("EQ_COFFEE_MACHINE", "EQ_WATER_HEATER"), ("EQ_OVEN", "EQ_GRILL"), ("EQ_EXHAUST_HOOD", "EQ_GAS_RANGE"),
          ("EQ_VEG_CUTTER", "EQ_MEAT_SLICER"), ("EQ_DOUGH_MIXER", "EQ_NOODLE_MACHINE"), ("EQ_ELECTRIC_PANEL", "EQ_GAS_CYLINDER"), ("EQ_RICE_WASHER", "EQ_SINK")]
CONFUSABLE = collections.defaultdict(list)
for a, b in _PAIRS:
    CONFUSABLE[a].append(b); CONFUSABLE[b].append(a)
for i, q in enumerate(Q, 1):
    q["query_id"] = f"Q3-{i:03d}"
    eids = q["query"]["equipment_ids"]
    gcodes = [g["hazard_code"] for g in q["gold"]]
    anchors = q["provenance"]["anchor_sources"]
    neg = collections.OrderedDict()
    if eids:
        # N1: same source attributes the code to another named equipment; no v2 link supports it for any query equipment
        for sid, hz in q.get("_hz", {}).items():
            for h in hz:
                others = [e for e in h["named_eq"] if e not in eids]
                if not others or set(h["named_eq"]) & set(eids):
                    continue
                for c in h["codes"]:
                    if c in gcodes or any(supported(e, c) for e in eids):
                        continue
                    n = neg.setdefault(c, {"hazard_code": c, "hazard_name": HZ[c], "type": "same_source_other_equipment", "evidence": []})
                    n["evidence"].append({"source_id": sid, "text": h["text"], "attributed_to": others})
        # N1b: in the same source unit, a v2 link gives the code to another equipment
        for sid in anchors:
            for l in UNIT_LINKS.get(sid, []):
                c = l["hazard_code"]
                if l["equipment_id"] in eids or c in gcodes or any(supported(e, c) for e in eids):
                    continue
                n = neg.setdefault(c, {"hazard_code": c, "hazard_name": HZ[c], "type": "same_source_other_equipment", "evidence": []})
                if not any(x["source_id"] == sid and x["text"] == l["hazard_text"] for x in n["evidence"]):
                    n["evidence"].append({"source_id": sid, "text": l["hazard_text"], "attributed_to": [l["equipment_id"]], "link_id": l["link_id"]})
        # N2: same source, hazard sentence names no equipment, query has no site note quoting it
        if not q["query"]["site_note"]:
            for sid, hz in q.get("_hz", {}).items():
                for h in hz:
                    if h["named_eq"] or h["task_eq"]:
                        continue
                    for c in h["codes"]:
                        if c in gcodes or any(supported(e, c) for e in eids):
                            continue
                        n = neg.setdefault(c, {"hazard_code": c, "hazard_name": HZ[c], "type": "same_source_unattributed", "evidence": []})
                        n["evidence"].append({"source_id": sid, "text": h["text"], "why_plausible": "같은 출처(행·쪽)에 함께 적힌 위험. 기기명 없음. 현장 설명이 있으면 정답이 될 수 있음"})
        # N5: a confusable equipment (pair chosen by AI assistance) has tier-A evidence for the code
        for e in eids:
            for x in CONFUSABLE.get(e, []):
                for c, srcs in S[x].items():
                    a_src = [sid for sid, t in srcs.items() if t == "A" and not sid.startswith("CASE-")]
                    if not a_src or c in gcodes or any(supported(y, c) for y in eids):
                        continue
                    n = neg.setdefault(c, {"hazard_code": c, "hazard_name": HZ[c], "type": "confusable_equipment", "evidence": []})
                    l = next(l for l in LINKS if l["equipment_id"] == x and l["hazard_code"] == c and l["source_id"] == a_src[0])
                    n["evidence"].append({"source_id": l["source_id"], "text": l["hazard_text"], "attributed_to": [x], "link_id": l["link_id"],
                                          "why_plausible": f"혼동하기 쉬운 기기({EQ[x]['standard_name']})의 위험. 혼동 쌍은 AI 보조로 정함"})
        # N3: lexical near-miss of the query equipment's own name
        for e in eids:
            for sid, t, cs, why in NEAR_MISS.get(e, []):
                for c in cs:
                    if c in gcodes or any(supported(x, c) for x in eids):
                        continue
                    n = neg.setdefault(c, {"hazard_code": c, "hazard_name": HZ[c], "type": "lexical_near_miss", "evidence": []})
                    n["evidence"].append({"source_id": sid, "text": t, "why_plausible": why})
    unverified = []
    for c in list(neg):
        hit = {e: MASTER_CODES.get(e, {}).get(c) for e in eids if MASTER_CODES.get(e, {}).get(c)}
        if hit:  # the master lists it for a query equipment: not a clean negative
            unverified.append({"hazard_code": c, "master_v1_evidence": hit, "moved_from": neg.pop(c)["type"]})
    for n in neg.values():
        n["evidence"] = n["evidence"][:3]
        n["confidence"] = {"same_source_other_equipment": "중간", "same_source_unattributed": "중간", "lexical_near_miss": "중간",
                           "confusable_equipment": "낮음"}[n["type"]] + "(질의 기기에 대한 v2 근거 0건·기기마스터 미등재. 실제 비해당 여부는 검수 필요)"
    for e in eids:
        for c, ev in MASTER_CODES.get(e, {}).items():
            if c not in gcodes and not supported(e, c) and c not in [u["hazard_code"] for u in unverified]:
                unverified.append({"hazard_code": c, "master_v1_evidence": {e: ev}, "moved_from": None})
    q["hard_negatives"] = list(neg.values())
    q["unverified_master_only"] = unverified
    excl = frozenset(a for a in anchors if a in UNIT_LINKS)
    q["acceptable_extra_codes"] = sorted({c for e in eids for c in S[e] if c not in gcodes and supported(e, c, excl, with_case=False)})
    if q["hard_negatives"]:
        q["types"].append("hard_negative")
    if len(gcodes) >= 2 and "multi_answer" not in q["types"]:
        q["types"].append("multi_answer")
    # retrieval ranks with the v2 index (equipment resolved correctly)
    modes = {"strict_full": frozenset(), "leave_source_out": excl}
    q["retrieval_v2"] = {}
    for m, ex in modes.items():
        if not eids:
            q["retrieval_v2"][m] = None
            continue
        r = retrieve(eids, ex)
        q["retrieval_v2"][m] = {"ranked": r, "gold_ranks": {c: (r.index(c) + 1 if c in r else None) for c in gcodes},
                                "negatives_in_ranked": [c for c in r if c in neg]}
    syn = q["provenance"].get("synonym") or []
    if eids and any(not s["matches_index_regex"] for s in syn):
        q["retrieval_v2"]["note"] = "동의어 표면형 일부가 인덱스 v2 기기 정규식과 맞지 않음: " + ", ".join(s["surface"] for s in syn if not s["matches_index_regex"])

# split (holdout). Single-source G queries are grouped by shared anchors; groups go to test in hash order while
#   (1) every equipment that has v2 candidates keeps at least one non-held-out source, and (2) test G groups <= ~45%.
# Store scenarios (many rows) do not drive the split: test only if all their rows are already held out, else dev.
# R and P queries are always test (their records are not in the RAG target, except CASE-* which strict mode always drops).
parent = {}
def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
gq = [q for q in Q if q["tier"] == "G" and "store_scenario" not in q["types"]]
for q in gq:
    a = q["provenance"]["anchor_sources"]
    for s_ in a[1:]:
        parent[find(s_)] = find(a[0])
    find(a[0])
groups = collections.defaultdict(list)
for q in gq:
    groups[find(q["provenance"]["anchor_sources"][0])].append(q)
held, n_test = set(), 0
has_cand = [e for e in IX_ORDER if retrieve([e])]
for comp in sorted(groups, key=lambda c: hashlib.sha1(c.encode()).hexdigest()):
    srcs = {s_ for q in groups[comp] for s_ in q["provenance"]["anchor_sources"] if s_ in UNIT_LINKS}
    trial = frozenset(held | srcs)
    ok = all(retrieve([e], trial) for e in has_cand) and n_test + len(groups[comp]) <= 0.45 * len(gq)
    for q in groups[comp]:
        q["split"] = "test" if ok else "dev"
    if ok:
        held |= srcs; n_test += len(groups[comp])
for q in Q:
    if q["tier"] in ("R", "P"):
        q["split"] = "test"
    elif "store_scenario" in q["types"]:
        q["split"] = "test" if all(s_ in held for s_ in q["provenance"]["anchor_sources"]) else "dev"
test_src = {s_ for q in Q if q["split"] == "test" for s_ in q["provenance"]["anchor_sources"]}
HOLD = frozenset(s for s in test_src if s in UNIT_LINKS)

for q in Q:
    eids = q["query"]["equipment_ids"]
    gcodes = [g["hazard_code"] for g in q["gold"]]
    if eids:
        r = retrieve(eids, HOLD)
        q["retrieval_v2"]["global_holdout"] = {"ranked": r, "gold_ranks": {c: (r.index(c) + 1 if c in r else None) for c in gcodes}}
    arts = [artefacts(s) for s in q["provenance"]["anchor_sources"]]
    texts = [ev["text"] for g in q["gold"] for ev in g["evidence"] if ev.get("text")]
    in_chunks = sorted({c for t in texts for c in text_in_chunks(t)})
    lk = {"anchor_in_v2_links": sorted({a["v2_link_source_id"] for a in arts if a["v2_link_source_id"]}),
          "anchor_in_v1_table": sorted({x for a in arts for x in a["v1_table_row_ids"]}),
          "anchor_in_v1_chunks": sorted({x for a in arts for x in a["v1_chunk_ids"]} | set(in_chunks)),
          "anchor_in_master_v1_refs": sorted({x for a in arts for x in a["master_v1_refs"]})}
    any_leak = any(lk.values())
    lk["same_source_in_rag_target"] = any_leak
    lk["level"] = ("높음(dev: 정답 출처가 검색 대상에 남음. 질의별 eval_exclude로 빼면 중간)" if q["split"] == "dev" and any_leak else
                   "중간(test: 제외목록 적용 시 같은 출처는 빠지나 같은 문서의 다른 쪽·근접 문장은 남음)" if any_leak else
                   "낮음(정답 출처 원문이 검색 대상에 없음)")
    q["leakage"] = lk
    q["eval_exclude"] = {"v2_link_source_ids": lk["anchor_in_v2_links"], "v1_table_row_ids": lk["anchor_in_v1_table"],
                         "v1_chunk_ids": lk["anchor_in_v1_chunks"], "case_rows_always": "CASE-*"}
    q["gold_hazard_codes"] = gcodes
    sf = ", ".join(q["query"]["surface_terms"]) if q["query"]["surface_terms"] else None
    head = f"[{q['industry_name']}] "
    if sf:
        txt = head + f"기기: {sf}. 이 기기에 대해 평가할 위험요인을 추천해 주세요."
    else:
        txt = head + f"작업·장소: {q['query']['work_label']}. 평가할 위험요인을 추천해 주세요."
    if q["query"]["site_note"]:
        txt += f" 현장 설명: {q['query']['site_note']}"
    q["query"]["text"] = txt
    q["query"]["equipment_ids_given_to_system"] = "synonym_surface" not in q["types"]
    q["review_status"] = "AI 보조, 검수 전"
    q.pop("_hz", None)

# n-th rank tags
for q in Q:
    lso = q["retrieval_v2"].get("leave_source_out") if q["query"]["equipment_ids"] else None
    if lso and len(q["gold_hazard_codes"]) >= 2 and any(v != 1 for v in lso["gold_ranks"].values()):
        q["types"].append("gold_not_all_rank1")
    if lso and any(v is None for v in lso["gold_ranks"].values()):
        q["types"].append("gold_unretrievable_after_holdout")
    q["types"] = list(dict.fromkeys(q["types"]))

FIELDS = ["query_id", "split", "tier", "types", "industry", "industry_name", "industry_basis", "query", "gold_hazard_codes", "gold",
          "gold_by_equipment", "acceptable_extra_codes", "hard_negatives", "unverified_master_only", "retrieval_v2", "leakage",
          "eval_exclude", "provenance", "review_status"]
with open(OUT_JSONL, "w", encoding="utf-8", newline="\n") as f:
    for q in Q:
        f.write(json.dumps({k: q[k] for k in FIELDS}, ensure_ascii=False) + "\n")

# ---- holdout list
hold_arts = [artefacts(s) for s in sorted(HOLD)]
hold_chunks = sorted({x for a in hold_arts for x in a["v1_chunk_ids"]})
eq_lost = sorted(e for e in IX_ORDER if retrieve([e]) and not retrieve([e], HOLD))
json.dump({
    "created_kst": "2026-11-16", "purpose": "v3 정답셋 test 분할을 평가할 때 검색 대상에서 뺄 출처 목록",
    "how_to_use": ["인덱스 v2 검색: 링크의 source_id가 exclude.v2_link_source_ids에 있으면 버린다. CASE-* 출처는 항상 버린다(엄격 모드).",
                   "v1 구조화표 BM25: exclude.v1_table_row_ids 행과 모든 CASE-* 행을 뺀다.",
                   "v1 청크 BM25: exclude.v1_chunk_ids를 뺀다. 쪽 단위 청크라 같은 쪽의 다른 행도 함께 빠진다(부수 제외).",
                   "기기마스터 v1 기반 방법: exclude.master_v1_refs가 가리키는 근거는 누출 경로다. 마스터를 쓰는 방법은 test 점수를 따로 표시한다.",
                   "질의별로만 빼려면 각 질의의 eval_exclude(leave-source-out)를 쓴다."],
    "test_query_ids": [q["query_id"] for q in Q if q["split"] == "test"],
    "dev_query_ids": [q["query_id"] for q in Q if q["split"] == "dev"],
    "exclude": {"v2_link_source_ids": sorted(HOLD),
                "v2_link_ids": sorted({x for a in hold_arts for x in a["v2_link_ids"]}),
                "v1_table_row_ids": sorted({x for a in hold_arts for x in a["v1_table_row_ids"]}),
                "v1_chunk_ids": hold_chunks,
                "master_v1_refs": sorted({x for a in hold_arts for x in a["master_v1_refs"]}),
                "always": ["CASE-*"]},
    "effect_on_index_v2": {"links_total": len(LINKS), "links_removed": sum(1 for l in LINKS if l["source_id"] in HOLD),
                           "links_left_non_case": sum(1 for l in LINKS if l["source_id"] not in HOLD and not l["source_type"] == "case"),
                           "equipment_losing_all_candidates": eq_lost,
                           "v1_chunks_removed": len(hold_chunks), "v1_chunks_total": len(CHUNKS)},
    "not_in_rag_target": ["KOSHA24_OKGYE", "NJ_CAFE_SINK", "P14-*(2014 학교급식 자료)"],
}, open(OUT_HOLD, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)

# ---- review table (one row per query x candidate code)
with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["query_id", "split", "tier", "types", "industry", "query_text", "equipment_ids", "hazard_code", "hazard_name", "role",
                "rank_leave_source_out", "evidence_source_ids", "evidence_text", "source_files_pages", "status",
                "review_decision(정답/정답아님/보류)", "reviewer", "review_note"])
    for q in Q:
        lso = (q["retrieval_v2"].get("leave_source_out") or {}) if q["query"]["equipment_ids"] else {}
        rk = {c: i + 1 for i, c in enumerate(lso.get("ranked", []))}
        base = [q["query_id"], q["split"], q["tier"], "|".join(q["types"]), q["industry_name"], q["query"]["text"], "|".join(q["query"]["equipment_ids"])]
        for g in q["gold"]:
            ev = g["evidence"]
            w.writerow(base + [g["hazard_code"], g["hazard_name"], "정답(" + ("기기" if g["role"] == "equipment" else "현장설명") + ")",
                               rk.get(g["hazard_code"], ""), "|".join(e["source_id"] for e in ev), " / ".join(e.get("text") or "" for e in ev)[:600],
                               "|".join(f'{e["source_file"].split("/")[-1]} p{e["pdf_pages"]}' for e in ev[:3]), "AI 보조, 검수 전", "", "", ""])
        for n in q["hard_negatives"]:
            ev = n["evidence"]
            w.writerow(base + [n["hazard_code"], n["hazard_name"], "함정후보(추천하면 안 됨)", rk.get(n["hazard_code"], ""),
                               "|".join(e["source_id"] for e in ev), " / ".join(e["text"] + (f' [귀속: {",".join(e["attributed_to"])}]' if e.get("attributed_to") else f' [{e.get("why_plausible")}]') for e in ev)[:600],
                               "", "AI 보조, 검수 전", "", "", ""])
        for c in q["acceptable_extra_codes"]:
            w.writerow(base + [c, HZ[c], "허용(다른 출처 근거)", rk.get(c, ""), "", "", "", "AI 보조, 검수 전", "", "", ""])
        for u in q["unverified_master_only"]:
            w.writerow(base + [u["hazard_code"], HZ[u["hazard_code"]], "판정보류(기기마스터만)", rk.get(u["hazard_code"], ""), "",
                               json.dumps(u["master_v1_evidence"], ensure_ascii=False), "", "AI 보조, 검수 전", "", "", ""])

# ---- QA summary
C = collections.Counter
eqq = [q for q in Q if q["query"]["equipment_ids"]]
def nonfirst(mode):
    xs = [q for q in eqq if q["retrieval_v2"].get(mode)]
    return {"queries_with_equipment": len(xs),
            "queries_with_a_gold_not_rank1": sum(1 for q in xs if any(v != 1 for v in q["retrieval_v2"][mode]["gold_ranks"].values())),
            "ratio": round(sum(1 for q in xs if any(v != 1 for v in q["retrieval_v2"][mode]["gold_ranks"].values())) / len(xs), 3),
            "multi_answer_queries_with_gold_not_rank1": sum(1 for q in xs if len(q["gold_hazard_codes"]) >= 2 and any(v != 1 for v in q["retrieval_v2"][mode]["gold_ranks"].values())),
            "queries_with_unretrieved_gold": sum(1 for q in xs if any(v is None for v in q["retrieval_v2"][mode]["gold_ranks"].values())),
            "gold_rank_distribution": dict(sorted(C(str(v) for q in xs for v in q["retrieval_v2"][mode]["gold_ranks"].values()).items())),
            "R@3_macro_retrieval_only": round(sum(sum(1 for v in q["retrieval_v2"][mode]["gold_ranks"].values() if v and v <= 3) / len(q["gold_hazard_codes"]) for q in xs) / len(xs), 3),
            "P@3_macro_retrieval_only": round(sum(sum(1 for v in q["retrieval_v2"][mode]["gold_ranks"].values() if v and v <= 3) / 3 for q in xs) / len(xs), 3)}
def eqrole(mode, split=None):
    """ranks of gold codes whose role is 'equipment' (context codes cannot come from an equipment index by design)"""
    xs = [q for q in eqq if q["retrieval_v2"].get(mode) and (split is None or q["split"] == split)]
    rk = lambda q: {g["hazard_code"]: q["retrieval_v2"][mode]["gold_ranks"][g["hazard_code"]] for g in q["gold"] if g["role"] == "equipment"}
    xs = [q for q in xs if rk(q)]
    nf = [q for q in xs if any(v != 1 for v in rk(q).values())]
    return {"queries": len(xs), "with_equipment_gold_not_rank1": len(nf), "ratio": round(len(nf) / len(xs), 3) if xs else None,
            "with_unretrieved_equipment_gold": sum(1 for q in xs if any(v is None for v in rk(q).values())),
            "rank_distribution": dict(sorted(C(str(v) for q in xs for v in rk(q).values()).items())),
            "R@3_macro_retrieval_only": round(sum(sum(1 for v in rk(q).values() if v and v <= 3) / len(rk(q)) for q in xs) / len(xs), 3) if xs else None}


QA.update({
    "queries": len(Q), "by_split": dict(C(q["split"] for q in Q)), "by_tier": dict(C(q["tier"] for q in Q)),
    "by_type": dict(C(t for q in Q for t in q["types"]).most_common()),
    "by_industry": dict(C(q["industry_name"] for q in Q)),
    "by_industry_basis_ai": sum(1 for q in Q if "AI 보조" in q["industry_basis"]),
    "gold_count_distribution": dict(sorted(C(len(q["gold_hazard_codes"]) for q in Q).items())),
    "gold_codes_total": sum(len(q["gold_hazard_codes"]) for q in Q),
    "gold_role_counts": dict(C(g["role"] for q in Q for g in q["gold"])),
    "gold_code_frequency": dict(C(c for q in Q for c in q["gold_hazard_codes"]).most_common()),
    "hard_negatives_total": sum(len(q["hard_negatives"]) for q in Q),
    "queries_with_hard_negative": sum(1 for q in Q if q["hard_negatives"]),
    "hard_negative_types": dict(C(n["type"] for q in Q for n in q["hard_negatives"])),
    "negatives_moved_to_unverified_master": sum(1 for q in Q for u in q["unverified_master_only"] if u["moved_from"]),
    "equipment_coverage": dict(C(e for q in Q for e in q["query"]["equipment_ids"]).most_common()),
    "equipment_covered": len({e for q in Q for e in q["query"]["equipment_ids"]}),
    "evidence_source_type_distribution": dict(C((ev.get("source_type") or "?") for q in Q for g in q["gold"] for ev in g["evidence"])),
    "anchor_source_distribution": dict(C(s.split("-")[0] if not s.startswith("P14") else "P14" for q in Q for s in q["provenance"]["anchor_sources"])),
    "leakage_level": dict(C(q["leakage"]["level"].split("(")[0] for q in Q)),
    "queries_same_source_in_rag_target": sum(1 for q in Q if q["leakage"]["same_source_in_rag_target"]),
    "nonfirst_strict_full": nonfirst("strict_full"), "nonfirst_leave_source_out": nonfirst("leave_source_out"),
    "nonfirst_global_holdout": nonfirst("global_holdout"),
    "equipment_role_gold_only": {m: eqrole(m) for m in ("strict_full", "leave_source_out", "global_holdout")},
    "test_split_leave_source_out": eqrole("leave_source_out", split="test"),
    "synonym_queries_regex_unmatched": [q["query_id"] for q in Q if q["retrieval_v2"].get("note")] if True else None,
    "negatives_in_retrieval_ranked_strict": sum(len(q["retrieval_v2"]["strict_full"]["negatives_in_ranked"]) for q in eqq),
})
# integrity
QA["integrity"] = {
    "duplicate_query_ids": [k for k, v in C(q["query_id"] for q in Q).items() if v > 1],
    "unknown_codes": sorted({c for q in Q for c in q["gold_hazard_codes"] + [n["hazard_code"] for n in q["hard_negatives"]] if c not in HZ}),
    "negative_also_gold": [q["query_id"] for q in Q if set(q["gold_hazard_codes"]) & {n["hazard_code"] for n in q["hard_negatives"]}],
    "negative_supported_by_v2_for_query_eq": [q["query_id"] for q in Q for n in q["hard_negatives"] if any(supported(e, n["hazard_code"]) for e in q["query"]["equipment_ids"])],
    "gold_without_evidence": [q["query_id"] for q in Q for g in q["gold"] if not g["evidence"]],
    "queries_without_gold": [q["query_id"] for q in Q if not q["gold_hazard_codes"]],
    "gold_code_term_not_in_evidence_text": [(q["query_id"], g["hazard_code"]) for q in Q for g in q["gold"]
                                           if not any(g["hazard_code"] in [c for c, _ in codes(ev.get("text") or "")] for ev in g["evidence"])],
    "dev_nonscenario_anchor_overlapping_test": [q["query_id"] for q in Q if q["split"] == "dev" and "store_scenario" not in q["types"] and set(q["provenance"]["anchor_sources"]) & test_src],
    "dev_scenario_partly_on_test_rows(설계상 허용: dev는 전체 인덱스로 평가)": [q["query_id"] for q in Q if q["split"] == "dev" and "store_scenario" in q["types"] and set(q["provenance"]["anchor_sources"]) & test_src],
    "duplicate_gold_signature": [k for k, v in C((tuple(sorted(q["query"]["equipment_ids"])), tuple(sorted(q["gold_hazard_codes"])), tuple(sorted(q["provenance"]["anchor_sources"]))) for q in Q).items() if v > 1],
}
json.dump(QA, open(OUT_QA, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in QA.items() if k not in ("equipment_coverage", "gold_code_frequency")}, ensure_ascii=False, indent=1)[:12000])
