"""Cloud 탐지 결과를 이미지 단위로 채점한다(로컬).

실행(작업 폴더 루트에서): python 261116_기기탐지_YOLO전환_DR/scripts/score_image_level.py <out_*.json> ...
출력: cloud/score_image_level_v2.json(v1은 보존), 표준출력 요약
F1 = 정밀도와 전체 clear 재현율(범위 밖 누락 포함)의 조화평균

정답 규칙(평가셋은 AI 보조 라벨, 사람 검수 전):
- 양성 P: visibility=clear 라벨
- 무시 I: visibility=partial 라벨, uncertain_candidates의 후보 ID → 예측해도 오답 아님, 놓쳐도 감점 없음
- 채점 범위 C: 그 모델이 낼 수 있는 equipment_id(아래 scope). 범위 밖 양성은 '범위 밖 누락'으로 따로 센다
- 예측: 이미지별로 equipment_id의 최고 점수 >= T 이면 '있음'
"""
import collections
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
OUT = os.path.join(ROOT, '261116_기기탐지_YOLO전환_DR')
TS = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def load_gt():
    ev = json.load(open(os.path.join(ROOT, '261115_기기마스터_인식평가셋_DR', '261115_기기인식_평가셋_v1_DR.json'), encoding='utf-8'))
    gt = {}
    for i in ev['images']:
        P = {l['equipment_id'] for l in i['labels'] if l['visibility'] == 'clear'}
        I = {l['equipment_id'] for l in i['labels'] if l['visibility'] != 'clear'} | {c['candidate_equipment_id'] for c in i['uncertain_candidates'] if c['candidate_equipment_id']}
        gt[i['image_id']] = (P, I - P)
    return gt


def scope_for(model_name, rows, include_partial):
    yes = {r['equipment_id'] for r in rows if r['detection_target'] == 'yes'}
    if model_name == 'yolo_coco':
        s = {r['equipment_id'] for r in rows if r['coco_match'] == 'direct'}
        if include_partial:
            s |= {r['equipment_id'] for r in rows if r['coco_match'] == 'partial'}
        return s & yes
    return yes


def score(out, gt, rows, include_partial):
    mo = out['model_output']
    name = mo['detector']['model_name']
    scope = scope_for(name, rows, include_partial)
    analyzed = {p['photo_id'] for p in mo['photos'] if p['status'] == 'analyzed'}
    best = collections.defaultdict(dict)
    for d in mo['detections']:
        if d['equipment_id'] is None or d['equipment_id'] not in scope:
            continue
        if d.get('class_map_match') == 'partial' and not include_partial:
            continue
        b = best[d['photo_id']]
        b[d['equipment_id']] = max(b.get(d['equipment_id'], 0), d['confidence'])
    sweep = []
    per_eid_at = {}
    for T in TS:
        tp = fp = fn = 0
        all_pos = out_scope = 0
        pe = collections.defaultdict(lambda: collections.Counter())
        for pid, (P, I) in gt.items():
            if pid not in analyzed:
                continue
            pred = {e for e, c in best[pid].items() if c >= T}
            all_pos += len(P)
            out_scope += len(P - scope)
            for e in pred & P:
                tp += 1; pe[e]['tp'] += 1
            for e in pred - P - I:
                fp += 1; pe[e]['fp'] += 1
            for e in (P & scope) - pred:
                fn += 1; pe[e]['fn'] += 1
        prec = tp / (tp + fp) if tp + fp else None
        rec_scope = tp / (tp + fn) if tp + fn else None
        rec_all = tp / all_pos if all_pos else None
        f1_all = 2 * prec * rec_all / (prec + rec_all) if prec and rec_all else 0.0
        sweep.append({'T': T, 'tp': tp, 'fp': fp, 'fn_in_scope': fn, 'precision': prec and round(prec, 3),
                      'recall_in_scope': rec_scope and round(rec_scope, 3),
                      'recall_all_clear_labels': round(rec_all, 3), 'f1_all_clear_labels': round(f1_all, 3),
                      'clear_labels_out_of_scope': out_scope})
        per_eid_at[T] = {e: dict(c) for e, c in sorted(pe.items())}
    return {'model': name, 'model_version': mo['detector']['model_version'], 'include_partial': include_partial,
            'scope_size': len(scope), 'photos_analyzed': len(analyzed), 'status': mo['status'],
            'run_meta': out.get('run_meta'), 'sweep': sweep, 'per_equipment_by_T': per_eid_at}


def main(paths):
    gt = load_gt()
    rows = json.load(open(os.path.join(OUT, '261116_사전학습클래스_대응표_v1_DR.json'), encoding='utf-8'))['rows']
    results = []
    for p in paths:
        out = json.load(open(p, encoding='utf-8'))
        variants = [False, True] if out['model_output']['detector']['model_name'] == 'yolo_coco' else [False]
        for inc in variants:
            r = score(out, gt, rows, inc)
            r['source_file'] = os.path.basename(p)
            results.append(r)
            print(f"== {r['source_file']} {r['model']} partial={inc} scope={r['scope_size']} photos={r['photos_analyzed']} status={r['status']}")
            for s in r['sweep']:
                if s['T'] in (0.1, 0.25, 0.4, 0.5, 0.7):
                    print('  ', s)
    res = {'scored_date_kst': '2026-11-16', 'gt': '261115_기기인식_평가셋_v1_DR.json (AI 보조 라벨, 사람 검수 전)',
           'rules': __doc__, 'results': results}
    json.dump(res, open(os.path.join(OUT, 'cloud', 'score_image_level_v2.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main(sys.argv[1:])
