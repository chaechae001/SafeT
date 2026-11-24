"""연결 파일 무결성·입력 범위 검사. 합성 자료만 사용한다."""
import hashlib
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services import authoring_rag as adapter
from services.auth import AuthError


def test_owned_equipment_is_not_observed_work():
    context={'text':'칼로 채소를 자릅니다.','machines':[{'machine_nm':'튀김기'}]}
    assert adapter.build_context(context)['equipment_ids']==[]
    assert adapter.build_context({'text':'튀김기는 사용하지 않습니다.'})['equipment_ids']==[]


def test_invalid_photo_is_rejected():
    with pytest.raises(AuthError) as error: adapter.build_context({'text':'튀김기','photos':[{}]})
    assert error.value.code=='AI_IMAGE_INVALID'


def test_photo_description_is_not_offered_as_model_evidence():
    from ai.assessment_authoring.live_text_check import input_segments

    bundle = {'media': [
        {'id': 'TEXT', 'kind': 'text', 'text': '튀김은 하지 않습니다.'},
        {'id': 'PHOTO1', 'kind': 'equipment_detection', 'text': '튀김기 후보 0.91.'},
    ]}
    assert input_segments(bundle) == {'S1': ('TEXT', '튀김은 하지 않습니다.')}


@pytest.mark.parametrize('prefix', [
    pytest.param('{"candidates":[', id='candidate-list-not-started'),
    pytest.param('{"candidates":[{"scenario_id":"FRY","work_ref":"S1"', id='required-controls-missing'),
    pytest.param(
        '{"candidates":[{"scenario_id":"FRY","work_ref":"S1","controls":['
        '{"control_id":"FRY-C1","state":"supported","input_ref":"S2"},'
        '{"control_id":"FRY-C1","state":"supported","input_ref":"S2"}]}]',
        id='repaired-response-fails-contract',
    ),
])
def test_extract_retries_invalid_length_response(monkeypatch, prefix):
    from ai.assessment_authoring.contracts import load_catalog

    context = {'media': [{'id': 'TEXT', 'kind': 'text',
                          'text': '튀김기로 조리합니다. 온도제어 장치가 작동합니다.'}]}
    retrieval = {'candidates': [{'scenario_id': 'FRY'}]}
    sent = []

    def request(_base, _key, path, payload):
        if path == '/tokenize':
            return {'count': 1000}
        sent.append(payload)
        if len(sent) == 1:
            reason, content = 'length', prefix + '\n  ' * 70
        else:
            reason, content = 'stop', '{"candidates":[{"scenario_id":"FRY","work_ref":"S1","controls":[]}]}'
        return {'choices': [{'finish_reason': reason, 'message': {'content': content}}]}

    monkeypatch.setattr(adapter.catalog_ai, 'gateway_url', lambda: 'http://mock.invalid')
    monkeypatch.setattr(adapter.catalog_ai, 'configuration', lambda: (None, 'mock', None))
    monkeypatch.setattr(adapter.catalog_ai, 'model_headers', lambda: {})
    monkeypatch.setattr(adapter, 'request_json', request)

    result = adapter.extract(context, retrieval, load_catalog(), {})

    assert [row['scenario_id'] for row in result['candidates']] == ['FRY']
    assert len(sent) == 2
    assert 'frequency_penalty' not in sent[0]
    assert sent[1] == dict(sent[0], frequency_penalty=0.5)


def test_authoring_search_has_no_lookup_equipment_limit(monkeypatch):
    seen={}
    def candidates(ids,k=None,max_equipment=10):
        seen.update(ids=ids,max_equipment=max_equipment)
        raise AuthError(503,'STOP','stop')
    monkeypatch.setattr(adapter.rag_retrieval,'candidates',candidates)
    ids=[f'EQ_{i:02d}' for i in range(16)]  # 사진 6장에서 탐지될 수 있는 규모
    with pytest.raises(AuthError) as error: adapter.qualified_candidates(ids)
    assert error.value.code=='STOP' and seen==dict(ids=ids,max_equipment=None)


@pytest.mark.parametrize('bad',['hash','evaluation_only'])
def test_link_integrity_and_retrieval_role_required(tmp_path,monkeypatch,bad):
    monkeypatch.setattr(adapter.rag_retrieval,'candidates',lambda *a,**kw:{'candidates':[]})
    monkeypatch.setenv('SAFET_RAG_DIR',str(tmp_path))
    raw=b'{}\n';(tmp_path/adapter.LINK_FILE).write_bytes(raw)
    manifest={'roles':{'retrieval':[adapter.LINK_FILE] if bad!='evaluation_only' else []},
              'files':[{'file':adapter.LINK_FILE,'sha256':'wrong' if bad=='hash' else hashlib.sha256(raw).hexdigest()}]}
    (tmp_path/'MANIFEST.json').write_text(json.dumps(manifest),encoding='utf-8')
    with pytest.raises(AuthError) as error: adapter.qualified_candidates(['EQ_FRYER'])
    assert error.value.code=='RAG_LINKS_INVALID'
