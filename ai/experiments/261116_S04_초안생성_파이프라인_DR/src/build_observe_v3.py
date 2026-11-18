"""관찰 3판 준비: 영역 사본(전체 + 겹치는 4분할)을 만들고 프롬프트·업로드 묶음을 만든다. 모델 호출 없음.
uv run --with pillow python src/build_observe_v3.py
→ inputs/photo_cases/images/regions/*.jpg, cloud/prompts_observe_v3.json, cloud/observe_bundle_v3.zip
"""
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from observe import PROMPT_VERSION_V3, REGIONS, build_messages_v3  # noqa: E402
from s04_pipeline import ROOT  # noqa: E402

PC = ROOT / "inputs" / "photo_cases"


def main():
    idx = json.loads((PC / "photo_cases_index.json").read_text(encoding="utf-8"))
    (PC / "images" / "regions").mkdir(parents=True, exist_ok=True)
    calls, files = [], []
    for c in idx["cases"]:
        req = json.loads((PC / f'{c["case_id"]}.json').read_text(encoding="utf-8"))
        pid = req["field_input"]["photos"][0]["photo_id"]
        im = Image.open(PC / c["image_file"]).convert("RGB")
        w, h = im.size
        stem = Path(c["image_file"]).stem
        for rg, (x0, y0, x1, y1) in REGIONS.items():
            if rg == "full":
                rel = c["image_file"]
            else:
                rel = f"images/regions/{stem}__{rg}.jpg"
                im.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))).save(PC / rel, quality=92)
            files.append(rel)
            calls.append({"case_id": c["case_id"], "photo_id": pid, "region": rg, "image_file": rel,
                          "expect_key": "answers", "messages": build_messages_v3(rg)})
    (ROOT / "cloud" / "prompts_observe_v3.json").write_text(
        json.dumps({"prompt_version": PROMPT_VERSION_V3, "regions": REGIONS, "calls": calls}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    with zipfile.ZipFile(ROOT / "cloud" / "observe_bundle_v3.zip", "w", zipfile.ZIP_STORED) as z:
        z.write(ROOT / "cloud" / "prompts_observe_v3.json", "prompts_observe_v3.json")
        for rel in sorted(set(files)):
            z.write(PC / rel, rel)
    print(len(calls), "calls,", len(set(files)), "images")


if __name__ == "__main__":
    main()
