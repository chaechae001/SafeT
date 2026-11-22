"""UX-018: 회원 탈퇴(POST /auth/withdraw)와 내 평가표 목록의 확인 대기 수(pending_count).

탈퇴: 비밀번호 재확인 → 로그인 불가·이름 삭제·기존 토큰 종료·사업장 사용 중지, 평가 기록은 남김, 재설정으로 되살릴 수 없음.
DB 안전장치는 conftest.py(_test DB 또는 ALLOW_DB_TESTS=1).
"""
import json

from sqlalchemy import text

from conftest import engine
from test_assessment import flow  # noqa: F401
from test_workplaces import make_login


def test_withdraw_wrong_password_keeps_account(client, email):
    h = make_login(client, email)
    r = client.post('/auth/withdraw', headers=h, json={'password': 'wrong-pass'})
    assert r.status_code == 400 and r.json()['detail']['code'] == 'PASSWORD_MISMATCH', r.text
    assert client.get('/auth/me', headers=h).status_code == 200


def test_withdraw_blocks_login_and_keeps_records(client, flow):  # noqa: F811
    h, p = flow
    created = client.post('/evals', headers=h, json=p)
    assert created.status_code == 201, created.text
    no = created.json()['eval_no']
    email = client.get('/auth/me', headers=h).json()['email']

    r = client.post('/auth/withdraw', headers=h, json={'password': 'password123'})
    assert r.status_code == 200 and r.json()['withdrawn'] is True, r.text
    # 기존 로그인 종료, 다시 로그인 불가
    assert client.get('/auth/me', headers=h).status_code == 401
    assert client.post('/auth/login', json={'email': email, 'password': 'password123'}).status_code == 401
    with engine.begin() as c:
        user = c.execute(text('SELECT name, pw FROM `user` WHERE email=:e'), {'e': email}).mappings().one()
        wp = c.execute(text('SELECT COUNT(*) FROM workplaces WHERE email=:e AND COALESCE(use_yn,"Y")="Y"'), {'e': email}).scalar()
        kept = c.execute(text('SELECT COUNT(*) FROM eval_mst WHERE eval_no=:n'), {'n': no}).scalar()
    assert user['name'] == '탈퇴한 사용자' and not user['pw'].startswith('$2')
    assert wp == 0 and kept == 1
    # 비밀번호 재설정으로 되살릴 수 없음(가입되지 않은 이메일과 같은 응답, 메일 발송 없음)
    sent = client.post('/auth/password/code', json={'email': email})
    assert sent.status_code in (200, 202), sent.text
    with engine.begin() as c:
        codes = c.execute(text('SELECT COUNT(*) FROM email_verifications WHERE email=:e'), {'e': email}).scalar()
    assert codes == 0


def test_list_has_pending_count(client, flow):  # noqa: F811
    h, p = flow
    doc = client.post('/evals', headers=h, json=p).json()
    snap = json.dumps({'rls_pending': [{'job': 'a'}, {'job': 'b'}]}, ensure_ascii=False)
    with engine.begin() as c:
        c.execute(text('UPDATE eval_mst SET authoring_snapshot=:s WHERE eval_no=:n'), {'s': snap, 'n': doc['eval_no']})
    card = next(x for x in client.get('/evals?tab=W', headers=h).json()['items'] if x['eval_no'] == doc['eval_no'])
    assert card['pending_count'] == 2
    with engine.begin() as c:
        c.execute(text('UPDATE eval_mst SET authoring_snapshot=NULL WHERE eval_no=:n'), {'n': doc['eval_no']})
    card = next(x for x in client.get('/evals?tab=W', headers=h).json()['items'] if x['eval_no'] == doc['eval_no'])
    assert card['pending_count'] == 0
