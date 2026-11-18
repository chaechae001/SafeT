"""실제사진 테스트 케이스(PC01~PC08)를 v2 요청 형식으로 만든다.

- 사진: inputs/photo_cases/images/*_1280.jpg (원본 실제사진/ 축소 사본, images_manifest.json에 원본 sha256 기록)
- 장소(location_label): 작성자가 사진을 보고 붙인 합성 입력이다(현장 사용자 입력 아님).
- 탐지(detections): 기기마스터 평가셋(261115_기기인식_평가셋_v1_DR.json)의 라벨을 '탐지 결과 대용(oracle_label)'으로 넣는다.
  그 라벨도 'AI 보조 라벨, 사람 검수 전'이며 bbox는 3×3 격자에서 만든 대략값이다. 탐지 성능 평가에 쓰면 안 된다.
python src/build_photo_cases.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT  # noqa: E402

EVAL = ROOT.parent / "261115_기기마스터_인식평가셋_DR" / "261115_기기인식_평가셋_v1_DR.json"
CASES = [
    ("PC01", "261113_P04_bApoYZBPCLE_0513.00s_DR", "주방 튀김기 앞"),
    ("PC02", "C03_kkubeurakko_process_3", "주방 화구"),
    ("PC03", "G02_goobne_fryer", "주방"),
    ("PC04", "brave_ZcRVMActFC", "주방 세척대 주변"),
    ("PC05", "seongdong_kyochon_1", "주방 튀김 구역"),
    ("PC06", "seongdong_nene_geumho_1", "주방 냉장고 위 벽면"),
    ("PC07", "seongdong_nene_seongsu_3", "주방 세척대·화구 구역"),
    ("PC08", "seongdong_bbq_haengdang_4", "주방 작업대"),
]


def main():
    ev = {im["image_id"]: im for im in json.loads(EVAL.read_text(encoding="utf-8"))["images"]}
    out_dir = ROOT / "inputs" / "photo_cases"
    for cid, image_id, loc in CASES:
        im = ev[image_id]
        pid = f"{cid}-photo-1"
        dets = [{"detection_id": f"{cid}-det-{i + 1}", "photo_id": pid, "equipment_id": l["equipment_id"],
                 "bbox_norm": l["bbox_norm_from_grid"], "confidence": None, "source": "oracle_label",
                 "detector_version": f'evalset:{image_id}#{l["label_id"].split("#")[1]}'} for i, l in enumerate(im["labels"])]
        req = {
            "request_id": f"photo-{cid}-261116", "assessment_id": f"PHOTO-{cid}-SYNTHETIC", "criteria_version": None,
            "business": {"industry": "치킨"},
            "equipment": [],
            "detections": dets,
            "field_input": {
                "photos": [{"photo_id": pid, "url": f"https://safe-t.local/photo_cases/{image_id}_1280.jpg", "location_label": loc}],
                "text": None, "voice_transcripts": []},
        }
        (out_dir / f"{cid}.json").write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
        print(cid, image_id, [d["equipment_id"] for d in dets])
    meta = {"note": "장소는 작성자 합성 입력. detections는 평가셋 라벨(AI 보조, 검수 전)을 탐지 결과 대용으로 넣은 oracle_label.",
            "cases": [{"case_id": c, "image_id": i, "image_file": f"images/{i}_1280.jpg", "location_label": l} for c, i, l in CASES]}
    (out_dir / "photo_cases_index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
