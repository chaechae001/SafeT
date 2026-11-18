"""Cloud 실행용: 34장 이미지에 탐지 모델을 돌려 v2 형식(초안) 결과를 낸다.

사용:
  python detect_compare.py --model yolo_coco  --weights yolo11x.pt        --inputs DIR --out out_yolo_coco.json
  python detect_compare.py --model yolo_world --weights yolov8x-worldv2.pt --inputs DIR --out out_yolo_world.json
  python detect_compare.py --model sam3 --inputs DIR --out out_sam3.json      (HF 접근 승인 후)
DIR에는 images/*.jpg, class_map.json이 있어야 한다.
모델 단계 점수 하한은 0.05로 낮게 두고, 임계값 T는 로컬 채점에서 바꿔 본다.
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import time

SCORE_FLOOR = 0.05


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def prompts_from_map(rows):
    """오픈 어휘용 (프롬프트, equipment_id) 목록. detection_target=yes만."""
    out = []
    for r in rows:
        if r['detection_target'] != 'yes':
            continue
        for p in r['open_vocab_prompt_draft'].split(';'):
            p = p.strip()
            if p:
                out.append((p, r['equipment_id']))
    return out


def coco_map(rows):
    m = {}
    for r in rows:
        if r['coco_class'] and r['coco_match'] == 'direct' and r['detection_target'] == 'yes':
            m.setdefault(r['coco_class'], []).append((r['equipment_id'], 'direct'))
    for r in rows:
        if r['coco_class'] and r['coco_match'] == 'partial':
            m.setdefault(r['coco_class'], []).append((r['equipment_id'], 'partial'))
    return m


def norm_box(xyxy, w, h):
    x0, y0, x1, y1 = [float(v) for v in xyxy]
    return [round(max(0, min(1, x0 / w)), 4), round(max(0, min(1, y0 / h)), 4),
            round(max(0, min(1, x1 / w)), 4), round(max(0, min(1, y1 / h)), 4)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True, choices=['yolo_coco', 'yolo_world', 'sam3'])
    ap.add_argument('--weights')
    ap.add_argument('--inputs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--imgsz', type=int, default=1280)
    a = ap.parse_args()

    import torch
    from PIL import Image
    rows = json.load(open(os.path.join(a.inputs, 'class_map.json'), encoding='utf-8'))
    img_dir = os.path.join(a.inputs, 'images')
    files = sorted(f for f in os.listdir(img_dir) if f.endswith('.jpg'))
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    torch.cuda.reset_peak_memory_stats() if dev == 'cuda' else None
    t_load0 = time.time()
    prompt_list = prompts_from_map(rows)
    detector = {'model_name': a.model, 'model_version': None, 'weights_sha256': None,
                'class_map_version': '261116_사전학습클래스_대응표_v1', 'score_threshold_applied': SCORE_FLOOR,
                'prompt_set_version': None}

    if a.model in ('yolo_coco', 'yolo_world'):
        import ultralytics
        from ultralytics import YOLO
        model = YOLO(a.weights)
        detector['model_version'] = f'ultralytics {ultralytics.__version__} / {os.path.basename(a.weights)}'
        wpath = a.weights if os.path.exists(a.weights) else getattr(model, 'ckpt_path', a.weights)
        detector['weights_sha256'] = sha256_file(wpath) if os.path.exists(wpath) else None
        if a.model == 'yolo_world':
            model.set_classes([p for p, _ in prompt_list])
            detector['prompt_set_version'] = 'open_vocab_prompt_draft v1'
        cmap = coco_map(rows)
    else:
        from sam3.model_builder import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor
        model = build_sam3_image_model()
        # 기본 confidence_threshold는 0.5. 임계값 비교를 위해 점수 하한과 같게 낮춘다.
        # 공식 예제처럼 bf16 autocast 안에서 추론한다(없으면 BFloat16/Float dtype 오류, 2026-11-16 1차 실패).
        proc = Sam3Processor(model, confidence_threshold=SCORE_FLOOR); torch.autocast('cuda', dtype=torch.bfloat16).__enter__()
        detector['model_version'] = 'facebook/sam3 (official repo)'
        detector['prompt_set_version'] = 'open_vocab_prompt_draft v1'
    load_s = time.time() - t_load0

    photos, dets, per_image_s = [], [], []
    for fn in files:
        pid = fn[:-4]
        img = Image.open(os.path.join(img_dir, fn)).convert('RGB')
        W, H = img.size
        t0 = time.time()
        try:
            n = 0
            if a.model in ('yolo_coco', 'yolo_world'):
                res = model.predict(img, conf=SCORE_FLOOR, imgsz=a.imgsz, device=0 if dev == 'cuda' else 'cpu', verbose=False)[0]
                names = res.names
                for b in res.boxes:
                    ci = int(b.cls.item())
                    conf = float(b.conf.item())
                    box = norm_box(b.xyxy[0].tolist(), W, H)
                    if a.model == 'yolo_world':
                        p, eid = prompt_list[ci]
                        targets = [(eid, 'open_vocab')]
                        dclass = p
                    else:
                        dclass = names[ci]
                        targets = cmap.get(dclass, [(None, None)])
                    for eid, match in targets:
                        n += 1
                        dets.append({'detection_id': f'd{len(dets) + 1}', 'photo_id': pid, 'equipment_id': eid,
                                     'detector_class': dclass, 'class_map_match': match, 'confidence': round(conf, 4), 'bbox': box})
            else:
                state = proc.set_image(img)
                for p, eid in prompt_list:
                    out = proc.set_text_prompt(state=state, prompt=p)
                    for box, sc in zip(out['boxes'].tolist(), out['scores'].tolist()):
                        if sc < SCORE_FLOOR:
                            continue
                        n += 1
                        dets.append({'detection_id': f'd{len(dets) + 1}', 'photo_id': pid, 'equipment_id': eid,
                                     'detector_class': p, 'class_map_match': 'open_vocab', 'confidence': round(float(sc), 4),
                                     'bbox': norm_box(box, W, H)})
            photos.append({'photo_id': pid, 'status': 'analyzed', 'error_code': None, 'width': W, 'height': H})
        except Exception as e:  # 사진별 실패 기록
            photos.append({'photo_id': pid, 'status': 'failed', 'error_code': type(e).__name__ + ': ' + str(e)[:200], 'width': W, 'height': H})
        per_image_s.append(round(time.time() - t0, 3))

    ok = sum(p['status'] == 'analyzed' for p in photos)
    status = 'ok' if ok == len(photos) else ('failed' if ok == 0 else 'partial')
    result = {
        'model_output': {
            'request_id': f'detect_compare_{a.model}', 'status': status, 'error_code': None, 'detector': detector,
            'master_version': 'v1-draft', 'judged_at': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec='seconds'),
            'photos': photos, 'detections': dets},
        'run_meta': {
            'python': platform.python_version(), 'torch': torch.__version__, 'cuda_available': dev == 'cuda',
            'gpu_name': torch.cuda.get_device_name(0) if dev == 'cuda' else None,
            'max_gpu_mem_allocated_gb': round(torch.cuda.max_memory_allocated() / 1e9, 3) if dev == 'cuda' else None,
            'model_load_s': round(load_s, 2), 'per_image_s': per_image_s,
            'mean_image_s': round(sum(per_image_s) / len(per_image_s), 3), 'imgsz': a.imgsz, 'n_prompts': len(prompt_list)},
    }
    json.dump(result, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('DONE', a.model, status, 'dets', len(dets), 'mean_s', result['run_meta']['mean_image_s'], 'maxmem_gb', result['run_meta']['max_gpu_mem_allocated_gb'])


if __name__ == '__main__':
    main()
