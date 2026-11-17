"""사진 상태 관찰 단계(VLM). 기기 이름은 판정하지 않는다(기기는 탐지 모델 담당).

- build_messages(): 사진 1장 + 장소 → VLM 메시지(이미지 자리 + 문장). 베낄 수 있는 예시 문장을 넣지 않는다.
- postprocess(): 모델 응답 → Observation[] (contract_v2/common.schema.json#/$defs/Observation)
  · hazard_state가 분류 코드에 없으면 버림(집계), 외국 문자 섞인 관찰 버림(집계), 같은 문장 중복 제거
  · 관찰 문장에 기기마스터 기기 이름이 있으면 equipment_term_flag=true (지우지 않고 표시만)
  · confidence는 모델 자기 보고값(보정 전)으로 표시
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from s04_pipeline import ROOT, foreign_script

TAX = json.loads((ROOT / "contract_v2" / "observation_taxonomy.json").read_text(encoding="utf-8"))
CODES = TAX["codes"]
PROMPT_VERSION = "observe-v1"

SYSTEM = ("너는 음식점 주방 사진에서 안전과 관련된 '상태'만 관찰해 적는 보조 도구다. "
          "사진에 실제로 보이는 것만 쓴다. 보이지 않는 것을 추측하지 않는다. 기기 이름을 쓰지 않는다. 출력은 JSON 하나만 쓴다.")


def build_messages(location: str | None) -> list[dict]:
    codes = "\n".join(f"- {c}: {v['name']}" for c, v in CODES.items() if c != "none")
    text = f"""사진 장소(사용자 입력): {location or "(입력 없음)"}

할 일: 이 사진에서 사고로 이어질 수 있는 상태를 최대 5개 관찰해 적는다.
관찰 대상은 바닥·작업대·벽·통로의 상태, 물이나 기름, 불꽃이나 열, 쌓인 물건, 전선과 콘센트, 용기, 날카로운 도구의 놓인 상태 같은 것이다.

규칙:
1. text: 보이는 상태를 한국어 한 문장으로 쓴다. 위치(바닥, 위쪽 선반, 왼쪽 등)를 함께 쓴다. 기기나 제품의 이름은 쓰지 않는다.
2. hazard_state: 아래 코드 중 하나만 쓴다.
{codes}
3. confidence: 이 관찰이 사진에서 분명히 보이는 정도를 0에서 1 사이 숫자로 쓴다.
4. 사고로 이어질 상태가 보이지 않으면 {{"observations":[]}}만 쓴다.
5. 같은 상태를 두 번 쓰지 않는다.

출력은 아래 틀의 JSON 하나만 쓴다(빈 값을 규칙대로 채운다):
{{"observations":[{{"text":"","hazard_state":"","confidence":0}}]}}"""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": text}]}]


def parse(content: str):
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None, "JSON 객체 없음"
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return None, str(e)[:160]
    if not isinstance(d, dict) or not isinstance(d.get("observations"), list):
        return None, "observations 배열 없음"
    return d["observations"], None


def postprocess(content: str, photo_id: str, location: str | None, model_version: str, emap) -> tuple[list[dict], dict]:
    stats = {"parse_error": None, "raw": 0, "dropped_bad_code": 0, "dropped_foreign": 0, "dropped_empty": 0,
             "dropped_dup": 0, "equipment_term_flag": 0, "kept": 0}
    obs_raw, err = parse(content)
    if obs_raw is None:
        stats["parse_error"] = err
        return [], stats
    out, seen = [], set()
    allow = ["LPG", "LNG", "CO"]
    for o in obs_raw:
        stats["raw"] += 1
        if not isinstance(o, dict):
            stats["dropped_empty"] += 1
            continue
        text = str(o.get("text") or "").strip()
        code = str(o.get("hazard_state") or "").strip()
        if not text:
            stats["dropped_empty"] += 1
            continue
        if code not in CODES:
            stats["dropped_bad_code"] += 1
            continue
        if foreign_script(text, allow):
            stats["dropped_foreign"] += 1
            continue
        if text in seen:
            stats["dropped_dup"] += 1
            continue
        seen.add(text)
        conf = o.get("confidence")
        conf = float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None
        if conf is not None:
            conf = min(1.0, max(0.0, conf))
        flag = bool(emap.match(text))
        stats["equipment_term_flag"] += flag
        out.append({"observation_id": f"obs-{photo_id}-{len(out) + 1}", "photo_id": photo_id, "location": location,
                    "text": text[:200], "hazard_state": code, "confidence": conf,
                    "confidence_source": "model_self_report" if conf is not None else "none",
                    "model_version": model_version, "equipment_term_flag": flag})
    stats["kept"] = len(out)
    return out, stats


# ---------------------------------------------------------------- 2판: 상태 질문 방식
# 1판(자유 관찰)에서 모델이 프롬프트의 관찰 대상 목록(작업대·물)을 베끼고 같은 문장을 반복했다.
# 2판은 상태 질문마다 yes/no/unclear로 답하게 한다. 질문은 분류 코드별 '사진에서 보일 수 있는 상태'를 적은 것이다(작성자 정의, 검수 전).
PROMPT_VERSION_V2 = "observe-v2-vqa"
QUESTIONS = [
    ("Q01", "slip", "바닥에 물이나 기름이 고여 있거나 번져 있는가"),
    ("Q02", "slip", "바닥이나 통로에 상자·종이·물건이 놓여 있어 걸릴 수 있는가"),
    ("Q03", "burn", "켜진 불꽃이 보이거나 기름·물이 끓고 있는가"),
    ("Q04", "fire", "화구나 조리기구 주변에 기름때·찌꺼기가 두껍게 쌓여 있는가"),
    ("Q05", "gas", "가스통·부탄캔·가스 호스가 보이는가"),
    ("Q06", "electric", "콘센트·플러그·늘어진 전선이 보이는가"),
    ("Q07", "chemical", "세제·표백제 같은 화학 용기가 보이는가"),
    ("Q08", "falling", "머리 높이보다 위 선반에 크거나 무거운 물건이 올려져 있는가"),
    ("Q09", "cut", "칼·가위·채칼 같은 날붙이가 드러나 있는가"),
    ("Q10", "ergonomic", "무거운 상자나 자재를 손으로 들어 옮겨야 하는 상태로 쌓여 있는가"),
]


def build_messages_v2(location: str | None) -> list[dict]:
    qs = "\n".join(f"- {q}: {t}" for q, _, t in QUESTIONS)
    tmpl = ",".join(f'{{"q":"{q}","answer":"","where":""}}' for q, _, _ in QUESTIONS)
    text = f"""사진 장소(사용자 입력): {location or "(입력 없음)"}

아래 질문마다 이 사진에 실제로 보이는지 답한다.
{qs}

규칙:
1. answer: yes, no, unclear 중 하나만 쓴다. 사진에서 분명히 보일 때만 yes를 쓴다. 잘 안 보이면 unclear를 쓴다.
2. where: answer가 yes이면 사진 속 위치와 보이는 모습을 한국어 한 문장으로 쓴다. 기기나 제품의 이름은 쓰지 않는다. no나 unclear이면 빈 문자열로 둔다.

출력은 아래 틀의 JSON 하나만 쓴다(빈 값을 규칙대로 채운다):
{{"answers":[{tmpl}]}}"""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": text}]}]


def postprocess_v2(content: str, photo_id: str, location: str | None, model_version: str, emap) -> tuple[list[dict], dict]:
    stats = {"parse_error": None, "answered": 0, "yes": 0, "no": 0, "unclear": 0, "bad_answer": 0, "missing_q": 0,
             "yes_without_where": 0, "dropped_foreign": 0, "equipment_term_flag": 0, "kept": 0}
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError as e:
        d, stats["parse_error"] = None, str(e)[:160]
    if not isinstance(d, dict) or not isinstance(d.get("answers"), list):
        stats["parse_error"] = stats["parse_error"] or "answers 배열 없음"
        return [], stats
    qmap = {q: (c, t) for q, c, t in QUESTIONS}
    got = {}
    for a in d["answers"]:
        if isinstance(a, dict) and a.get("q") in qmap and a.get("q") not in got:
            got[a["q"]] = a
    stats["missing_q"] = len(qmap) - len(got)
    out = []
    for q, (code, qtext) in qmap.items():
        a = got.get(q)
        if not a:
            continue
        stats["answered"] += 1
        ans = str(a.get("answer") or "").strip().lower()
        if ans not in ("yes", "no", "unclear"):
            stats["bad_answer"] += 1
            continue
        stats[ans] += 1
        if ans != "yes":
            continue
        where = str(a.get("where") or "").strip()
        if not where:
            stats["yes_without_where"] += 1
            where = qtext  # 위치 문장이 없으면 질문 문장을 관찰로 쓴다(표시)
        if foreign_script(where, ["LPG", "LNG"]):
            stats["dropped_foreign"] += 1
            continue
        flag = bool(emap.match(where))
        stats["equipment_term_flag"] += flag
        out.append({"observation_id": f"obs-{photo_id}-{len(out) + 1}", "photo_id": photo_id, "location": location,
                    "text": where[:200], "hazard_state": code, "confidence": None, "confidence_source": "none",
                    "model_version": model_version, "equipment_term_flag": flag, "_question": q})
    stats["kept"] = len(out)
    return out, stats


# ---------------------------------------------------------------- 3판: 위치 선택지 고정 + 장소 입력 분리 + 영역별 질문
# 2판에서 위치 문장이 장소 입력·질문을 복사하거나 틀렸다('바닥에 보이는 불꽃'). 3판은
#  - 장소 입력을 프롬프트에 넣지 않는다(관찰 결과의 location 필드에만 붙인다).
#  - 위치는 고정 선택지 코드로 고르고, 보이는 모습은 짧은 문장으로 따로 쓴다.
#  - 사진 전체 1회 + 겹치는 4분할 영역 4회를 질문하고 사진 단위로 합친다(작은 상태 누락 대응).
PROMPT_VERSION_V3 = "observe-v3-vqa-region"
WHERE = {"floor": "바닥", "worktop": "작업대·조리대 위", "wall": "벽면", "upper_shelf": "위쪽 선반", "burner": "화구·불 주변",
         "under_counter": "작업대·선반 아래", "inside_vessel": "용기·조리기구 안", "other": "기타"}
REGIONS = {"full": (0.0, 0.0, 1.0, 1.0), "tl": (0.0, 0.0, 0.55, 0.55), "tr": (0.45, 0.0, 1.0, 0.55),
           "bl": (0.0, 0.45, 0.55, 1.0), "br": (0.45, 0.45, 1.0, 1.0)}


def build_messages_v3(region: str) -> list[dict]:
    qs = "\n".join(f"- {q}: {t}" for q, _, t in QUESTIONS)
    wh = ", ".join(f"{k}({v})" for k, v in WHERE.items())
    tmpl = ",".join(f'{{"q":"{q}","answer":"","where":"","seen":""}}' for q, _, _ in QUESTIONS)
    scope = "사진 전체" if region == "full" else "잘라 낸 사진 일부"
    text = f"""이 이미지는 음식점 주방의 {scope}다. 아래 질문마다 이미지에 실제로 보이는지 답한다.
{qs}

규칙:
1. answer: yes, no, unclear 중 하나만 쓴다. 이미지에서 분명히 보일 때만 yes를 쓴다. 잘 안 보이면 unclear를 쓴다.
2. where: answer가 yes이면 위치를 다음 코드 중 하나로 고른다: {wh}. no나 unclear이면 빈 문자열.
3. seen: answer가 yes이면 실제로 보이는 물체와 상태를 15자 안팎 한국어로 짧게 쓴다. 질문 문장을 그대로 옮기지 않는다. 기기나 제품 이름은 쓰지 않는다. no나 unclear이면 빈 문자열.

출력은 아래 틀의 JSON 하나만 쓴다(빈 값을 규칙대로 채운다):
{{"answers":[{tmpl}]}}"""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": text}]}]


def parse_v3(content: str):
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("answers"), list):
        return None
    got = {}
    for a in d["answers"]:
        if isinstance(a, dict) and a.get("q") in {q for q, _, _ in QUESTIONS} and a["q"] not in got:
            got[a["q"]] = a
    return got


def merge_v3(region_contents: dict, photo_id: str, location: str | None, model_version: str, emap,
             regions: tuple = ("full", "tl", "tr", "bl", "br")) -> tuple[list[dict], dict]:
    """영역별 응답을 사진 단위로 합친다. 같은 질문(상태)의 yes는 1건으로 합치고 근거 영역을 모두 남긴다."""
    stats = {"regions": 0, "parse_fail_regions": 0, "yes": 0, "no": 0, "unclear": 0, "bad_answer": 0,
             "bad_where": 0, "seen_copies_question": 0, "seen_empty": 0, "equipment_term_flag": 0, "kept": 0}
    qmap = {q: (c, t) for q, c, t in QUESTIONS}
    hits = {}
    for rg in regions:
        if rg not in region_contents:
            continue
        stats["regions"] += 1
        got = parse_v3(region_contents[rg])
        if got is None:
            stats["parse_fail_regions"] += 1
            continue
        for q, a in got.items():
            ans = str(a.get("answer") or "").strip().lower()
            if ans not in ("yes", "no", "unclear"):
                stats["bad_answer"] += 1
                continue
            stats[ans] += 1
            if ans != "yes":
                continue
            where = str(a.get("where") or "").strip()
            if where not in WHERE:
                stats["bad_where"] += 1
                where = "other"
            seen = str(a.get("seen") or "").strip()
            if not seen:
                stats["seen_empty"] += 1
            elif seen.rstrip(".") in qmap[q][1] or qmap[q][1][:10] in seen:
                stats["seen_copies_question"] += 1
            h = hits.setdefault(q, {"regions": [], "where": [], "seen": []})
            h["regions"].append(rg)
            h["where"].append(where)
            if seen and not foreign_script(seen, ["LPG", "LNG"]):
                h["seen"].append(seen)
    out = []
    for q, h in hits.items():
        code, qtext = qmap[q]
        where = max(set(h["where"]), key=h["where"].count)
        seen = h["seen"][0] if h["seen"] else qtext
        text = f"{WHERE[where]}: {seen}"
        flag = bool(emap.match(text))
        stats["equipment_term_flag"] += flag
        out.append({"observation_id": f"obs-{photo_id}-{len(out) + 1}", "photo_id": photo_id, "location": location,
                    "text": text[:200], "hazard_state": code, "confidence": None, "confidence_source": "none",
                    "model_version": model_version, "equipment_term_flag": flag,
                    "_question": q, "_regions": h["regions"], "_where_code": where})
    stats["kept"] = len(out)
    return out, stats
