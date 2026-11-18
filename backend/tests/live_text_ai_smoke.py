"""명시 실행 전용: 합성 텍스트를 실제 EXAONE에 보내고 격리 DB에서 검증한다."""
import os
import pytest
from test_assessment import flow, create, edits
from test_catalog_flow import catalog_flow

if os.getenv('SAFET_RUN_LIVE_TEXT_TEST') != '1':
    pytest.skip('실제 모델 호출은 명시 실행만 허용합니다.', allow_module_level=True)
if not os.getenv('DB_NAME', '').endswith('_test'):
    raise RuntimeError('격리 테스트 DB가 필요합니다.')
if not os.getenv('SAFET_AI_API_KEY'):
    raise RuntimeError('서버 환경변수에 API 키가 필요합니다.')

@pytest.mark.parametrize('needs_question', [False, True])
def test_live_text_draft_roundtrip(client, catalog_flow, monkeypatch, needs_question):
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE', 'catalog_ai_v1')
    auth, payload = catalog_flow
    payload['text'] = ('합성 시험 현장입니다. 튀김기를 보유하고 있습니다. 실제 사용 여부는 아직 확인하지 않았습니다.'
                       if needs_question else
                       '합성 시험 현장입니다. 음식점에서 직원이 매일 튀김기로 감자튀김을 조리하고 뜨거운 기름을 다룹니다.')
    payload.pop('photos', None)
    doc = create(client, catalog_flow)
    url = f"/evals/{doc['eval_no']}"
    assert doc['generation_source'] == 'catalog_ai_v1'
    assert [it['catalog']['scenario']['id'] for it in doc['items']] == ['FRY']
    item = doc['items'][0]
    analysis = item['catalog']['ai_analysis']
    assert analysis['model'] == os.environ['SAFET_AI_MODEL']
    assert item['signal'] == 'N'
    assert not any(a['checked'] for a in item['curr'] + item['plans'])
    assert item['curr'] and item['plans']
    questions = analysis['questions']
    if needs_question:
        assert questions, '사용 여부가 불명확하면 질문이 필요합니다.'
    if questions:
        assert client.post(url + '/confirm', headers=auth, json=edits(doc)).status_code == 422
        body = {'revision': doc['revision'], 'answers': [
            {'item_id': item['id'], 'question_id': q['id'],
             'answer': '합성 현장을 확인했습니다. 직원이 매일 주방에서 튀김기로 감자튀김을 조리하고 뜨거운 기름을 직접 다룹니다. 현재 안전 조치는 아직 없습니다.'}
            for q in questions]}
        response = client.post(url + '/risk-answers', headers=auth, json=body)
        assert response.status_code == 200, response.text
        doc = response.json()
        assert not doc['items'][0]['catalog']['ai_analysis']['questions']
    body = edits(doc)
    body['items'][0].update(none=True, controls_reviewed=True)
    response = client.put(url, headers=auth, json=body)
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc['items'][0]['signal'] == 'R' and doc['items'][0]['after'] == 'N'
    body = edits(doc)
    for action in body['items'][0]['plans']:
        action['checked'] = True
    body['items'][0].update(owner={'type': 'R', 'name': '근로자'}, due='2026-12-01')
    response = client.put(url, headers=auth, json=body)
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc['items'][0]['signal'] == 'R' and doc['items'][0]['after'] == 'Y'
    assert doc['items'][0]['catalog']['projected_result']['kind'] == 'projected'
    response = client.post(url + '/confirm', headers=auth, json=edits(doc))
    assert response.status_code == 200, response.text
    reloaded = client.get(url, headers=auth).json()
    assert reloaded['eval_status'] == 'C'
    assert reloaded['items'][0]['signal'] == 'R' and reloaded['items'][0]['after'] == 'Y'
