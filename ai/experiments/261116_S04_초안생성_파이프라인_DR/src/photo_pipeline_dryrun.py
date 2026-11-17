"""사진 케이스(PC01~PC08) 위험 항목 생성 단계 준비·점검(모델 호출 없음).

1) 프롬프트 묶음: 탐지 결과(oracle_label) 기기 + 관찰(v2, 1회차) 문장으로 A3 항목 프롬프트를 만든다
   → cloud/prompts_s04_photo_items_dryrun.json (Cloud 미실행)
2) 모의 점검(mock_llm, 실제 모델 출력 아님): PC04에 관찰 ID를 인용한 항목 1개와 인용하지 않은 항목 1개를 넣어
   - 관찰 근거 없는 항목이 제외되지 않고 off(insufficient_input)가 되는지
   - 응답이 contract_v2 스키마를 통과하는지 확인한다 → runs/photo_dryrun/
python src/photo_pipeline_dryrun.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dump_prompts_v3 import A3  # noqa: E402
from equipment_map import EquipmentMap  # noqa: E402
from observe import postprocess_v2  # noqa: E402
from s04_pipeline import ROOT, S04Pipeline, now_kst  # noqa: E402

OBS = json.loads((ROOT / "cloud" / "outputs" / "cloud_outputs_observe_v2.json").read_text(encoding="utf-8"))
OBS_VER = f'{OBS["model_id"]}@{OBS["revision"][:12]}+observe-v2-vqa'.replace("/", "_")


def observations_for(case_id: str, em) -> list[dict]:
    r = next(x for x in OBS["results"] if x["case_id"] == case_id)
    req = json.loads((ROOT / "inputs" / "photo_cases" / f"{case_id}.json").read_text(encoding="utf-8"))
    loc = req["field_input"]["photos"][0]["location_label"]
    obs, _ = postprocess_v2(r["attempts"][0]["content"], r["photo_id"], loc, OBS_VER, em)
    return obs


def pipe_for(mode: str, case_id: str, em, mock=None) -> S04Pipeline:
    pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json", mode=mode, mock_llm_path=mock)
    pipe.cfg["backend"]["llm"].update(A3)
    pipe.cfg["backend"]["llm"]["measure_stage"] = "c2"
    pipe.observations = observations_for(case_id, em)
    pipe.observation_stage_version = OBS_VER
    return pipe


def main():
    em = EquipmentMap(S04Pipeline(ROOT / "config" / "pipeline_config.json").kb.rows)
    out = {"created_at": now_kst(), "note": "Cloud 미실행(준비만). 기기=oracle_label, 관찰=observe-v2 1회차.", "calls": []}
    for f in sorted((ROOT / "inputs" / "photo_cases").glob("PC*.json")):
        cid = f.stem
        req = json.loads(f.read_text(encoding="utf-8"))
        pipe = pipe_for("llm", cid, em)
        d = pipe.dump_prompt(req)
        for c in d["calls"]:
            out["calls"].append({"case_id": cid, "request_id": req["request_id"], "unit_id": c["unit_id"],
                                 "messages": c["messages"], "expect_key": "items"})
        print(cid, "관찰", len(pipe.observations), "호출 단위", [c["unit_id"] for c in d["calls"]])
    (ROOT / "cloud" / "prompts_s04_photo_items_dryrun.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # 모의 점검
    out_dir = ROOT / "runs" / "photo_dryrun"
    out_dir.mkdir(parents=True, exist_ok=True)
    mock = out_dir / "mock_items_PC04.txt"
    mock.write_text("[모의 응답 — 실제 모델 출력 아님. off 규칙·v2 스키마 점검용]\n" + json.dumps({"items": [
        {"work": "통로 이동", "hazard": "바닥에 깔린 골판지에 걸려 넘어짐", "accident_type": "넘어짐", "cause": "통로 바닥에 골판지와 물건이 놓여 있음",
         "description": "골판지에 발이 걸려 넘어짐", "input_evidence": ["obs-PC04-photo-1-1"], "level": "medium", "level_reason": "요양이 필요한 부상 가능",
         "source_row_ids": [], "current_row_ids": [], "law_keys": []},
        {"work": "가스 사용", "hazard": "가스 누출에 의한 화재", "accident_type": "화재", "cause": "가스 용기 취급",
         "description": "가스가 새어 불이 남", "input_evidence": [], "level": "high", "level_reason": "사망 가능",
         "source_row_ids": [], "current_row_ids": [], "law_keys": []}]}, ensure_ascii=False), encoding="utf-8")
    req = json.loads((ROOT / "inputs" / "photo_cases" / "PC04.json").read_text(encoding="utf-8"))
    pipe = pipe_for("mock_llm", "PC04", em, mock)
    resp = pipe.run(req)
    errs = pipe.rv.errors("s04_draft.response.schema.json", resp)
    (out_dir / "PC04_mock_response.json").write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    check = {"v2_schema_valid": not errs, "errors": errs[:5], "status": resp["status"],
             "items": [(i["hazard"], i["signal"], i["off_reason_code"], i.get("observation_refs"), i.get("detection_refs"))
                       for i in resp.get("items", [])],
             "observations": len(resp.get("observations", [])), "analysis_stages": resp.get("analysis_stages")}
    (out_dir / "PC04_mock_check.json").write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(check, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
