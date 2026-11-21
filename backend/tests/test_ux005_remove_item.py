"""UX-005 (2026-11-21) 위험 항목 1개 삭제 API: POST /evals/{번호}/items/{항목}/delete

실행 (backend 폴더, _test DB): .venv\\Scripts\\python -m pytest tests/test_ux005_remove_item.py -q
test_assessment.py 의 flow 픽스처(작성자·사업장·생성 payload)를 그대로 쓴다.
"""
import uuid

from conftest import db_one
from test_assessment import flow  # noqa: F401  (픽스처)


def make(client, flow, text):
    h, p = flow
    p = dict(p, request_key=str(uuid.uuid4()), text=text)
    r = client.post('/evals', headers=h, json=p)
    assert r.status_code == 201, r.text
    return h, r.json()


def test_항목_삭제_성공_다른_항목_유지(client, flow):
    h, d = make(client, flow, '튀김기 앞 바닥에 물기가 있어요. 칼로 채소를 손질하고 무거운 식자재 박스를 옮겨요.')
    if len(d['items']) < 2:
        h, d = make(client, flow, '튀김 조리를 하고 바닥 청소를 해요. 가스레인지를 쓰고 칼로 손질해요.')
    assert len(d['items']) >= 2, '시험용 평가표에 항목이 2개 이상 필요'
    target, rest = d['items'][0]['id'], [it['id'] for it in d['items'][1:]]
    r = client.post(f"/evals/{d['eval_no']}/items/{target}/delete", headers=h, json={'revision': d['revision']})
    assert r.status_code == 200, r.text
    after = r.json()
    assert [it['id'] for it in after['items']] == rest
    assert after['revision'] == d['revision'] + 1
    assert db_one('SELECT COUNT(*) n FROM eval_action WHERE eval_dtl_no=:d', d=target)['n'] == 0


def test_항목_삭제_오래된_revision_409(client, flow):
    h, d = make(client, flow, '튀김기 앞 바닥에 물기가 있어요.')
    r = client.post(f"/evals/{d['eval_no']}/items/{d['items'][0]['id']}/delete", headers=h, json={'revision': d['revision'] + 5})
    assert r.status_code == 409 and r.json()['detail']['code'] == 'STALE_REVISION'


def test_다른_평가표_항목은_404(client, flow):
    h, d = make(client, flow, '튀김기 앞 바닥에 물기가 있어요.')
    r = client.post(f"/evals/{d['eval_no']}/items/999999999/delete", headers=h, json={'revision': d['revision']})
    assert r.status_code == 404 and r.json()['detail']['code'] == 'ITEM_NOT_FOUND'


def test_로그인_없으면_401(client, flow):
    h, d = make(client, flow, '튀김기 앞 바닥에 물기가 있어요.')
    r = client.post(f"/evals/{d['eval_no']}/items/{d['items'][0]['id']}/delete", json={'revision': d['revision']})
    assert r.status_code == 401
