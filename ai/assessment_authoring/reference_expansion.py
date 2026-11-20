"""검수된 위험·예방 문맥을 기존 인덱스에 비파괴적으로 덧붙인다."""
import copy
import hashlib
import json
from pathlib import Path


def expand(response, root):
    if not root:
        return response
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['version'] != 'N02-N08-context-1' or manifest['file'] != 'contexts.json':
        raise ValueError('unsupported context manifest')
    raw = (root / manifest['file']).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest['sha256']:
        raise ValueError('context hash mismatch')
    rows = json.loads(raw)
    if len(rows) != 2 or {r['doc_id'] for r in rows} != {'N02', 'N08'}:
        raise ValueError('unexpected context set')
    for r in rows:
        expected = {'N02': ('burn', 12), 'N08': ('slip', 7)}[r['doc_id']]
        if (r['hazard_code'], r['pdf_pages'][0]) != expected or r['review_status'] != 'pdf_verified':
            raise ValueError('unreviewed source scope')
        if not r['hazard_text'].strip() or not r['prevention_text'].strip():
            raise ValueError('empty context')
    out = copy.deepcopy(response)
    out['context_version'] = manifest['version']
    out['context_sha256'] = digest
    for candidate in out['candidates']:
        if 'EQ_FRYER' not in candidate['equipment_ids']:
            continue
        for r in rows:
            if candidate['hazard_code'] != r['hazard_code']:
                continue
            detail = {k: copy.deepcopy(v) for k,v in r.items() if k != 'hazard_code'}
            detail['link_id'] = manifest['version'] + ':' + r['doc_id']
            candidate['hazard_texts'].append(r['hazard_text'])
            candidate['source_ids'].append(r['source_id'])
            candidate.setdefault('source_evidence', []).append(detail)
    return out
