"""SAM 3 올림·1회 추론·내림 시간 측정(합성 빈 이미지, 회사 사진 미사용). 사용: python sam3_load_probe.py TIMELINE"""
import json, sys, time, datetime, gc
KST = datetime.timezone(datetime.timedelta(hours=9))
tl = open(sys.argv[1], "a", encoding="utf-8")
def mark(ev, **kw):
    tl.write(json.dumps({"t": time.time(), "at": datetime.datetime.now(KST).isoformat(timespec="seconds"), "event": ev, **kw}) + "\n"); tl.flush()
import torch
from PIL import Image
from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
mark("sam3_load_start")
model = build_sam3_image_model()
proc = Sam3Processor(model, confidence_threshold=0.3)
torch.cuda.synchronize(); mark("sam3_load_done", alloc_gb=round(torch.cuda.memory_allocated() / 1e9, 3))
with torch.autocast("cuda", dtype=torch.bfloat16):
    st = proc.set_image(Image.new("RGB", (1024, 768), (128, 128, 128)))
    out = proc.set_text_prompt(state=st, prompt="deep fryer")
torch.cuda.synchronize(); mark("sam3_infer_done", peak_gb=round(torch.cuda.max_memory_allocated() / 1e9, 3))
mark("sam3_unload_start")
del model, proc, st, out; gc.collect(); torch.cuda.empty_cache(); torch.cuda.synchronize()
mark("sam3_unload_done_inproc", alloc_gb=round(torch.cuda.memory_allocated() / 1e9, 3))
