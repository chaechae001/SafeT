"""STT 결과 문장에서 기기를 찾는 방식 비교(기존: 이름·동의어 포함 / 보강: 공백 무시·표준명 분해·별칭·한 글자 근사). 정답 기기는 작성자가 문장별로 정한 값(합성)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from hitl_graph import LocalData, match_equipment  # noqa: E402
GOLD = {"S01": {"EQ_FRYER"}, "S02": {"EQ_GAS_RANGE"}, "S03": {"EQ_KNIFE_BOARD"}, "S04": {"EQ_MEAT_SLICER"}, "S05": {"EQ_WALKIN_COOLER"},
        "S06": {"EQ_EXHAUST_HOOD"}, "S07": {"EQ_DOUGH_MIXER"}, "S08": {"EQ_DISHWASHER", "EQ_ELECTRIC_PANEL"}, "S09": {"EQ_SHELF", "EQ_LADDER"},
        "S10": {"EQ_MOTORCYCLE"}, "S11": {"EQ_SOUP_KETTLE"}, "S12": {"EQ_ELECTRIC_PANEL"}}
cfg = json.loads((ROOT / "config" / "hitl_graph_config.json").read_text(encoding="utf-8"))["text_match"]
d = LocalData(); names = d.names()
out = {}
for tag in ("cuda_int8f16",):
    r = json.loads((ROOT / "stt_test" / "outputs" / f"out_{tag}.json").read_text(encoding="utf-8"))
    for mode in ("old", "new"):
        tp = fp = fn = 0; rows = []
        for x in r["results"]:
            sid, cond = x["file"][:3], x["file"][4:-4]
            got = set(d.match(x["text"])) if mode == "old" else {h["equipment_id"] for h in match_equipment(names, x["text"], cfg["aliases"], cfg["fuzzy_min_len"])}
            g = GOLD[sid]; tp += len(got & g); fp += len(got - g); fn += len(g - got)
            rows.append({"id": sid, "cond": cond, "text": x["text"], "got": sorted(got), "miss": sorted(g - got), "extra": sorted(got - g)})
        out[mode] = {"recall": round(tp / (tp + fn), 3), "precision": round(tp / (tp + fp), 3) if tp + fp else None, "tp": tp, "fp": fp, "fn": fn, "rows": rows}
        print(mode, {k: out[mode][k] for k in ("recall", "precision", "tp", "fp", "fn")})
(ROOT / "stt_test" / "outputs" / "text_match_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for r in out["new"]["rows"]:
    if r["miss"] or r["extra"]: print("new", r["id"], r["cond"], r["miss"], r["extra"], r["text"])
