"""회원가입 API 테스트 (A02)

실행 (backend 폴더에서): .venv\\Scripts\\python -m pytest -q
"""
import bcrypt

from conftest import db_exec, db_one


def request_code(client, email):
    return client.post("/auth/signup/code", json={"email": email})


def verify(client, email, code):
    return client.post("/auth/signup/code/verify", json={"email": email, "code": code})


def signup(client, email, password="password123", name="김하늘", token="no-token"):
    return client.post("/auth/signup", json={"email": email, "password": password, "name": name, "verify_token": token})


def verified_token(client, mailer, email):
    """인증 요청 → 코드 확인 → 일회용 인증 토큰"""
    request_code(client, email)
    r = verify(client, email, mailer.last_code(email))
    assert r.status_code == 200, r.text
    return r.json()["verify_token"]


def wrong(code):
    return f"{(int(code) + 1) % 10 ** 6:06d}"


# ---------- 인증 요청 ----------
def test_인증요청_메일발송과_해시저장(client, mailer, email):
    r = request_code(client, email)
    assert r.status_code == 200, r.text
    assert r.json() == {"expires_in": 300, "resend_after": 60}
    code = mailer.last_code(email)
    assert len(code) == 6 and code.isdigit()
    row = db_one("SELECT auth_code, try_count, expiration_dt, send_dt FROM email_verifications WHERE email=:e", e=email)
    assert row["auth_code"] != code and len(row["auth_code"]) == 64      # 코드 원문 저장 안 함
    assert row["try_count"] == 0
    assert (row["expiration_dt"] - row["send_dt"]).total_seconds() == 300


def test_이메일_대소문자_공백_정리(client, mailer, email):
    r = request_code(client, "  " + email.upper() + " ")
    assert r.status_code == 200
    assert mailer.sent[-1][0] == email


def test_60초_안에_재요청_막힘(client, mailer, email):
    assert request_code(client, email).status_code == 200
    r = request_code(client, email)
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "RESEND_TOO_SOON"
    assert int(r.headers["Retry-After"]) > 0


def test_60초_지나면_재요청_가능_새코드로만_인증(client, mailer, email):
    request_code(client, email)
    first = mailer.last_code(email)
    db_exec("UPDATE email_verifications SET send_dt = send_dt - INTERVAL 61 SECOND WHERE email=:e", e=email)
    assert request_code(client, email).status_code == 200
    second = mailer.last_code(email)
    if first != second:
        assert verify(client, email, first).status_code == 400      # 이전 코드는 무효
    assert verify(client, email, second).status_code == 200


def test_이미_가입한_이메일은_인증요청에서_안내(client, mailer, email):
    db_exec("INSERT INTO `user` (email, pw, name) VALUES (:e, 'x', '테스트')", e=email)
    r = request_code(client, email)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EMAIL_EXISTS"
    assert mailer.sent == []


def test_메일_설정없음_503_저장안함(client, monkeypatch, email):
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    r = request_code(client, email)      # 실제 발송 함수 사용
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "MAIL_NOT_CONFIGURED"
    assert db_one("SELECT COUNT(*) n FROM email_verifications WHERE email=:e", e=email)["n"] == 0


def test_메일_발송실패_502_저장안함(client, mailer, email):
    mailer.fail = OSError("smtp down")
    r = request_code(client, email)
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "MAIL_FAILED"
    assert db_one("SELECT COUNT(*) n FROM email_verifications WHERE email=:e", e=email)["n"] == 0


# ---------- 인증 코드 확인 ----------
def test_인증요청_없이_확인(client, email):
    r = verify(client, email, "123456")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "CODE_NOT_REQUESTED"


def test_틀린코드_횟수증가_5번이면_잠김(client, mailer, email):
    request_code(client, email)
    code = mailer.last_code(email)
    for i in range(1, 5):
        r = verify(client, email, wrong(code))
        assert r.status_code == 400 and r.json()["detail"]["tries"] == i
    r = verify(client, email, wrong(code))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "TOO_MANY_TRIES"
    r = verify(client, email, code)                 # 잠긴 뒤에는 맞는 코드도 거부
    assert r.status_code == 429


def test_만료된_코드(client, mailer, email):
    request_code(client, email)
    db_exec("UPDATE email_verifications SET expiration_dt = expiration_dt - INTERVAL 10 MINUTE WHERE email=:e", e=email)
    r = verify(client, email, mailer.last_code(email))
    assert r.status_code == 400 and r.json()["detail"]["code"] == "CODE_EXPIRED"


def test_맞는코드_인증완료_일회용토큰(client, mailer, email):
    request_code(client, email)
    r = verify(client, email, mailer.last_code(email))
    assert r.status_code == 200 and r.json()["verified"] is True
    token = r.json()["verify_token"]
    assert len(token) >= 40
    row = db_one("SELECT auth_dt, auth_code FROM email_verifications WHERE email=:e", e=email)
    assert row["auth_dt"] is not None
    assert row["auth_code"].startswith("vt:") and token not in row["auth_code"]     # 토큰 원문은 저장 안 함


def test_인증된_뒤엔_틀린코드도_맞는코드도_성공_안함(client, mailer, email):
    request_code(client, email)
    code = mailer.last_code(email)
    assert verify(client, email, code).status_code == 200
    for c in (wrong(code), code):
        r = verify(client, email, c)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "CODE_ALREADY_USED"
        assert "verify_token" not in r.json()


# ---------- 가입하기 ----------
def test_인증없이_가입_막힘(client, email):
    r = signup(client, email)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "NOT_VERIFIED"
    assert client.post("/auth/signup", json={"email": email, "password": "password123", "name": "x"}).status_code == 422


def test_다른사람이_인증완료를_가로채_가입_못함(client, mailer, email):
    """이메일 주인이 코드를 확인한 뒤, 가입하기 전에 다른 사람이 같은 이메일로 가입 시도"""
    token = verified_token(client, mailer, email)
    r = signup(client, email, password="attacker-pass", name="다른 사람", token="guessed-token")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_VERIFY_TOKEN"
    assert db_one("SELECT COUNT(*) n FROM `user` WHERE email=:e", e=email)["n"] == 0
    r = signup(client, email, password="owner-pass1", name="주인", token=token)       # 주인은 그대로 가입
    assert r.status_code == 201
    assert client.post("/auth/login", json={"email": email, "password": "owner-pass1"}).status_code == 200


def test_인증토큰은_한번만(client, mailer, email):
    token = verified_token(client, mailer, email)
    assert signup(client, email, token=token).status_code == 201
    db_exec("DELETE FROM `user` WHERE email=:e", e=email)              # 계정이 없어져도
    r = signup(client, email, token=token)                             # 같은 토큰 재사용 불가
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_VERIFY_TOKEN"


def test_가입_전체흐름_비밀번호_bcrypt(client, mailer, email):
    token = verified_token(client, mailer, email)
    r = signup(client, email, password="safe-t-pass!", name="  김 하늘 ", token=token)
    assert r.status_code == 201, r.text
    assert r.json() == {"email": email, "name": "김 하늘"}
    row = db_one("SELECT pw, name, auth_dt, ins_dt FROM `user` WHERE email=:e", e=email)
    assert row["pw"] != "safe-t-pass!" and row["pw"].startswith("$2b$")
    assert bcrypt.checkpw(b"safe-t-pass!", row["pw"].encode())
    assert row["auth_dt"] is not None and row["ins_dt"] is not None

    r = signup(client, email)                       # 같은 이메일 다시 가입
    assert r.status_code == 409


def test_인증후_30분_지나면_가입_막힘(client, mailer, email):
    token = verified_token(client, mailer, email)
    db_exec("UPDATE email_verifications SET auth_dt = auth_dt - INTERVAL 31 MINUTE WHERE email=:e", e=email)
    r = signup(client, email, token=token)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "VERIFY_EXPIRED"


# ---------- 입력 형식 ----------
def test_입력형식_검사(client, email):
    assert request_code(client, "not-an-email").status_code == 422
    assert request_code(client, "a" * 45 + "@x.com").status_code == 422          # 50자 초과
    assert verify(client, email, "12ab56").status_code == 422
    assert signup(client, email, password="short").status_code == 422             # 8자 미만
    assert signup(client, email, password="가" * 30).status_code == 422             # 72바이트 초과
    assert signup(client, email, name="   ").status_code == 422


def test_화면주소에서_API_호출_허용(client):
    r = client.options("/auth/signup/code", headers={
        "Origin": "http://localhost:8000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:8000"


def test_허용하지_않은_주소는_막힘(client):
    r = client.options("/auth/signup/code", headers={
        "Origin": "http://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in r.headers


def test_DB_상태확인(client):
    r = client.get("/health/db")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.json()["table_count"] >= 19
