"""입력 기기·문장 → 기기마스터 equipment_id → 관련 위험요인 → 점검표 행 매핑표를 CSV로 내보낸다(TC01 + 사례 6건).
python src/export_equipment_mapping.py → runs/improve_round3/261116_기기_위험요인_점검표_매핑_DR.csv
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dump_prompts_v3 import REQS  # noqa: E402
from equipment_map import EquipmentMap  # noqa: E402
from s04_pipeline import ROOT, S04Pipeline  # noqa: E402

pipe = S04Pipeline(ROOT / "config" / "pipeline_config.json")
em = EquipmentMap(pipe.kb.rows)
out = ROOT / "runs" / "improve_round3" / "261116_기기_위험요인_점검표_매핑_DR.csv"
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["request_id", "input_kind", "input_text", "equipment_id", "standard_name", "hazard_codes(근거)",
                "checklist_rows_mapped", "checklist_sections", "note"])
    for rp in REQS:
        req = json.loads(rp.read_text(encoding="utf-8"))
        items = [("equipment", e["name"]) for e in req["equipment"]]
        fi = req["field_input"]
        items += [("text", s) for s in pipe.normalize(req)["sentences"] and [x for _, x in pipe.normalize(req)["sentences"]]]
        for kind, text in items:
            eids = em.match(text)
            if not eids:
                if kind == "equipment":
                    w.writerow([req["request_id"], kind, text, "", "", "", "", "", "기기마스터에서 찾지 못함"])
                elif not req["equipment"]:
                    w.writerow([req["request_id"], kind, text, "", "", "", "", "", "문장에서 기기를 찾지 못함(필터 미적용)"])
                continue
            for eid in eids:
                rows = em.rows_for([eid])
                secs = sorted({pipe.kb.rows[r]["source_section"] for r in rows})
                codes = em.codes([eid])
                w.writerow([req["request_id"], kind, text, eid, em.equipment[eid]["standard_name"],
                            " ".join(f"{c}({v})" for c, v in codes.items()), " ".join(rows), " / ".join(secs),
                            "" if rows else "기기마스터에 점검표 출처 없음 → 위험요인 코드 낱말로 후보 검색"])
print(out)
