"""사진 상태 관찰 단계 평가(내부, 작성자(비전문가) 검토). 모델 호출 없음.

- v1(자유 관찰, cloud_outputs_observe_v1.json): 채택 시도(1회차) 사용
- v2(상태 질문, cloud_outputs_observe_v2.json): 1회차(greedy)를 사용한다. Cloud 쪽 스크립트가 갱신되지 않아(파싱 키 불일치)
  모든 사진이 3회씩 재시도됐으나, v1과 같은 조건(greedy 1회차)으로 비교하려고 1회차만 쓴다.
- 참고 관찰: inputs/photo_cases/author_reference_observations.json (모델 출력 전에 작성)
- 판정(REVIEW): 맞음 / 부분 / 틀림(환각) / 틀림(부정문: '없다'를 위험으로 적음) — 작성자 판단, 정답 라벨 아님
python src/eval_observe.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from equipment_map import EquipmentMap  # noqa: E402
import re  # noqa: E402

from observe import merge_v3, postprocess, postprocess_v2  # noqa: E402
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

REF = json.loads((ROOT / "inputs" / "photo_cases" / "author_reference_observations.json").read_text(encoding="utf-8"))["cases"]

# (버전, 사례, 관찰 순번) → (판정, 맞춘 참고 관찰 ID, 메모)
REVIEW = {
    ("v1", "PC01", 1): ("부분", ["R3"], "작업면 물·기름방울은 있으나 '물이 쌓여'는 과장"),
    ("v1", "PC02", 1): ("맞음", ["R1"], "불꽃 관찰. 코드는 burn(참고는 fire)"),
    ("v1", "PC02", 2): ("틀림(부정문)", [], "'바닥이 깨끗하다'를 위험으로 적음"),
    ("v1", "PC02", 3): ("틀림(부정문)", [], "'물·기름이 보이지 않는다'"),
    ("v1", "PC02", 4): ("틀림(부정문)", [], "'날카로운 도구가 없다'"),
    ("v1", "PC02", 5): ("틀림(부정문)", [], "'쌓인 물건이 없다', 코드 traffic"),
    ("v1", "PC03", 1): ("틀림(환각)", [], "깨진 통 없음(제품 사진)"),
    ("v1", "PC04", 1): ("틀림(환각)", [], "물이 흐르는 모습 없음. 바닥 골판지·부탄캔·세제 용기는 놓침"),
    ("v1", "PC05", 1): ("틀림(환각)", [], "깨진 통 없음. PC03과 같은 문장"),
    ("v1", "PC06", 1): ("틀림(환각)", [], "작업대 물기 안 보임"),
    ("v1", "PC07", 1): ("맞음", ["R1"], "세척대 옆 작업면 물기"),
    ("v1", "PC08", 1): ("부분", ["R1"], "작업대 위 물건·아래 상자. 위험 정도는 약함"),
    ("v1", "PC08", 2): ("부분", ["R1"], "1과 같은 내용 반복, '떨어질 가능성'은 과장"),
    ("v2", "PC01", 1): ("부분", ["R3"], "Q01 바닥 물·기름: 바닥은 안 보이고 작업면 방울만. 문장은 장소 입력 복사"),
    ("v2", "PC01", 2): ("맞음", ["R1"], "Q03 끓는 기름. 문장은 장소 입력 복사"),
    ("v2", "PC02", 1): ("맞음", ["R1"], "Q03 불꽃. 위치 '바닥'은 틀림"),
    ("v2", "PC04", 1): ("맞음", ["R1"], "Q02 바닥 골판지·물건"),
    ("v2", "PC04", 2): ("맞음", ["R3"], "Q07 화학 용기. 위치 '화구 주변'은 틀림(세척대 아래)"),
    ("v2", "PC06", 1): ("맞음", ["R2"], "Q06 전선. 위치 '바닥'은 틀림(벽 콘센트)"),
    # 3판(전체 사진만 / 전체+4분할 영역). 판정 기준은 같고, 위치는 WHERE_OK에 따로 적는다.
    ("v3-full", "PC01", 1): ("부분", ["R3"], "Q01: 바닥은 안 보이고 작업면 방울만. seen은 질문 복사"),
    ("v3-full", "PC01", 2): ("맞음", ["R1"], "Q03 끓는 기름. seen이 다른 질문(Q04) 문장 복사"),
    ("v3-full", "PC02", 1): ("맞음", ["R1"], "Q03 불꽃. '기름이 끓고'는 과장(양념 조리)"),
    ("v3-full", "PC04", 1): ("맞음", ["R1"], "Q02 바닥 물건. seen은 질문 복사"),
    ("v3-full", "PC06", 1): ("맞음", ["R2"], "Q06 플러그"),
    ("v3-regions", "PC01", 1): ("부분", ["R3"], "전체와 같음(5개 영역 모두 yes)"),
    ("v3-regions", "PC01", 2): ("맞음", ["R1"], "전체와 같음"),
    ("v3-regions", "PC02", 1): ("맞음", ["R1"], "전체와 같음"),
    ("v3-regions", "PC04", 1): ("맞음", ["R1"], "전체와 같음"),
    ("v3-regions", "PC06", 1): ("맞음", ["R2"], "전체와 같음"),
    ("v3-regions", "PC07", 1): ("맞음", ["R3"], "Q09 날붙이(오른쪽 위 영역에서만). seen이 '날짜, 날짜…' 반복으로 망가짐"),
}

# 위치가 맞는지(작성자 판단). v2는 where 문장, v3는 where 코드 기준. v1은 고정 위치가 없어 제외.
WHERE_OK = {
    ("v2", "PC01", 1): False, ("v2", "PC01", 2): False, ("v2", "PC02", 1): False, ("v2", "PC04", 1): True,
    ("v2", "PC04", 2): False, ("v2", "PC06", 1): False,
    ("v3-full", "PC01", 1): False, ("v3-full", "PC01", 2): True, ("v3-full", "PC02", 1): True,
    ("v3-full", "PC04", 1): False, ("v3-full", "PC06", 1): False,
    ("v3-regions", "PC01", 1): False, ("v3-regions", "PC01", 2): True, ("v3-regions", "PC02", 1): True,
    ("v3-regions", "PC04", 1): False, ("v3-regions", "PC06", 1): False, ("v3-regions", "PC07", 1): False,
}


def load(version):
    f = {"v1": "cloud_outputs_observe_v1.json", "v2": "cloud_outputs_observe_v2.json",
         "v3-full": "cloud_outputs_observe_v3.json", "v3-regions": "cloud_outputs_observe_v3.json"}[version]
    return json.loads((ROOT / "cloud" / "outputs" / f).read_text(encoding="utf-8"))


def main():
    em = EquipmentMap(S04Pipeline(ROOT / "config" / "pipeline_config.json").kb.rows)
    out_dir = ROOT / "runs" / "observe"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, all_obs = [], {}
    for ver in ("v1", "v2", "v3-full", "v3-regions"):
        d = load(ver)
        mv = f'{d["model_id"]}@{d["revision"][:12]}+observe-{ver}'.replace("/", "_")
        results = d["results"]
        if ver.startswith("v3"):
            grouped = {}
            for r in d["results"]:
                m = re.search(r"__(tl|tr|bl|br)\.jpg$", r["image_file"])
                rg = m.group(1) if m else "full"
                g = grouped.setdefault(r["case_id"], {"case_id": r["case_id"], "photo_id": r["photo_id"], "contents": {},
                                                       "seconds": 0.0, "input_tokens": 0, "output_tokens": 0})
                att = r["attempts"][r["accepted_attempt"] - 1]
                if ver == "v3-full" and rg != "full":
                    continue
                g["contents"][rg] = att["content"]
                g["seconds"] += att["seconds"]
                g["input_tokens"] += r["input_tokens"]
                g["output_tokens"] += att["output_tokens"]
            results = list(grouped.values())
        for r in results:
            req = json.loads((ROOT / "inputs" / "photo_cases" / f'{r["case_id"]}.json').read_text(encoding="utf-8"))
            loc = req["field_input"]["photos"][0]["location_label"]
            if ver.startswith("v3"):
                regs = ("full",) if ver == "v3-full" else ("full", "tl", "tr", "bl", "br")
                obs, st = merge_v3(r["contents"], r["photo_id"], loc, mv, em, regs)
                att = {"seconds": r["seconds"], "output_tokens": r["output_tokens"]}
                idx = 0
                st["parse_error"] = None if not st["parse_fail_regions"] else f'{st["parse_fail_regions"]}개 영역 실패'
            else:
                idx = (r["accepted_attempt"] - 1) if (ver == "v1" and r.get("accepted_attempt")) else 0
                att = r["attempts"][idx]
                fn = postprocess if ver == "v1" else postprocess_v2
                obs, st = fn(att["content"], r["photo_id"], loc, mv, em)
            all_obs[(ver, r["case_id"])] = obs
            refs = REF[r["case_id"]]
            judged = [REVIEW.get((ver, r["case_id"], i + 1), ("미검토", [], "")) for i in range(len(obs))]
            for i_, (o, j) in enumerate(zip(obs, judged)):
                o["author_review"] = {"judgement": j[0], "matched_ref": j[1], "note": j[2],
                                      "where_ok": WHERE_OK.get((ver, r["case_id"], i_ + 1))}
            matched = {x for j in judged for x in j[1]}
            rows.append({
                "version": ver, "case_id": r["case_id"], "attempt_used": idx + 1, "seconds": att["seconds"],
                "input_tokens": r["input_tokens"], "output_tokens": att["output_tokens"], "parse_error": st.get("parse_error"),
                "observations": len(obs), "equipment_term_flag": st["equipment_term_flag"],
                "review": dict(Counter(j[0] for j in judged)), "ref_total": len(refs), "ref_matched": len(matched),
                "stats": st,
            })
    summ = {}
    for ver in ("v1", "v2", "v3-full", "v3-regions"):
        r = [x for x in rows if x["version"] == ver]
        wk = [v for (vv, _, _), v in WHERE_OK.items() if vv == ver]
        rev = sum((Counter(x["review"]) for x in r), Counter())
        summ[ver] = {
            "photos": len(r), "parse_ok_attempt_used": sum(x["parse_error"] is None for x in r),
            "observations": sum(x["observations"] for x in r),
            "review": dict(rev),
            "ref_recall": f'{sum(x["ref_matched"] for x in r)}/{sum(x["ref_total"] for x in r)}',
            "negative_photo_PC03_obs": next(x["observations"] for x in r if x["case_id"] == "PC03"),
            "equipment_term_flag": sum(x["equipment_term_flag"] for x in r),
            "dup_dropped": sum(x["stats"].get("dropped_dup", 0) for x in r),
            "seconds_total": round(sum(x["seconds"] for x in r), 1),
            "where_correct": f"{sum(wk)}/{len(wk)}" if wk else "해당 없음",
            "seen_copies_question": sum(x["stats"].get("seen_copies_question", 0) for x in r),
        }
    res = {"generated_at": now_kst(), "note": "내부 평가. 판정은 작성자(비전문가) 검토이며 정답 라벨이 아니다. 사진 8장.",
           "summary": summ, "rows": rows,
           "observations": {f"{v}|{c}": o for (v, c), o in all_obs.items()}}
    (out_dir / "observe_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
