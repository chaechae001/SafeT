"""기기별 위험요인 후보를 RAG 인덱스 v2에서 찾는다(모델 호출 없음).

데이터는 저장소에 없다. 원문 문장이 들어 있고 재배포 조건이 확인되지 않아 Cloud 비공개 폴더에 둔다.
  SAFET_RAG_DIR=/home/elicer/safet/data/rag/safet_rag_data_v1   (비어 있으면 기능 꺼짐)
폴더의 MANIFEST.json 해시와 맞는 검색용 파일만 읽는다. 평가 전용 파일(정답셋·검수표)은 읽지 않는다.

정렬은 실험 파이프라인의 R_index_v2와 같다.
  - 실제 사례(CASE-*) 출처는 쓰지 않는다(평가 정답과 같은 기록이라 누출 방지).
  - 근거 등급 A(위험 문장에 기기명)를 먼저, 같은 등급은 출처가 많은 순서.
  - 기기 여러 대: 코드별로 가장 좋은 등급과 서로 다른 출처 수를 합쳐 정렬.
  - 대책은 관련도 1~3등급만(4등급은 '같은 표 행일 뿐'이라 뺀다).
결과는 추천 후보와 근거다. 위험도 판정이나 법적 기준이 아니다.
"""
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

from services.auth import AuthError

INDEX_FILE = '261116_RAG_기기위험요인인덱스_v2_DR.json'
MAX_MEASURES = 3
MAX_EQUIPMENT = 10


def data_dir():
    value = os.getenv('SAFET_RAG_DIR', '').strip()
    return Path(value) if value else None


def enabled():
    return data_dir() is not None


@lru_cache(maxsize=4)
def _load(path: str, mtime: float):
    root = Path(path)
    try:
        manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise AuthError(503, 'RAG_DATA_UNAVAILABLE', 'RAG 데이터 위치를 확인해 주세요.') from None
    if INDEX_FILE not in manifest.get('roles', {}).get('retrieval', []):
        raise AuthError(503, 'RAG_DATA_INVALID', 'RAG 데이터 구성을 확인해 주세요.')
    expected = {f['file']: f['sha256'] for f in manifest.get('files', [])}
    raw = (root / INDEX_FILE).read_bytes() if (root / INDEX_FILE).is_file() else b''
    if not raw or hashlib.sha256(raw).hexdigest() != expected.get(INDEX_FILE):
        raise AuthError(503, 'RAG_DATA_INVALID', 'RAG 데이터 무결성 확인에 실패했어요.')
    index = json.loads(raw.decode('utf-8'))
    by_eq = {e['equipment_id']: e for e in index.get('index', [])}
    no_evidence = {(x['equipment_id'] if isinstance(x, dict) else x) for x in index.get('no_evidence', [])}
    return {'version': manifest.get('name'), 'index_sha256': expected[INDEX_FILE], 'by_eq': by_eq,
            'no_evidence': no_evidence, 'known': set(by_eq) | no_evidence}


def load():
    root = data_dir()
    if root is None:
        raise AuthError(503, 'RAG_DISABLED', 'RAG 검색이 꺼져 있어요.')
    manifest = root / 'MANIFEST.json'
    try:
        mtime = manifest.stat().st_mtime
    except OSError:
        raise AuthError(503, 'RAG_DATA_UNAVAILABLE', 'RAG 데이터 위치를 확인해 주세요.') from None
    return _load(str(root), mtime)


def _sources(ids):
    return [s for s in ids if not s.startswith('CASE-')]


def candidates(equipment_ids, k=None):
    """기기 ID 목록 → 위험 코드 후보(근거 출처·문장·대책 포함), 정렬된 순서."""
    ids = list(dict.fromkeys(equipment_ids or []))
    if not ids or len(ids) > MAX_EQUIPMENT:
        raise AuthError(422, 'INVALID_EQUIPMENT', f'기기는 1~{MAX_EQUIPMENT}개를 지정해 주세요.')
    data = load()
    unknown = [e for e in ids if e not in data['known']]
    if unknown:
        raise AuthError(422, 'UNKNOWN_EQUIPMENT', '알 수 없는 기기가 있어요.', unknown=unknown)
    agg = {}
    for e in ids:
        for h in data['by_eq'].get(e, {}).get('hazards', []):
            src = _sources(h.get('source_ids', []))
            if not src:
                continue
            c = agg.setdefault(h['hazard_code'], {'hazard_code': h['hazard_code'], 'tier': 'Z', 'source_ids': [],
                                                  'equipment_ids': [], 'hazard_texts': [], 'measures': []})
            c['tier'] = min(c['tier'], min(h.get('tiers') or ['Z']))
            c['equipment_ids'].append(e)
            c['source_ids'] += [s for s in src if s not in c['source_ids']]
            c['hazard_texts'] += [t for t in (h.get('hazard_texts') or [])[:2] if t not in c['hazard_texts']]
            for m in h.get('measures', []):
                ms = _sources(m.get('source_ids', []))
                if m.get('relevance_rank', 9) <= 3 and ms and m['text'] not in [x['text'] for x in c['measures']]:
                    c['measures'].append({'text': m['text'], 'source_ids': ms, 'relevance_rank': m['relevance_rank']})
    out = sorted(agg.values(), key=lambda c: (c['tier'], -len(c['source_ids'])))
    for rank, c in enumerate(out, 1):
        c['rank'] = rank
        c['n_sources'] = len(c['source_ids'])
        c['measures'] = sorted(c['measures'], key=lambda m: m['relevance_rank'])[:MAX_MEASURES]
    if k:
        out = out[:k]
    return {'data_version': data['version'], 'index_sha256': data['index_sha256'],
            'candidates': out, 'no_evidence': [e for e in ids if e in data['no_evidence'] or e not in data['by_eq']],
            'notice': '문헌 근거 기반 추천 후보입니다. 적용 여부와 위험도는 현장에서 확인해 주세요.'}
