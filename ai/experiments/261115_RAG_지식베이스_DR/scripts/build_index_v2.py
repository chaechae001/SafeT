"""v2: equipment -> hazard -> measure index for 'equipment-based hazard recommendation' (Human-in-the-Loop).

Rule: a link is created only when an equipment term (MATCH below) appears literally in the source text
(hazard sentence, checklist item, task label or checklist section title). Hazard codes come from literal terms
(LEX below). No link is inferred from co-occurrence alone. Equipment without any link -> '근거 없음' list.

Inputs (read-only):
  - 261115_기기마스터_인식평가셋_DR/261115_기기마스터_v1_DR.json (equipment_id, hazard codes)
  - 261115_RAG_지식베이스_DR/261115_RAG_구조화표_v1_DR.jsonl (CHK rows, CASE rows)
  - scratchpad d8_rows.json (parse_d8_tables.py output; D8 p247-275 table rows)
  - D5 rows: transcribed from page images (2026-11-16, visual) - defined below
  - D8 p96-97 국외 레스토랑 공정별 개선안: pdftotext text, defined below
Outputs: 261115_RAG_지식베이스_DR/261116_RAG_기기위험요인인덱스_v2_DR.json
         261115_RAG_지식베이스_DR/261116_RAG_기기위험요인링크_v2_DR.jsonl
"""
import json, re, hashlib, collections

ROOT = r"<LOCAL_WORKSPACE>/"
KB = ROOT + "261115_RAG_지식베이스_DR/"
SC = r"<LOCAL_SCRATCH>/"
MASTER = ROOT + "261115_기기마스터_인식평가셋_DR/261115_기기마스터_v1_DR.json"
D5_FILE = "RAG용/[2023-중소기업지원실-404]_[2023-중소기업지원실-404]서비스업+재해사례+중심+위험성평가+방법+안내서.pdf"
D8_FILE = "RAG용/최종보고서_프랜차이즈 가맹본부의 산재예방 조치 이행 실태조사 및 개선방안 마련.pdf"

# ---- equipment match terms (literal, regex). Written for this index; reviewed against source wording.
MATCH = {
    "EQ_FRYER": r"튀김기|프라이어|튀김솥",
    "EQ_GAS_RANGE": r"가스레인지|가스테이블|쿡탑|(?<!전자)레인지",
    "EQ_OVEN": r"오븐|화덕",
    "EQ_GRILL": r"그릴|샐러맨더|석쇠",
    "EQ_MICROWAVE": r"전자레인지|전자렌지",
    "EQ_RICE_COOKER": r"취반기|밥솥",
    "EQ_SOUP_KETTLE": r"국솥|스팀솥|육수솥",
    "EQ_GRIDDLE": r"그리들|철판",
    "EQ_STEAMER": r"찜기|찜솥",
    "EQ_ODEN_WARMER": r"어묵|온장고",
    "EQ_PORTABLE_BURNER": r"부루스타|휴대용 가스",
    "EQ_COOKING_ROBOT": r"조리 로봇|협동로봇|로봇팔",
    "EQ_KNIFE_BOARD": r"(?<!알)칼(?!날|슘|텍|리)|도마",
    "EQ_SCISSORS": r"가위",
    "EQ_VEG_CUTTER": r"채소절단기|야채절단기|채칼|다지기",
    "EQ_MEAT_SLICER": r"육절기|골절기|고기 ?절단기",
    "EQ_MIXER": r"혼합기|믹서|블렌더|(?<!원두 )(?<!얼음 )분쇄기|푸드 ?프로세서",
    "EQ_DOUGH_MIXER": r"반죽기|니더",
    "EQ_NOODLE_MACHINE": r"제면기",
    "EQ_RICE_WASHER": r"세미기",
    "EQ_MARINATOR": r"염지",
    "EQ_COFFEE_MACHINE": r"커피 ?머신|에스프레소|샷 ?추출기|스팀 ?노즐|스팀기",
    "EQ_COFFEE_GRINDER": r"커피 ?그라인더|원두 ?분쇄",
    "EQ_ICE_MAKER": r"제빙기",
    "EQ_ICE_CRUSHER": r"빙삭기|빙수기|쇄빙기|얼음 ?분쇄",
    "EQ_WATER_HEATER": r"온수기|온수 ?디스펜서",
    "EQ_BEER_DISPENSER": r"생맥주|맥주 ?서버|탄산가스",
    "EQ_DISHWASHER": r"식기세척기",
    "EQ_STERILIZER": r"소독기|살균기",
    "EQ_SINK": r"싱크대|씽크대|개수대|세정대|세척대",
    "EQ_EXHAUST_HOOD": r"배기후드|후드|배기팬|환풍기|덕트|환기설비|환기장치",
    "EQ_WASTE_OIL_CONTAINER": r"폐유|폐식용유",
    "EQ_REFRIGERATOR": r"냉장·냉동고|냉장고|냉동고",
    "EQ_WALKIN_COOLER": r"냉장창고|냉동창고|냉동․냉장창고|냉동·냉장창고|저온창고|워크인",
    "EQ_DISPLAY_COOLER": r"쇼케이스|진열 ?냉장",
    "EQ_CART": r"대차|카트",
    "EQ_SHELF": r"선반",
    "EQ_LADDER": r"사다리|작업발판",
    "EQ_DUMBWAITER": r"덤웨이터|리프트|승강기|소형화물용 ?엘리베이터",
    "EQ_MOTORCYCLE": r"이륜차|오토바이|이륜자동차|스쿠터",
    "EQ_GAS_CYLINDER": r"가스용기|LPG ?용기|가스통|부탄",
    "EQ_ELECTRIC_PANEL": r"분전반|콘센트|멀티탭|연장선|전선|플러그",
}

# ---- hazard codes (master hazard_codes) -> literal terms
LEX = {
    "slip": r"넘어짐|넘어져|넘어지|넘어질|미끄러|미끄럼|(?<!용기 )(?<!용기)전도(?!방지)",
    "cut": r"베임|베이|절단|끼임|끼여|끼일|말림|말릴|말려|감김|찔림|찔릴|자상|협착|긁힘",
    "burn": r"화상|열상|뜨거",
    "fire": r"화재|착화|화염",
    "gas": r"가스\s?누출|가스\s?누설|LPG|LNG|가스경보|가스 검지|가스 사용|가스.{0,20}폭발",
    "electric": r"감전|누전|절연|접지",
    "chemical": r"세척제|세제|화학물질|락스|MSDS",
    "ergonomic": r"근골격계|요통|중량물|반복작업|부자연스|작업자세|입식",
    "falling": r"낙하|떨어짐|떨어져|떨어질|떨어지|떨어뜨|추락|부딪|충돌|전복",
    "respiratory": r"조리흄|환기|유해가스|일산화탄소|흄",
    "traffic": r"교통사고|교통|신호위반|중앙선",
    "noise_vibration": r"(?<!이상)소음|(?<!이상)진동|dB",
    "heat_cold": r"고온환경|고열|한랭|저체온|방한|저온",
    "entrapment": r"갇힘|내부에서도 열리|내부에서 수동개폐|내부에 작업자가 있는지|임의로 잠기지",
}


def codes(t):
    out = []
    for c, rx in LEX.items():
        m = re.search(rx, t)
        if m:
            out.append((c, m.group()))
    return out


def eq_hits(t, sid=None):
    out = []
    for e, rx in MATCH.items():
        m = re.search(rx, t or "")
        if m:
            out.append((e, m.group()))
    out = [x for x in out if (x[0], sid) not in EXCLUDE_MATCH]
    # 전자레인지 also matches '레인지' rule guard; drop GAS_RANGE if only 전자레인지
    ids = [e for e, _ in out]
    if "EQ_MICROWAVE" in ids and "EQ_GAS_RANGE" in ids and not re.search(r"가스레인지|가스테이블|쿡탑|(?<!전자)레인지", t):
        out = [x for x in out if x[0] != "EQ_GAS_RANGE"]
    # 식기세척기/소독기 etc are fine; '세척대' vs '식기세척기' distinct
    return out


norm = lambda s: re.sub(r"\s+", "", s or "")

# ---------------- evidence units ----------------
UNITS = []


def unit(**k):
    k.setdefault("hazards", []); k.setdefault("measures", []); k.setdefault("current_controls", [])
    UNITS.append(k)


# 1) checklist rows (v1 table)
TB = [json.loads(l) for l in open(KB + "261115_RAG_구조화표_v1_DR.jsonl", encoding="utf-8")]
for r in TB:
    if r["source_type"] != "checklist":
        continue
    unit(source_id=r["row_id"], source_type="checklist", source_file=r["source_file"], pages=[r["source_pdf_page"]],
         task=r["source_section"], hazards=[r["source_text"]], measures=[r["source_text"]],
         extraction="pypdf 텍스트(v1 구조화 표)", visual_check="v1에서 PDF 텍스트 대조(공백 제외 일치)",
         pairing="점검항목 1개 = 위험 단어와 조치가 같은 문장")

# 2) cases (v1 table) - excluded for project_review_status '사용 보류'
for r in TB:
    if r["source_type"] != "case":
        continue
    unit(source_id=r["row_id"], source_type="case", source_file=r["source_file"], pages=[r["source_pdf_page"]],
         task=r["source_section"], hazards=[r["hazard_text"]], measures=[r["improvement_measure"]],
         extraction=r["source_text_method"], visual_check="v1에서 원본 쪽 대조",
         pairing="사례 1건 = 유해위험요인과 감소대책(권고)", review=r["project_review_status"],
         excluded=r["project_review_status"] == "사용 보류")

# 3) D8 industry guide table rows (coordinate parse)
D8 = json.load(open(SC + "d8_rows.json", encoding="utf-8"))
D8_LABEL_NOTE = {"D8T-048": "원문 표 라벨은 '배달(이륜차)'이나 내용은 조리실 바닥·후드 청소다(원문 오류로 보임, p267 이미지 확인). 라벨을 근거로 쓰지 않는다."}
for r in D8:
    unit(source_id=r["row_key"], source_type="d8_table", source_file=D8_FILE, pages=r["pages"],
         task=f"{r['industry']} / {r['task']}", industry=r["industry"],
         hazards=[h for h in r["hazards"] if h != "기타"], measures=[m for m in r["measures"] if m != "기타"],
         extraction="pypdf 좌표 기반 표 복원(parse_d8_tables.py)", visual_check="표본 대조: p249·p254·p264·p267 이미지",
         pairing="같은 표 행(주요 작업)의 위험요인 목록과 예방대책 목록. 1:1 대응 아님",
         task_label_usable=r["row_key"] not in D8_LABEL_NOTE, note=D8_LABEL_NOTE.get(r["row_key"]))

# 4) D5 food-industry pages: visual transcription (2026-11-16). hazards = 재해 유형(p58 표) + 사고사망사례 그림 설명.
D5 = [
    ("D5V-059", [59], "01 이륜차 배달업무", ["이륜차 배달 중 교통사고"],
     [("배달종사자는 도로교통법상 적합한 운전 면허를 소지하고 있는가?", ["관계법령에 따른 적합한 운전자격 면허 소지"]),
      ("기상조건이 양호한가?", ["우천 및 폭설 등 기상상황이 악화될 경우 가능한 운행을 삼가고, 도로사정이 양호한 경로로 안전운전"]),
      ("교통안전수칙을 준수하고 있는가?", ["배달 출발 시와 배달 복귀시 이륜차의 불법 주행이 행해지지 않는 구역별 안전주행경로를 설정", "주행경로의 특징, 위험요인 등을 사전에 교육", "운전 중 휴대폰 사용 금지 등 전방 주시 철저"]),
      ("개인 보호구를 지급하였는가?", ["물건을 운반하거나 수거·배달하기 위하여 이륜차를 운행하는 작업시 승차용 안전모를 반드시 착용 및 지도"])]),
    ("D5V-066", [66], "06 이동식 사다리 작업", ["사다리 작업 중 추락", "이동식사다리 이용하여 경작업 중 떨어짐"],
     [("사다리를 설치하여 사용하는 것이 적정한가?", ["작업발판 용도로 사다리 사용을 지양하고, 고소작업대 또는 난간이 부착된 말비계 작업발판 사용", "※ 사다리는 이동통로 용도로, 불가피한 경작업에 한하여 허용"]),
      ("사다리가 변형되거나 손상되었는가?", ["사다리 즉시 교체"]),
      ("사다리가 바닥에 제대로 고정되지 않아 기울어질 위험이 있는가?", ["사다리는 평탄하고 미끄럼이 없는 바닥에 설치하고, 최대길이 3.5m 이하 A형 사다리 사용", "2인1조 작업 실시"]),
      ("사다리를 이용한 작업시 중심을 잃을 가능성이 있는가?", ["사다리 설치각도는 75도 이내로 유지"]),
      ("개인보호구 착용 상태는 양호한가?", ["안전모, 안전대 등 작업 특성에 맞는 개인보호구 착용"])]),
    ("D5V-067", [67], "07 음식 운반용 승강기(덤웨이터) 사용 작업", ["리프트에 끼임·추락", "음식운반용 승강기에 탑승하여 상층으로 이동 중 목과 팔이 끼임", "음식운반용 승강기 작동 중 출입문을 개방하여 신체 끼임"],
     [("운반구와 출입문 사이에 신체가 끼일 위험이 있는가?", ["사람 탑승금지", "운행 중 부저 작동상태 등 경보장치 확인", "신체가 운반구 내에 있을 때 작동 금지"]),
      ("적재하중을 준수하는가?", ["적재하중 표기 및 준수", "출입문 연동장치와 비상정지장치 설치 및 작동유무 수시 확인"]),
      ("운반구가 떨어질 위험이 있는가?", ["제어장치 작동유무 수시 확인", "사람 탑승금지", "음식물 등은 중앙에 적재하여 운반"])]),
    ("D5V-068", [68], "08 혼합기(식품가공용) 등 기계 작업", ["혼합기 사용 중 끼임", "혼합기 재료 배합중 끼임", "혼합기 내부 청소 중 끼임"],
     [("원료 투입구 덮개를 닫은 상태에서 작업하고 있는가?", ["원료 투입구 덮개를 닫은 상태에서 작업", "가동 중 덮개를 여는 경우에는 기계 정지 등 연동", "불가피한 경우 막대 등 보조도구 사용"]),
      ("청소 작업 시 안전하게 작업하고 있는가?", ["운전 정지 후 청소 작업 실시", "불시 기동 방지를 위한 동력전원 차단, 잠금장치 및 점검 중 조작금지 표지 게시", "조작방법 및 안전작업 절차 준수"]),
      ("자율안전확인 신고 기계를 사용하고 있는가?", ["자율안전확인 신고 기계 사용 - 식품가공용 기계(파쇄·절단·혼합·제면기만 해당)"]),
      ("안전모 등 개인보호구 착용 상태는?", ["작업모, 작업복 등 작업에 적합한 보호장구 착용"]),
      ("동력전달부, 속도조절부, 가공부 등에 안전가드 등이 설치되어 있는가?", ["안전가드 설치", "동력전달부 등 위험구역에 출입금지 조치", "가동형 가드를 사용하는 경우 연동형(인터록) 구조 사용"]),
      ("비상정지장치가 설치되어 있고 정상적으로 작동되는가?", ["비상정지장치 설치"])]),
    ("D5V-069", [69], "09 절단용 수공구(칼) 작업", ["조리용 수공구 찔림", "절단 작업 중 베임", "육절기 작업 중 베임"],
     [("절단용 수공구(칼) 사용 시 안전하게 작업하고 있는가?", ["숙련된 작업자에 한해 작업 실시", "작업에 집중할 수 있는 환경 조성 - 조명, 작업 높이 조정 등", "냉동 식자재는 해동 후 절단", "무리한 힘을 주어 작업하는 불안전한 행동 금지", "베임 방지용 안전장갑 착용"]),
      ("절단용 수공구(칼)은 안전한 장소에 보관하고 있는가?", ["사용 시 칼이 떨어질 우려가 없는 장소에 임시 보관", "사용 후 지정된 장소에 보관"])]),
    ("D5V-070", [70], "10 조리 관련 설비 – 배기후드", ["조리흄 발생 또는 화학물질 누출로 재해, 화재 등"],
     [("배기후드 점검 또는 청소를 안전하게 하고 있는가?", ["배기후드 및 덕트 속 기름기 등 이물질 정기적 제거", "배기후드 청소 시 전용 청소용구 및 안전한 작업발판 사용(2인 1조 작업 실시)", "정비 및 청소작업 시 전원을 차단하고 회전체가 정지된 것을 확인 후 작업 중임을 표시"]),
      ("배기후드가 정상적으로 작동하는가?", ["배기후드 작동이 원활하지 않은 경우 창문 및 출입문을 개방하여 주기적으로 환기"])]),
    ("D5V-072A", [72], "11 식자재 운반 및 보관 – 중량물(식자재) 운반", ["전도, 선반에 부딪힘, 근골격계 질환 및 저체온증 등"],
     [("운반대차 등 운반용 기구를 안전하게 사용하는가?", ["운반용 기구는 사용 전 정상 작동여부 확인", "운반대차에 과적하거나 편하중이 발생하지 않도록 사용"]),
      ("선반 등으로 운반 시 작업을 안전하게 하고 있는가?", ["운반시 선반 등 날카로운 부분에 부딪힘·베임 방지를 위한 보호대 설치", "선반 위에 물건을 올리거나 내릴 경우 안전한 작업발판 사용 * 바퀴달린 의자를 사용하거나, 적재물을 쌓아서 딛는 행동 금지"])]),
    ("D5V-072B", [72], "11 식자재 운반 및 보관 – 냉장·냉동고 식자재 보관", ["전도, 선반에 부딪힘, 근골격계 질환 및 저체온증 등"],
     [("냉장·냉동고를 안전하게 사용하고 있는가?", ["냉장·냉동고에 저온주의 표지 부착"]),
      ("냉장·냉동고 내부에서 안전하게 작업하고 있는가?", ["냉장·냉동고 출입문은 내부에서도 열리는지 정기적 확인", "냉장·냉동고 내에서 장시간 작업 시 방한복·방한장갑·방한모 등을 지급·착용", "냉장·냉동고 출입문을 잠그는 경우에는 반드시 내부에 작업자가 있는지 확인"])]),
]
for sid, pages, task, haz, rows in D5:
    for k, (q, ms) in enumerate(rows, 1):
        unit(source_id=f"{sid}-r{k}", source_type="d5_visual", source_file=D5_FILE, pages=pages + [58],
             task=task, hazards=haz, check_question=q, measures=ms,
             extraction="쪽 이미지 시각 판독 전사(2026-11-16). 재해 유형은 p58 표, 사고사망사례 그림 설명",
             visual_check="실시", pairing="같은 작업 쪽의 재해 유형(쪽 단위)과 점검항목별 개선대책. 1:1 대응 아님")

# 5) D8 p96-97 국외 레스토랑 공정별 개선안 (measures only; no hazard column)
D8F = [
    ("D8F-01", "요리 (가스레인지, 오븐, 그릴 사용)", ["냄비 손잡이를 버너에서 멀리 놓고 레인지 가장자리 위로 튀어나오지 않도록 한다.", "끓는 액체가 담긴 무거운 냄비를 옮기거나 운반할 때 도움을 받는다.", "집게를 사용하여 음식을 끓는 물에 담근다.", "스토브에서 음식을 확인하거나 끓는 물에 음식을 담을 때 또는 오븐에 손을 뻗을 때 냄비 홀더 또는 장갑을 사용한다.", "물에 적신 수건과 같은 젖은 재료를 팟 홀더로 사용하지 않는다."]),
    ("D8F-02", "요리 (딥프라이어 사용)", ["프라이어에 기름 튀김 방지 가드를 사용한다.", "프라이어 바구니에 음식을 넣기 전에 음식의 물기를 없애고 얼음을 털어낸다.", "프라이어 바구니를 반 이상 채우지 않는다.", "사용하지 않을 때는 프라이어 오일을 덮어 놓는다.", "냄비 홀더 또는 장갑을 사용한다."]),
    ("D8F-03", "요리 (전자레인지 사용)", ["문이 열리면 자동으로 꺼지는 전자레인지를 제공한다.", "도어의 밀봉을 주기적으로 확인한다.", "전자레인지에 금속 용기, 호일, 조리기구를 사용하지 않는다.", "전자레인지에서 꺼낸 후 용기를 조심스럽게 열어 증기가 빠져나갈 수 있도록 한다.", "전자레인지에서 물건을 꺼낼 때는 뜨거운 패드, 냄비 홀더, 또는 장갑을 사용한다."]),
    ("D8F-04", "요리 (칼 사용)", ["각 작업에 적합한 크기와 유형의 칼을 제공한다.", "칼을 날카롭게 유지한다. 둔한 칼은 안전하지 않다.", "칼을 물에 담가 두지 않는다.", "미끄러지지 않도록 도마 밑에 젖은 천을 깔아준다.", "칼을 카운터 위에 올려놓고 다른 사람에게 전달하거나 칼날이 아래로 향하게 전달한다.", "절단 작업을 많이 하는 경우 손목을 덮고 잘 맞으며 이음새가 견고하고 촘촘하게 짜여진 절단 방지 장갑을 착용한다."]),
    ("D8F-05", "요리 (슬라이서, 그라인더, 푸드 프로세서)", ["대형 전기 제품에는 기계 가드를 장착한다.", "손, 얼굴, 머리카락, 의복 및 장신구를 움직이는 부품에 가까이 두지 않는다.", "전기 장비를 청소하거나 수리할 때는 항상 잠금/태그아웃 절차를 사용한다.", "장비를 작동할 때 절단 방지 장갑, 고글 및 팔 보호대를 착용한다."]),
]
for sid, task, ms in D8F:
    unit(source_id=sid, source_type="d8_foreign_measures", source_file=D8_FILE, pages=[96, 97], task=task,
         hazards=[], measures=ms, extraction="pdftotext(쪽 걸침 p96-97). 이미지 대조 미실시",
         visual_check="미실시", pairing="공정별 개선안만 있음(위험요인 칸 없음). 국외(Cal/OSHA) 가이드 정리")

# explicit false matches found on review (equipment word used in another sense)
EXCLUDE_MATCH = {("EQ_DUMBWAITER", "CHK-4-1-2-09"): "사다리를 올려놓으면 안 되는 장소로 '리프트'를 언급"}

# checklist section titles that enumerate machine kinds with a shared suffix ('파쇄·절단·반죽·혼합·제면기')
SECTION_EQ = {
    "4-2-1. 식품가공기계(파쇄·절단·반죽·혼합·제면기)": [("EQ_VEG_CUTTER", "절단(기)"), ("EQ_MIXER", "파쇄·혼합(기)"),
                                                  ("EQ_DOUGH_MIXER", "반죽(기)"), ("EQ_NOODLE_MACHINE", "제면기")],
}


def split_components(h):
    """D5 page-level 재해 유형 strings list several types; split so each part is coded separately"""
    return [p.strip() for p in re.split(r",\s*|\s및\s", h) if p.strip()]


# ---------------- link generation ----------------
master = json.load(open(MASTER, encoding="utf-8"))
EQ = {e["equipment_id"]: e for e in master["equipment"]}
HZ = master["hazard_codes"]
links, measure_only, unmapped = [], [], []
for u in UNITS:
    if u.get("excluded"):
        continue
    task_eq = [] if u.get("task_label_usable") is False else (SECTION_EQ.get(u["task"]) or eq_hits(u["task"], u["source_id"]))
    seen = set()
    hz_list = [c for h in u["hazards"] for c in (split_components(h) if u["source_type"] == "d5_visual" else [h])]
    for h in hz_list:
        hz_eq = eq_hits(h, u["source_id"])
        cands = [(e, t, "위험요인 문장") for e, t in hz_eq] + [(e, t, "작업명·섹션명·점검질문") for e, t in task_eq if e not in {x for x, _ in hz_eq}]
        for e, term, where in cands:
            if not codes(h) and u["source_type"] != "checklist":
                unmapped.append({"equipment_id": e, "hazard_text": h, "source_id": u["source_id"], "match_where": where})
            for c, cterm in codes(h):
                key = (e, c, h)
                if key in seen:
                    continue
                seen.add(key)
                ms_named = [m for m in u["measures"] if re.search(MATCH[e], m)]
                links.append({
                    "equipment_id": e, "standard_name": EQ[e]["standard_name"], "hazard_code": c, "hazard_name": HZ[c],
                    "hazard_text": h, "hazard_code_term": cterm,
                    "measures": u["measures"], "measures_naming_equipment": ms_named,
                    "equipment_match": {"term": term, "where": where},
                    "evidence_tier": "A" if where == "위험요인 문장" else "B",
                    "source_id": u["source_id"], "source_type": u["source_type"], "source_file": u["source_file"],
                    "pdf_pages": u["pages"], "task_or_section": u["task"], "check_question": u.get("check_question"),
                    "pairing": u["pairing"], "extraction": u["extraction"], "visual_check": u["visual_check"],
                    "note": u.get("note"),
                })
    # measures that name an equipment although no hazard link was made from this unit for that equipment
    linked_eq = {l["equipment_id"] for l in links if l["source_id"] == u["source_id"]}
    for m in u["measures"]:
        for e, term in eq_hits(m, u["source_id"]) + [(e, t) for e, t in task_eq]:
            if e in linked_eq:
                continue
            measure_only.append({"equipment_id": e, "measure": m, "equipment_match": {"term": term},
                                 "source_id": u["source_id"], "source_type": u["source_type"], "source_file": u["source_file"],
                                 "pdf_pages": u["pages"], "task_or_section": u["task"],
                                 "why_no_hazard_link": "원문에 이 기기와 함께 적힌 위험요인 단어가 없음(대책만 있음)"})
for i, l in enumerate(links, 1):
    l["link_id"] = f"L{i:04d}"
    l["eval_exclude_when_gold_from_case"] = l["source_type"] == "case"
# dedupe measure_only
mo, seen = [], set()
for m in measure_only:
    k = (m["equipment_id"], norm(m["measure"]), m["source_id"])
    if k not in seen:
        seen.add(k); mo.append(m)
for i, m in enumerate(mo, 1):
    m["measure_only_id"] = f"M{i:04d}"

# ---------------- aggregate index ----------------
REL = {1: "대책 문장에 기기명 포함", 2: "작업명·점검표 섹션명에 기기명이 있는 같은 항목", 3: "대책 문장에 같은 위험유형 단어 포함", 4: "같은 표 행에 있음(관련성 미확인)"}


def relevance(m, l, eid):
    if re.search(MATCH[eid], m):
        return 1, REL[1]
    if l["equipment_match"]["where"] != "위험요인 문장" or l["source_type"] in ("checklist", "d5_visual", "case"):
        if l["source_type"] in ("checklist", "d5_visual", "case"):
            return 2, REL[2]
    if l["hazard_code"] in {c for c, _ in codes(m)}:
        return 3, REL[3]
    return 4, REL[4]


index, no_evidence, master_check = [], [], []
for eid, e in EQ.items():
    L = [l for l in links if l["equipment_id"] == eid]
    hz = collections.OrderedDict()
    for l in sorted(L, key=lambda x: (x["evidence_tier"], x["hazard_code"])):
        d = hz.setdefault(l["hazard_code"], {"hazard_code": l["hazard_code"], "hazard_name": l["hazard_name"],
                                             "link_ids": [], "source_ids": [], "hazard_texts": [], "measures": [],
                                             "tiers": set(), "source_types": set()})
        d["link_ids"].append(l["link_id"]); d["tiers"].add(l["evidence_tier"]); d["source_types"].add(l["source_type"])
        if l["source_id"] not in d["source_ids"]: d["source_ids"].append(l["source_id"])
        if norm(l["hazard_text"]) not in {norm(x) for x in d["hazard_texts"]}: d["hazard_texts"].append(l["hazard_text"])
        for m in l["measures"]:
            rel = relevance(m, l, eid)
            ex = [x for x in d["measures"] if norm(x["text"]) == norm(m)]
            if ex:
                if rel[0] < ex[0]["relevance_rank"]:
                    ex[0]["relevance_rank"], ex[0]["relevance"] = rel
                if l["source_id"] not in ex[0]["source_ids"]:
                    ex[0]["source_ids"].append(l["source_id"])
            else:
                d["measures"].append({"text": m, "source_ids": [l["source_id"]], "relevance_rank": rel[0], "relevance": rel[1]})
    hl = []
    for d in hz.values():
        d["measures"].sort(key=lambda x: (x["relevance_rank"], -len(x["source_ids"])))
        d["tiers"] = sorted(d["tiers"]); d["source_types"] = sorted(d["source_types"])
        d["n_sources"] = len(d["source_ids"]); d["n_measures"] = len(d["measures"])
        hl.append(d)
    hl.sort(key=lambda d: (-d["n_sources"], d["hazard_code"]))
    mos = [m for m in mo if m["equipment_id"] == eid]
    index.append({"equipment_id": eid, "standard_name": e["standard_name"], "area": e["area"],
                  "match_terms": MATCH[eid], "hazards": hl, "measure_only": [{"text": m["measure"], "source_id": m["source_id"], "measure_only_id": m["measure_only_id"]} for m in mos],
                  "n_links": len(L), "n_hazard_codes": len(hl)})
    if not L:
        no_evidence.append({"equipment_id": eid, "standard_name": e["standard_name"],
                            "measure_only_count": len(mos),
                            "reason": "원문(점검표·D5·D8·사례)에 이 기기명과 위험요인 단어가 함께 나오는 곳이 없음" + (" (대책 문장만 있음)" if mos else ""),
                            "master_hazard_codes_v1": [h["code"] for h in e["related_hazards"]]})
    for h in e["related_hazards"]:
        ok = h["code"] in hz
        master_check.append({"equipment_id": eid, "hazard_code": h["code"], "master_evidence": h["evidence"],
                             "supported_by_v2_links": ok, "v2_sources": hz[h["code"]]["source_ids"] if ok else []})

out = {
    "name": "Safe-T 기기별 위험요인·예방대책 인덱스 v2", "created_date_kst": "2026-11-16",
    "status": "초안. AI가 규칙으로 생성. 전문가 검수 전. 추천 후보이며 최종 선택·판단은 사용자가 한다.",
    "purpose": "사진 분석은 기기 식별만 담당하고, LLM이 기기별 위험요인·평가 항목을 추천할 때 근거로 쓴다.",
    "equipment_key": "261115_기기마스터_인식평가셋_DR/261115_기기마스터_v1_DR.json equipment_id",
    "rules": {
        "link": "기기명(match_terms)이 원문의 위험요인 문장(tier A) 또는 작업명·점검표 섹션명·점검 질문(tier B)에 그대로 있을 때만 연결한다.",
        "hazard_code": "위험요인 문장에 hazard_code_lexicon 단어가 그대로 있을 때만 붙인다.",
        "measures": "연결 근거와 같은 행·항목·작업 쪽의 대책을 그대로 둔다. 위험요인과 1:1 대응이 아니다(pairing 참고).",
        "no_inference": "같은 쪽·같은 표에 함께 있다는 이유만으로는 연결하지 않는다.",
    },
    "hazard_codes": HZ, "hazard_code_lexicon": LEX,
    "counts": {"units": len(UNITS), "links": len(links), "measure_only": len(mo),
               "equipment_total": len(EQ), "equipment_with_links": len(EQ) - len(no_evidence), "equipment_no_evidence": len(no_evidence),
               "hazard_texts_without_code": len(unmapped)},
    "index": index, "no_evidence": no_evidence, "master_v1_link_check": master_check,
    "excluded_units": [{"source_id": u["source_id"], "reason": "프로젝트 검수 상태 '사용 보류'"} for u in UNITS if u.get("excluded")],
    "measure_only_records": mo,
    "hazard_texts_without_code": [x for x in unmapped if x["hazard_text"] not in ("기타",)],
}
json.dump(out, open(KB + "261116_RAG_기기위험요인인덱스_v2_DR.json", "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
with open(KB + "261116_RAG_기기위험요인링크_v2_DR.jsonl", "w", encoding="utf-8", newline="\n") as f:
    for l in links:
        f.write(json.dumps(l, ensure_ascii=False) + "\n")
print(json.dumps(out["counts"], ensure_ascii=False))
print("no evidence:", [n["equipment_id"] for n in no_evidence])
