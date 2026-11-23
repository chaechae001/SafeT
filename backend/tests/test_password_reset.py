"""비밀번호 재설정 API 테스트

실행 (backend 폴더에서): .venv\\Scripts\\python -m pytest -q
"""
import bcrypt

from conftest import db_exec, db_one

OLD, NEW = "Old-password1", "New-password2"


def make_user(email):
    """가입한 지 1시간 된 사용자 (회원가입처럼 ins_dt·upt_dt 기록)"""
    db_exec("INSERT INTO `user` (email, pw, name, ins_dt, upt_dt) VALUES (:e, :p, '테스트', NOW() - INTERVAL 1 HOUR, NOW() - INTERVAL 1 HOUR)",
            e=email, p=bcrypt.hashpw(OLD.encode(), bcrypt.gensalt()).decode())


def req(client, email):
    return client.post("/auth/password/code", json={"email": email})


def verify(client, email, code):
    return client.post("/auth/password/code/verify", json={"email": email, "code": code})


def reset(client, email, pw=NEW, token="no-token"):
    return client.post("/auth/password/reset", json={"email": email, "password": pw, "verify_token": token})


def login(client, email, pw):
    return client.post("/auth/login", json={"email": email, "password": pw})


def verified_token(client, mailer, email):
    req(client, email)
    r = verify(client, email, mailer.last_code(email))
    assert r.status_code == 200, r.text
    return r.json()["verify_token"]


def test_가입한_이메일_재설정_전체흐름(client, mailer, email):
    make_user(email)
    r = req(client, email)
    assert r.status_code == 200 and r.json() == {"expires_in": 300, "resend_after": 60}
    v = verify(client, email, mailer.last_code(email))
    assert v.status_code == 200 and v.json()["verify_token"]
    assert reset(client, email, token=v.json()["verify_token"]).status_code == 200
    assert login(client, email, NEW).status_code == 200
    assert login(client, email, OLD).status_code == 401
    assert bcrypt.checkpw(NEW.encode(), db_one("SELECT pw FROM `user` WHERE email=:e", e=email)["pw"].encode())


def test_다른사람이_인증완료를_가로채_재설정_못함(client, mailer, email):
    """주인이 재설정 코드를 확인한 뒤, 이메일만 아는 다른 사람이 자기 비밀번호로 재설정 시도 (계정 탈취 시도)"""
    make_user(email)
    token = verified_token(client, mailer, email)
    r = reset(client, email, pw="Attacker-pass1", token="guessed-token")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_VERIFY_TOKEN"
    assert login(client, email, "Attacker-pass1").status_code == 401
    assert login(client, email, OLD).status_code == 200                  # 비밀번호 그대로
    assert reset(client, email, token=token).status_code == 200           # 주인은 그대로 진행
    assert login(client, email, NEW).status_code == 200


def test_토큰없이는_재설정_불가(client, mailer, email):
    make_user(email)
    verified_token(client, mailer, email)
    r = client.post("/auth/password/reset", json={"email": email, "password": NEW})
    assert r.status_code == 422


def test_인증된_뒤엔_틀린코드로_성공_안함(client, mailer, email):
    make_user(email)
    req(client, email)
    code = mailer.last_code(email)
    assert verify(client, email, code).status_code == 200
    wrong = f"{(int(code) + 1) % 10 ** 6:06d}"
    for c in (wrong, code):
        r = verify(client, email, c)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "CODE_ALREADY_USED"


def test_가입_안한_이메일도_같은_응답_메일_기록_없음(client, mailer, email):
    r = req(client, email)
    assert r.status_code == 200 and r.json() == {"expires_in": 300, "resend_after": 60}
    assert mailer.sent == []
    assert db_one("SELECT COUNT(*) n FROM email_verifications WHERE email=:e", e=email)["n"] == 0
    r = verify(client, email, "123456")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "CODE_MISMATCH"     # '요청 안 함'과 구분 안 함
    assert reset(client, email).status_code == 400


def test_회원가입_인증기록으로는_재설정_불가(client, mailer, email):
    client.post("/auth/signup/code", json={"email": email})
    t = client.post("/auth/signup/code/verify", json={"email": email, "code": mailer.last_code(email)}).json()["verify_token"]
    assert client.post("/auth/signup", json={"email": email, "password": OLD, "name": "새 사용자", "verify_token": t}).status_code == 201
    for token in ("no-token", t):                                    # 가입 때 받은 토큰으로도 불가
        r = reset(client, email, token=token)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "NOT_VERIFIED"
    assert login(client, email, OLD).status_code == 200


def test_재설정_토큰은_한번만(client, mailer, email):
    make_user(email)
    token = verified_token(client, mailer, email)
    assert reset(client, email, token=token).status_code == 200
    r = reset(client, email, pw="Another-pass3", token=token)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "NOT_VERIFIED"
    assert login(client, email, NEW).status_code == 200


def test_재설정하면_기존_로그인_끝남(client, mailer, email):
    make_user(email)
    token = login(client, email, OLD).json()["access_token"]
    me = lambda t: client.get("/auth/me", headers={"Authorization": f"Bearer {t}"})
    assert me(token).status_code == 200
    reset(client, email, token=verified_token(client, mailer, email))
    r = me(token)
    assert r.status_code == 401 and "비밀번호가 바뀌어" in r.json()["detail"]["message"]
    new_token = login(client, email, NEW).json()["access_token"]
    assert me(new_token).status_code == 200


def test_틀린코드_횟수와_잠김(client, mailer, email):
    make_user(email)
    req(client, email)
    code = mailer.last_code(email)
    wrong = f"{(int(code) + 1) % 10 ** 6:06d}"
    for i in range(1, 5):
        assert verify(client, email, wrong).json()["detail"]["tries"] == i
    assert verify(client, email, wrong).status_code == 429
    assert verify(client, email, code).status_code == 429


def test_60초안_재요청_만료_30분(client, mailer, email):
    make_user(email)
    assert req(client, email).status_code == 200
    assert req(client, email).status_code == 429
    db_exec("UPDATE email_verifications SET expiration_dt = expiration_dt - INTERVAL 10 MINUTE WHERE email=:e", e=email)
    assert verify(client, email, mailer.last_code(email)).json()["detail"]["code"] == "CODE_EXPIRED"
    db_exec("UPDATE email_verifications SET send_dt = send_dt - INTERVAL 61 SECOND WHERE email=:e", e=email)
    token = verified_token(client, mailer, email)
    db_exec("UPDATE email_verifications SET auth_dt = auth_dt - INTERVAL 31 MINUTE WHERE email=:e AND auth_dt IS NOT NULL", e=email)
    assert reset(client, email, token=token).json()["detail"]["code"] == "VERIFY_EXPIRED"


def test_새_비밀번호_형식(client, email):
    assert reset(client, email, "short").status_code == 422
    assert reset(client, email, "가" * 30).status_code == 422


def test_메일_발송실패(client, mailer, email):
    make_user(email)
    mailer.fail = OSError("smtp down")
    assert req(client, email).status_code == 502
    assert db_one("SELECT COUNT(*) n FROM email_verifications WHERE email=:e", e=email)["n"] == 0


def test_reset_preserves_withdrawal_committed_after_user_lookup(client, mailer, email, monkeypatch):
    from services import auth

    make_user(email)
    token = verified_token(client, mailer, email)
    lookup = auth._reset_user

    def lookup_before_withdrawal(db, address):
        previous = lookup(db, address)
        # 별도 트랜잭션이 저장한 탈퇴 표식을 오래된 조회 결과로 덮지 않아야 한다.
        db_exec("UPDATE `user` SET pw=:marker WHERE email=:e", marker=auth.WITHDRAWN, e=email)
        return previous

    monkeypatch.setattr(auth, "_reset_user", lookup_before_withdrawal)
    response = reset(client, email, token=token)
    assert response.status_code == 400
    assert db_one("SELECT pw FROM `user` WHERE email=:e", e=email)["pw"] == auth.WITHDRAWN
    assert login(client, email, NEW).status_code == 401
