"""v2 gold set for equipment(or work) -> evaluated hazards, for Recall@K / Precision@K of hazard recommendation.

Tiers
  R : 실제 사업장 위험성평가 기록(공개본). S01 A·B사업단, S02 난정평화교육원.
  P : 공개 문서에 수록된 익명 음식점 위험성평가표 예시(2014 교육부 자료, 평가일 2012-08-01). 실제 이행·승인 미확인.
No synthetic (AI-made) gold item is created. AI assistance is limited to labeling: hazard_code (rule lexicon,
same as the index) and equipment_id mapping (literal synonym match, or marked 'AI 보조 후보').
Outputs: 261115_RAG_지식베이스_DR/261116_RAG_위험요인추천_정답셋_v2_DR.jsonl (+ evidence rows inside)
"""
import json, re, importlib.util

ROOT = r"<LOCAL_WORKSPACE>/"
KB = ROOT + "261115_RAG_지식베이스_DR/"
SC = r"<LOCAL_SCRATCH>/"
spec = importlib.util.spec_from_file_location("ix", SC + "build_index_v2.py")
# reuse lexicon/match without re-running outputs: exec only the definitions part
src = open(SC + "build_index_v2.py", encoding="utf-8").read().split("# ---------------- evidence units ----------------")[0]
ns = {}
exec(src, ns)
codes, eq_hits, MATCH = ns["codes"], ns["eq_hits"], ns["MATCH"]
norm = lambda s: re.sub(r"\s+", "", s or "")

S01 = "261113_restaurant_completed_assessments_DR/261113_노인인력개발원_안전보건관리에센스_원본_DR.pdf"
S02 = "261113_restaurant_completed_assessments_DR/261113_난정평화교육원_2025_위험성평가결과_원본_DR.pdf"
P14 = "261113_본사컨설팅_평가완료표_조사_DR/261113_학교급식_안전보건관리대책_2014_공개원문_DR.pdf"
cases = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT + "261113_restaurant_completed_assessments_DR/261113_실제사업장_위험성평가사례_8건_DR.jsonl", encoding="utf-8")}
v1 = {json.loads(l)["row_id"]: json.loads(l) for l in open(KB + "261115_RAG_구조화표_v1_DR.jsonl", encoding="utf-8")}


def case_ev(cid):
    r = v1["CASE-" + cid]; c = cases[cid]
    return {"record_id": cid, "source_file": r["source_file"], "pdf_page": r["source_pdf_page"],
            "hazard_text": r["hazard_text"], "measure_text": r["improvement_measure"], "current_control": None,
            "scores": {"before": c["before"], "after": c["after"]}, "transcription": r["source_text_method"],
            "project_review_status": c["project_review_status"]}


# ---- R tier evidence
NANJEONG_SINK = {"record_id": "NJ_CAFE_SINK", "source_file": S02, "pdf_page": [22, 35, 41],
                 "hazard_text": "꽃우물까페 씽크대 물이 너무 뜨거워 화상 위험(청소실무원 의견)",
                 "measure_text": "-온수조절기 낮춤으로 조절 -더운물 사용 시 내열성 장갑 착용 권고 (p41: -온수밸브 조절하여 개선 완료)",
                 "current_control": "온수조절기 점검",
                 "scores": {"before": {"likelihood": 3, "severity": 3, "score": 9}, "after": {"score": 3}},
                 "completion": "개선예정일 25.4.30, 완료일 25.04.04, 담당 관리과장(p35)",
                 "transcription": "pdftotext -layout(p22 청취조사표, p35 위험성평가표, p41 감소대책 실행)", "project_review_status": "v2 신규(8건 JSONL 밖)"}

# ---- P tier evidence (2014 example, pdf p77-80). p77·p78 이미지 대조, p79·p80 텍스트(-layout) 대조
def p14(no, page, area, haz, cur, l, s, red, cause):
    return {"record_id": f"P14-{no:02d}", "source_file": P14, "pdf_page": page, "work_area": area, "hazard_text": haz,
            "current_control": cur, "measure_text": red, "scores": {"likelihood": l, "severity": s, "score": l * s},
            "cause_category": cause, "transcription": "이미지 대조" if page in (77, 78) else "pdftotext -layout(이미지 미대조)"}

P = [
    p14(1, 77, "조리실/주방", "분쇄기에 손가락이 끼임", "고무장갑 착용", 3, 2, "1. 안전덮개 등 설치 2. 보조도구 사용", "1.1 협착위험 부분(감김, 끼임)"),
    p14(2, 77, "조리실/주방", "혼합기 칼날에 손가락 절단 위험", None, 3, 2, "1. 안전덮개 등 설치 2. 비상정지 스위치 설치 3. 보조도구 사용", "1.2 위험한 표면(절단, 베임, 긁힘)"),
    p14(3, 77, "조리실/주방", "뜨거운 냄비, 그릇, 조리기구에 의한 화상위험", None, 3, 2, "1. 보호장갑, 토시착용", "1.2 위험한 표면(절단, 베임, 긁힘)"),
    p14(4, 77, "조리실/주방", "주방 시설물 모서리에 충돌", "1. 모서리에 완충패드 부착", 2, 1, None, "1.4 충돌위험 부분"),
    p14(5, 77, "조리실/주방", "물기로 인해 바닥에서 미끄러져 넘어짐", "1. 조리실 정리정돈", 2, 2, "1. 청결상태 유지 2. 배수상태 정비", "1.5 넘어짐(미끄러짐, 걸림, 헛디딤)"),
    p14(6, 77, "조리실/주방", "물청소시 전기감전 위험", "1. 누전차단기 설치 2. 이중절연구조", 1, 3, None, "2.1 감전(안전전압초과)"),
    p14(7, 77, "조리실/주방", "뜨거운 국물에 의한 화상", "1. 장갑지급", 3, 2, "1. 이동대차 등의 설비 사용", "3.4 액체·미스트"),
    p14(8, 77, "조리실/주방", "세척제의 피부접촉", "1. 고무장갑지급", 2, 1, None, "3.4 액체·미스트"),
    p14(9, 77, "조리실/주방", "주방연료의 가스 사용", "1. 환기팬 가동 2. 가스 검지 및 경보 장치 설치", 1, 3, None, "3.8 화재/폭발 위험"),
    p14(10, 78, "조리실/주방", "중량물취급으로 인한 근골격계질환", "1. 중량물 들기작업 표시 부착 2. 중량물 들기작업 교육", 2, 1, None, "5.7 중량물 취급작업"),
    p14(11, 78, "조리실/주방", "조리기구 반복사용으로 인한 근골격계질환", "1. 근골격계질환 예방교육 2. 작업전 스트레칭 실시", 2, 1, None, "5.8 반복작업"),
    p14(12, 78, "조리실/주방", "조리작업시 부자연스런 작업자세", "1. 근골격계질환 예방교육 2. 작업전 스트레칭 실시", 2, 1, None, "5.9 불안정한 작업자세"),
    p14(13, 78, "조리실/주방", "칼 사용으로 인한 자상", "1. 보호장갑", 2, 1, None, "5.10 작업(조작) 도구"),
    p14(14, 78, "조리실/주방", "조리작업시 고온환경", None, 2, 1, None, "6.1 기후/고온/한랭"),
    p14(15, 78, "조리실/주방", "제한된 공간사용으로 인한 충돌위험", "1. 조리실 정리정돈", 2, 1, None, "6.3 공간 및 이동통로"),
    p14(16, 78, "조리실/주방", "24시간 영업으로 인한 장시간 근로", "1. 교대근무", 2, 1, None, "6.5 작업시간"),
    p14(17, 79, "홀서비스/홀", "뜨거운 냄비, 그릇 운반시 화상", None, 3, 2, "1. 이동대차를 이용하여 운반 2. 보호장갑 착용", "1.2 위험한 표면"),
    p14(18, 79, "홀서비스/홀", "물기로 인해 바닥에서 미끄러짐", "1. 조리실 정리정돈", 2, 1, None, "1.5 넘어짐"),
    p14(19, 79, "홀서비스/홀", "뜨거운 음식물에 의한 화상", "1. 장갑지급", 2, 1, None, "3.4 액체·미스트"),
    p14(20, 79, "홀서비스/홀", "중량물취급으로 인한 근골격계질환", None, 2, 2, "1. 이동대차 이용 2. 소량씩 운반", "5.7 중량물 취급작업"),
    p14(21, 79, "홀서비스/홀", "음식물 운반시 부자연스런 작업자세", "1. 작업전 스트레칭 실시 2. 근골격계질환 예방 교육", 2, 1, None, "5.9 불안정한 작업자세"),
    p14(22, 79, "홀서비스/홀", "24시간 영업으로 인한 장시간 근로", "1. 교대근무 2. 충분한 휴식 제공", 2, 1, None, "6.5 작업시간"),
    p14(23, 80, "배달", "뜨거운 냄비, 그릇 운반시 화상", "1. 보호장갑", 2, 1, None, "1.2 위험한 표면"),
    p14(24, 80, "배달", "오토바이를 이용한 배달시 교통사고", "1. 헬멧착용", 3, 3, "1. 제한속도 지정 2. 교통신호준수 교육 3. 전방주시 철저교육", "1.3 기계(설비)의 낙하, 비래, 전복, 붕괴, 전도위험 부분"),
    p14(25, 80, "배달", "뜨거운 국물에 의한 화상", "1. 보호장갑", 2, 1, None, "3.4 액체·미스트"),
    p14(26, 80, "배달", "중량물취급으로 인한 근골격계질환", "1. 근골격계질환 예방 교육", 2, 1, None, "5.7 중량물 취급작업"),
    p14(27, 80, "배달", "음식물 운반시 부자연스런 작업자세", "1. 작업전 스트레칭 실시", 2, 1, None, "5.9 불안정한 작업자세"),
    p14(28, 80, "배달", "계단 이용시 넘어짐", None, 2, 3, "1. 뛰지 않도록 안전교육 2. 엘리베이터이용", "6.3 공간 및 이동통로"),
    p14(29, 80, "배달", "24시간 영업으로 인한 장시간 근로", "1. 교대근무", 2, 1, None, "6.5 작업시간"),
]
PI = {e["record_id"]: e for e in P}


def item(gid, tier, site, qtype, eid, work, evs, note=None, default=True, cand=None):
    gold = []
    for ev in evs:
        ev["hazard_codes_auto"] = [c for c, _ in codes(ev["hazard_text"])]
        for c in ev["hazard_codes_auto"]:
            if c not in gold:
                gold.append(c)
    return {"gold_id": gid, "tier": tier, "site_group": site, "query": {"type": qtype, "equipment_id": eid, "work_label": work},
            "gold_hazard_codes": gold, "evidence": evs, "use_in_default_eval": default,
            "candidate_equipment_ids_ai": cand, "note": note}


G = [
    item("G-R01", "R", "S01-A사업단(음식점)", "equipment", "EQ_ELECTRIC_PANEL", None, [case_ev("FOOD_A_01"), case_ev("FOOD_A_04")],
         "FOOD_A_04는 전선과 가스배관 두 대상이 얽힌 위험이다. 전선 쪽(EQ_ELECTRIC_PANEL)으로 묶었다(동의어 '전선' 일치)."),
    item("G-R02", "R", "S01-A사업단(음식점)", "equipment", "EQ_GAS_CYLINDER", None, [case_ev("FOOD_A_02")],
         "원문의 '가스용기 전도'는 용기 넘어짐이라 slip 코드에서 제외했다(사전 규칙)."),
    item("G-R03", "R", "S01-B사업단(카페)", "work", None, "매장 출입문 통행", [case_ev("CAFE_B_01")],
         "기기마스터에 출입문 ID가 없다. 작업·장소 질의로만 쓴다."),
    item("G-R04", "R", "S02-난정평화교육원(급식실)", "equipment", "EQ_ELECTRIC_PANEL", None, [case_ev("KITCHEN_N_01"), case_ev("KITCHEN_N_02")],
         "같은 사업장의 거의 같은 기록 2건이라 질의 1개로 합쳤다(이중 집계 방지)."),
    item("G-R05", "R", "S02-난정평화교육원(카페)", "equipment", "EQ_SINK", None, [NANJEONG_SINK],
         "교육원 내 카페 싱크대 기록. 개선 완료일 기재. 음식점은 아니며 카페·세척 작업 사례다."),
    item("G-P01", "P", "P14-익명 OO음식점(2012 평가 예시)", "equipment", "EQ_MIXER", None, [PI["P14-01"], PI["P14-02"]],
         "분쇄기·혼합기 모두 기기마스터 EQ_MIXER 동의어와 일치."),
    item("G-P02", "P", "P14-익명 OO음식점(2012 평가 예시)", "equipment", "EQ_KNIFE_BOARD", None, [PI["P14-13"]]),
    item("G-P03", "P", "P14-익명 OO음식점(2012 평가 예시)", "equipment", "EQ_MOTORCYCLE", None, [PI["P14-24"]]),
    item("G-P04", "P", "P14-익명 OO음식점(2012 평가 예시)", "work", None, "조리실(주방) 작업", [PI[f"P14-{i:02d}"] for i in range(1, 17)],
         "P14-09(주방연료 가스)는 기기명이 없어 기기 질의에 넣지 않았다.", cand={"P14-09": ["EQ_GAS_RANGE", "EQ_GAS_CYLINDER"]}),
    item("G-P05", "P", "P14-익명 OO음식점(2012 평가 예시)", "work", None, "홀서비스 작업", [PI[f"P14-{i:02d}"] for i in range(17, 23)]),
    item("G-P06", "P", "P14-익명 OO음식점(2012 평가 예시)", "work", None, "배달 작업", [PI[f"P14-{i:02d}"] for i in range(23, 30)]),
]
for g in G:
    if g["tier"] == "P":
        g["use_in_default_eval"] = False

EXCLUDED = [
    {"record_id": "FOOD_A_03", "reason": "프로젝트 검수 '사용 보류'. 위험 설명(LPG 용기)과 사진·대책(분전반)이 다름."},
    {"record_id": "FOOD_A_05", "reason": "프로젝트 검수 '사용 보류'. 원문 위험성 표기(2×4=12) 불일치, 대상(가스배관 감지기)에 맞는 기기 ID 없음."},
    {"record_id": "P14-16·22·29(장시간 근로)", "reason": "기기 관련 위험이 아니고 hazard_code에 대응 코드가 없다. 작업 질의 증거에는 남기되 정답 코드는 비어 있다."},
]

# ---- leakage checks
chunks = [json.loads(l) for l in open(KB + "261115_RAG_청크_v1_DR.jsonl", encoding="utf-8")]
links = [json.loads(l) for l in open(KB + "261116_RAG_기기위험요인링크_v2_DR.jsonl", encoding="utf-8")]
master = json.load(open(ROOT + "261115_기기마스터_인식평가셋_DR/261115_기기마스터_v1_DR.json", encoding="utf-8"))
master_refs = {r.get("locator") or "" for e in master["equipment"] for h in e["related_hazards"] for r in h["refs"]}
CH = [norm(c["text"]) for c in chunks]
for g in G:
    lk = []
    for ev in g["evidence"]:
        h = norm(ev["hazard_text"])
        rid = ev["record_id"]
        flags = {
            "in_v1_chunks": any(h[:20] in t for t in CH),
            "in_v1_table": ("CASE-" + rid) in v1,
            "in_v2_index_links": sorted({l["link_id"] for l in links if l["source_id"] == "CASE-" + rid}),
            "in_equipment_master_v1_refs": ("CASE-" + rid) in master_refs,
            "in_S04_pipeline_inputs": rid in ("FOOD_A_01", "FOOD_A_02", "FOOD_A_04", "CAFE_B_01", "KITCHEN_N_01", "KITCHEN_N_02"),
        }
        ev["leakage"] = flags
        if flags["in_v1_chunks"] or flags["in_v1_table"] or flags["in_v2_index_links"] or flags["in_equipment_master_v1_refs"]:
            lk.append(rid)
    g["leakage_records"] = lk
    g["leakage_risk"] = "높음" if lk else "낮음(검색 대상 원문에 같은 기록 없음)"
    g["eval_exclude_source_ids"] = sorted({"CASE-" + r for r in lk})

with open(KB + "261116_RAG_위험요인추천_정답셋_v2_DR.jsonl", "w", encoding="utf-8", newline="\n") as f:
    for g in G:
        f.write(json.dumps(g, ensure_ascii=False) + "\n")
json.dump({"excluded_records": EXCLUDED}, open(SC + "gold_excluded.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for g in G:
    print(g["gold_id"], g["tier"], g["query"], g["gold_hazard_codes"], g["leakage_risk"], g["leakage_records"])
