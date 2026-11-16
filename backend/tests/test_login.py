"""로그인 API 테스트 (A01 · JWT)

실행 (backend 폴더에서): .venv\\Scripts\\python -m pytest -q
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from conftest import db_exec

PW = "password123"


def make_user(email, pw=PW, name="김하늘"):
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    db_exec("INSERT INTO `user` (email, pw, name) VALUES (:e, :p, :n)", e=email, p=h, n=name)


def login(client, email, pw=PW):
    return client.post("/auth/login", json={"email": email, "password": pw})


def me(client, token):
    return client.get("/auth/me", headers={"Authorization": f"Bearer {token}"} if token else {})


def test_로그인_성공_토큰과_사업장없음(client, email):
    make_user(email)
    r = login(client, email)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == email and body["name"] == "김하늘"
    assert body["has_workplace"] is False                 # → 화면은 새 사업장 등록으로
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    assert body["access_token"].count(".") == 2


def test_사업장_있으면_has_workplace_참(client, email, biz_code):
    make_user(email)
    db_exec("INSERT INTO workplaces (email, workplace, biz_code, use_yn) VALUES (:e, '테스트 매장', :b, 'Y')", e=email, b=biz_code)
    assert login(client, email).json()["has_workplace"] is True   # → 화면은 내 평가표로


def test_삭제한_사업장만_있으면_없음으로(client, email, biz_code):
    make_user(email)
    db_exec("INSERT INTO workplaces (email, workplace, biz_code, use_yn) VALUES (:e, '삭제한 매장', :b, 'N')", e=email, b=biz_code)
    assert login(client, email).json()["has_workplace"] is False


def test_비밀번호_틀림과_없는_이메일은_같은_안내(client, email):
    make_user(email)
    a = login(client, email, "wrong-password")
    b = login(client, "nobody-" + email)
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]
    assert a.json()["detail"]["code"] == "LOGIN_FAILED"
    assert a.headers["WWW-Authenticate"] == "Bearer"


def test_이메일_대소문자_무시(client, email):
    make_user(email)
    assert login(client, "  " + email.upper()).status_code == 200


def test_입력형식(client):
    assert login(client, "not-email").status_code == 422
    assert login(client, "a@b.co", "").status_code == 422


def test_me_토큰으로_사용자확인(client, email):
    make_user(email)
    token = login(client, email).json()["access_token"]
    r = me(client, token)
    assert r.status_code == 200
    assert r.json() == {"email": email, "name": "김하늘", "has_workplace": False}


def test_me_토큰없음_잘못됨_만료(client, email, monkeypatch):
    make_user(email)
    assert me(client, None).json()["detail"]["code"] == "LOGIN_REQUIRED"
    assert me(client, "abc.def.ghi").status_code == 401
    import os
    secret = os.environ["JWT_SECRET"]
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = jwt.encode({"sub": email, "iat": past - timedelta(hours=8), "exp": past}, secret, algorithm="HS256")
    r = me(client, expired)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "TOKEN_EXPIRED"
    forged = jwt.encode({"sub": email, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "x" * 40, algorithm="HS256")
    assert me(client, forged).status_code == 401              # 다른 키로 서명한 토큰


def test_비밀키_없으면_503(client, email, monkeypatch):
    make_user(email)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    r = login(client, email)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "AUTH_NOT_CONFIGURED"


def test_가입후_바로_로그인(client, mailer, email):
    client.post("/auth/signup/code", json={"email": email})
    client.post("/auth/signup/code/verify", json={"email": email, "code": mailer.last_code(email)})
    assert client.post("/auth/signup", json={"email": email, "password": PW, "name": "새 사용자"}).status_code == 201
    r = login(client, email)
    assert r.status_code == 200 and r.json()["name"] == "새 사용자"


def test_CORS_Authorization_헤더_허용(client):
    r = client.options("/auth/me", headers={
        "Origin": "http://localhost:8000",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    })
    assert r.status_code == 200
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
