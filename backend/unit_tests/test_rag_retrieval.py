"""RAG 후보 검색 규칙 검사. 실제 RAG 데이터 없이 합성 인덱스로 실행한다(원문 데이터는 저장소에 없음)."""
import hashlib, json, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT / 'backend'))
from services import rag_retrieval as rag
from services.auth import AuthError

INDEX = {'index': [
    {'equipment_id': 'EQ_A', 'hazards': [
        {'hazard_code': 'burn', 'tiers': ['B'], 'source_ids': ['S1', 'S2', 'S3'], 'hazard_texts': ['합성 화상 문장'],
         'measures': [{'text': '같은 행 대책', 'source_ids': ['S1'], 'relevance_rank': 4},
                      {'text': '기기명 대책', 'source_ids': ['S2'], 'relevance_rank': 1}]},
        {'hazard_code': 'cut', 'tiers': ['A'], 'source_ids': ['S4'], 'hazard_texts': ['합성 베임 문장'], 'measures': []},
        {'hazard_code': 'electric', 'tiers': ['A'], 'source_ids': ['CASE-X'], 'hazard_texts': ['사례 문장'],
         'measures': [{'text': '사례 대책', 'source_ids': ['CASE-X'], 'relevance_rank': 1}]}]},
    {'equipment_id': 'EQ_B', 'hazards': [
        {'hazard_code': 'burn', 'tiers': ['A'], 'source_ids': ['S5'], 'hazard_texts': ['B 화상'], 'measures': []}]}],
    'no_evidence': [{'equipment_id': 'EQ_NONE'}]}


def write(tmp_path, index=INDEX, tamper=False):
    raw = json.dumps(index, ensure_ascii=False).encode('utf-8')
    (tmp_path / rag.INDEX_FILE).write_bytes(raw)
    sha = hashlib.sha256(raw + (b'x' if tamper else b'')).hexdigest()
    (tmp_path / 'MANIFEST.json').write_text(json.dumps({'name': 'test_v1', 'roles': {'retrieval': [rag.INDEX_FILE]},
                                                         'files': [{'file': rag.INDEX_FILE, 'sha256': sha}]}), encoding='utf-8')
    rag._load.cache_clear()
    return tmp_path


def test_disabled_without_env(monkeypatch):
    monkeypatch.delenv('SAFET_RAG_DIR', raising=False)
    assert not rag.enabled()
    with pytest.raises(AuthError) as e:
        rag.candidates(['EQ_A'])
    assert e.value.code == 'RAG_DISABLED'


def test_order_tier_then_sources_and_case_excluded(tmp_path, monkeypatch):
    monkeypatch.setenv('SAFET_RAG_DIR', str(write(tmp_path)))
    r = rag.candidates(['EQ_A'])
    assert [c['hazard_code'] for c in r['candidates']] == ['cut', 'burn']   # A등급 먼저, CASE만 있는 electric 제외
    burn = r['candidates'][1]
    assert [m['text'] for m in burn['measures']] == ['기기명 대책']        # 관련도 4등급 대책 제외
    assert not any(s.startswith('CASE-') for c in r['candidates'] for s in c['source_ids'])


def test_multi_equipment_merges_best_tier_and_sources(tmp_path, monkeypatch):
    monkeypatch.setenv('SAFET_RAG_DIR', str(write(tmp_path)))
    r = rag.candidates(['EQ_A', 'EQ_B'], k=1)
    assert r['candidates'][0]['hazard_code'] == 'burn' and r['candidates'][0]['tier'] == 'A'
    assert r['candidates'][0]['n_sources'] == 4 and r['candidates'][0]['equipment_ids'] == ['EQ_A', 'EQ_B']


def test_unknown_and_no_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('SAFET_RAG_DIR', str(write(tmp_path)))
    assert rag.candidates(['EQ_NONE']) ['no_evidence'] == ['EQ_NONE']
    with pytest.raises(AuthError) as e:
        rag.candidates(['EQ_ZZZ'])
    assert e.value.status == 422 and e.value.extra['unknown'] == ['EQ_ZZZ']


def test_hash_mismatch_refused(tmp_path, monkeypatch):
    monkeypatch.setenv('SAFET_RAG_DIR', str(write(tmp_path, tamper=True)))
    with pytest.raises(AuthError) as e:
        rag.candidates(['EQ_A'])
    assert e.value.code == 'RAG_DATA_INVALID'
