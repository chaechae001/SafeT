"""UX-001 (2026-11-21) 인증 보완 테스트: 비밀번호 규칙 · 게스트 로그인 · 개발용 메일 보관함

실행 (backend 폴더에서, _test DB): .venv\\Scripts\\python -m pytest tests/test_ux001_auth.py -q
"""
import json
from datetime import timedelta

import pytest

from conftest import db_one
from schemas.auth import password_rule_ok
from services import mailer

GUEST_KEY = "k" * 20 + "UX001-guest-key-for-tests"


# ---------- 비밀번호 규칙 (회원가입·재설정 공통) ----------
@pytest.mark.parametrize("pw,ok", [
    ("Abcdef1!", True),
    ("abcdef1!", False),      # 대문자 없음
    ("ABCDEF1!", False),      # 소문자 없음
    ("Abcdefg!", False),      # 숫자 없음
    ("Abcdefg1", False),      # 특수문자 없음
    ("Abc1!", False),         # 8자 미만
    ("Ab1! cdef", True),      # 공백 포함 허용, 특수문자는 ! 로 충족
])
def test_비밀번호_규칙(pw, ok):
    assert password_rule_ok(pw) is ok


def test_가입_약한비밀번호_422(client, email):
    r = client.post("/auth/signup", json={"email": email, "password": "password123", "name": "x", "verify_token": "t"})
    assert r.status_code == 422
    assert "대문자" in json.dumps(r.json(), ensure_ascii=False)


def test_재설정_약한비밀번호_422(client, email):
    r = client.post("/auth/password/reset", json={"email": email, "password": "Password123", "verify_token": "t"})
    assert r.status_code == 422


def test_기존_약한비밀번호_계정도_로그인은_가능(client, email):
    import bcrypt
    from conftest import db_exec
    db_exec("INSERT INTO `user` (email, pw, name) VALUES (:e, :p, '기존')", e=email,
            p=bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode())
    assert client.post("/auth/login", json={"email": email, "password": "password123"}).status_code == 200


# ---------- 게스트 로그인 ----------
@pytest.fixture
def guest(monkeypatch, email):
    monkeypatch.setenv("SAFET_GUEST_KEY", GUEST_KEY)
    monkeypatch.setenv("SAFET_GUEST_EMAIL", email)      # 테스트 이메일 → 끝나면 삭제
    return email


def test_게스트_키없으면_꺼짐(client, monkeypatch):
    monkeypatch.delenv("SAFET_GUEST_KEY", raising=False)
    r = client.post("/auth/guest", json={"key": GUEST_KEY})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "GUEST_DISABLED"


def test_게스트_틀린키_401(client, guest):
    r = client.post("/auth/guest", json={"key": GUEST_KEY + "x"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "GUEST_KEY_INVALID"
    assert db_one("SELECT email FROM `user` WHERE email=:e", e=guest) is None


def test_게스트_로그인_계정생성_토큰(client, guest):
    r = client.post("/auth/guest", json={"key": GUEST_KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == guest and body["has_workplace"] is False and body["access_token"]
    me = client.get("/auth/me", headers={"Authorization": "Bearer " + body["access_token"]})
    assert me.status_code == 200 and me.json()["email"] == guest
    # 두 번째도 같은 계정 (중복 생성 없음)
    assert client.post("/auth/guest", json={"key": GUEST_KEY}).json()["email"] == guest


def test_게스트_계정은_비밀번호로_로그인_불가(client, guest):
    client.post("/auth/guest", json={"key": GUEST_KEY})
    for pw in ("", "guest", GUEST_KEY):
        r = client.post("/auth/login", json={"email": guest, "password": pw or "x"})
        assert r.status_code in (401, 422)


# ---------- 개발용 메일 보관함 ----------
def test_SMTP없고_보관함있으면_파일저장(tmp_path, monkeypatch):
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SAFET_DEV_MAIL_OUTBOX", str(tmp_path))
    mailer.send_code("a@test.invalid", "123456", timedelta(minutes=5), purpose="reset")
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    item = json.loads(files[0].read_text(encoding="utf-8"))
    assert item["code"] == "123456" and item["purpose"] == "reset" and item["to"] == "a@test.invalid"


def test_SMTP없고_보관함없으면_기존처럼_설정오류(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SAFET_DEV_MAIL_OUTBOX"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(mailer.MailConfigError):
        mailer.send_code("a@test.invalid", "123456", timedelta(minutes=5))


def test_보관함_화면_설정없으면_404(client, monkeypatch):
    monkeypatch.delenv("SAFET_DEV_MAIL_OUTBOX", raising=False)
    assert client.get("/dev/outbox").status_code == 404


def test_보관함_화면_외부요청_404(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    monkeypatch.setenv("SAFET_DEV_MAIL_OUTBOX", str(tmp_path))
    remote = TestClient(app, client=("203.0.113.5", 50000))
    assert remote.get("/dev/outbox").status_code == 404
    local = TestClient(app, client=("127.0.0.1", 50000))
    assert local.get("/dev/outbox").status_code == 200
