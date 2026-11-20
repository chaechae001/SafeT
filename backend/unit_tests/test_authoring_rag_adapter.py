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
