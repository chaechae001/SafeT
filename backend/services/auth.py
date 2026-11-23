"""회원가입 업무 처리 (A02 · 화면설계서 07쪽)

규칙 (2026-11-16 결정)
- 인증 코드: 숫자 6자리, 5분 뒤 만료, 5번 틀리면 다시 요청, 재요청은 60초 뒤부터
- 이미 가입한 이메일은 인증 요청 단계에서 안내
- 비밀번호는 bcrypt 해시로 저장, 인증 코드는 SHA-256 해시로 저장(원문 저장 안 함)
- 인증을 마친 뒤 30분 안에 가입을 마쳐야 함

ORM 모델은 합의 전이라(models/README.md) 테이블은 SQL 로 직접 다룹니다.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable

import bcrypt
import jwt
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.mailer import MailConfigError

CODE_TTL = timedelta(minutes=5)
MAX_TRY = 5
RESEND_GAP = timedelta(seconds=60)
SIGNUP_WINDOW = timedelta(minutes=30)
KST = timezone(timedelta(hours=9))

SendCode = Callable[[str, str, timedelta], None]


class AuthError(Exception):
    """화면에 보여 줄 오류 (code: 화면 처리용, message: 사용자 안내 문구)"""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def now() -> datetime:
    """한국 시각 (DB datetime 컬럼에 맞춰 시간대 정보 없이)"""
    return datetime.now(KST).replace(tzinfo=None, microsecond=0)


def _hash_code(email: str, code: str) -> str:
    return hashlib.sha256(f"{email}:{code}".encode("utf-8")).hexdigest()


# ---------- 일회용 인증 토큰 (2026-11-16 보완) ----------
# 코드 확인에 성공한 사람에게만 무작위 토큰을 주고, 가입·비밀번호 재설정에는 그 토큰을 함께 받습니다.
# → 이메일만 아는 다른 사람이 '인증 완료' 상태를 가로채 가입·재설정할 수 없음
# 토큰 원문은 저장하지 않고, 확인을 마친 행의 auth_code 를 토큰 해시('vt:'+64자)로 바꿔 둡니다.
# 쓰고 나면 auth_code 를 'used' 로 바꿔 다시 쓸 수 없게 합니다.
TOKEN_PREFIX = "vt:"
TOKEN_USED = "used"


def _hash_token(email: str, token: str) -> str:
    return TOKEN_PREFIX + hashlib.sha256(f"verify:{email}:{token}".encode("utf-8")).hexdigest()


def _check_code_issue_token(db: Session, email: str, last, code: str) -> dict:
    """가장 최근 코드와 비교 → 맞으면 인증 완료 + 일회용 토큰 발급 (회원가입·재설정 공통)"""
    if last["auth_dt"]:
        # 이미 확인한 코드는 다시 성공시키지 않음 (틀린 코드로도 통과하던 문제 보완)
        raise AuthError(400, "CODE_ALREADY_USED", "이미 확인한 코드예요. 인증 코드를 다시 요청해 주세요.")
    if (last["try_count"] or 0) >= MAX_TRY:
        raise AuthError(429, "TOO_MANY_TRIES", f"{MAX_TRY}번 틀렸어요. 인증 코드를 다시 요청해 주세요.")
    if now() > last["expiration_dt"]:
        raise AuthError(400, "CODE_EXPIRED", "인증 코드가 만료됐어요. 다시 요청해 주세요.")

    if not hmac.compare_digest(last["auth_code"] or "", _hash_code(email, code)):
        tries = (last["try_count"] or 0) + 1
        db.execute(text("UPDATE email_verifications SET try_count = :n WHERE seq = :q"), {"n": tries, "q": last["seq"]})
        db.commit()
        if tries >= MAX_TRY:
            raise AuthError(429, "TOO_MANY_TRIES", f"{MAX_TRY}번 틀렸어요. 인증 코드를 다시 요청해 주세요.")
        raise AuthError(400, "CODE_MISMATCH", f"인증 코드가 맞지 않아요. ({tries}/{MAX_TRY})", tries=tries)

    token = secrets.token_urlsafe(32)
    db.execute(
        text("UPDATE email_verifications SET auth_dt = :t, auth_code = :h WHERE seq = :q"),
        {"t": now(), "h": _hash_token(email, token), "q": last["seq"]},
    )
    db.commit()
    return {"verified": True, "verify_token": token}


def _consume_token(db: Session, email: str, last, token: str) -> None:
    """인증 토큰 확인 후 '사용함'으로 바꿈. 커밋은 호출한 쪽에서 가입·재설정과 함께 합니다."""
    if not last or not last["auth_dt"]:
        raise AuthError(400, "NOT_VERIFIED", "이메일 인증을 먼저 해 주세요.")
    if now() - last["auth_dt"] > SIGNUP_WINDOW:
        raise AuthError(400, "VERIFY_EXPIRED", "인증한 지 30분이 지났어요. 인증 코드를 다시 요청해 주세요.")
    expected = _hash_token(email, token or "")
    if not hmac.compare_digest(last["auth_code"] or "", expected):
        raise AuthError(400, "INVALID_VERIFY_TOKEN", "인증 정보가 맞지 않아요. 인증 코드를 다시 요청해 주세요.")
    # 같은 토큰으로 동시에 두 번 요청해도 한 번만 성공 (조건부 UPDATE)
    res = db.execute(
        text("UPDATE email_verifications SET auth_code = :u WHERE seq = :q AND auth_code = :h"),
        {"u": TOKEN_USED, "q": last["seq"], "h": expected},
    )
    if res.rowcount != 1:
        db.rollback()
        raise AuthError(400, "INVALID_VERIFY_TOKEN", "인증 정보가 맞지 않아요. 인증 코드를 다시 요청해 주세요.")


def _user_exists(db: Session, email: str) -> bool:
    return db.execute(text("SELECT 1 FROM `user` WHERE email = :e"), {"e": email}).first() is not None


def _latest(db: Session, email: str):
    return db.execute(
        text(
            "SELECT seq, auth_code, expiration_dt, try_count, send_dt, auth_dt "
            "FROM email_verifications WHERE email = :e AND auth_code <> :guard ORDER BY seq DESC LIMIT 1"
        ),
        {"e": email, "guard": WITHDRAW_GUARD},
    ).mappings().first()


def request_code(db: Session, email: str, send: SendCode) -> dict:
    """인증 요청: 코드를 만들어 저장하고 메일로 보냅니다. 메일 발송에 실패하면 저장하지 않습니다."""
    if _user_exists(db, email):
        raise AuthError(409, "EMAIL_EXISTS", "이미 사용된 이메일이에요. 다른 이메일로 가입해 주세요.")

    t = now()
    last = _latest(db, email)
    if last and last["send_dt"] and t - last["send_dt"] < RESEND_GAP:
        wait = int((RESEND_GAP - (t - last["send_dt"])).total_seconds()) or 1
        raise AuthError(429, "RESEND_TOO_SOON", f"{wait}초 뒤에 다시 요청해 주세요.", retry_after=wait)

    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.execute(
        text(
            "INSERT INTO email_verifications (email, auth_code, expiration_dt, try_count, send_dt) "
            "VALUES (:e, :c, :x, 0, :s)"
        ),
        {"e": email, "c": _hash_code(email, code), "x": t + CODE_TTL, "s": t},
    )
    try:
        send(email, code, CODE_TTL)
    except MailConfigError:
        db.rollback()
        raise AuthError(503, "MAIL_NOT_CONFIGURED", "메일 발송 설정이 없어요. 관리자에게 문의해 주세요.")
    except Exception:
        db.rollback()
        raise AuthError(502, "MAIL_FAILED", "인증 메일을 보내지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    db.commit()
    return {"expires_in": int(CODE_TTL.total_seconds()), "resend_after": int(RESEND_GAP.total_seconds())}


def verify_code(db: Session, email: str, code: str) -> dict:
    """인증 코드 확인: 가장 최근에 보낸 코드와 비교 → 맞으면 일회용 인증 토큰 발급"""
    last = _latest(db, email)
    if not last:
        raise AuthError(400, "CODE_NOT_REQUESTED", "인증 요청을 먼저 해 주세요.")
    return _check_code_issue_token(db, email, last, code)


def signup(db: Session, email: str, password: str, name: str, verify_token: str) -> dict:
    """가입하기: 코드 확인 때 받은 인증 토큰을 가진 사람만 가입합니다."""
    if _user_exists(db, email):
        raise AuthError(409, "EMAIL_EXISTS", "이미 사용된 이메일이에요. 다른 이메일로 가입해 주세요.")
    last = _latest(db, email)
    _consume_token(db, email, last, verify_token)

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    t = now()
    try:
        db.execute(
            text(
                "INSERT INTO `user` (email, pw, name, auth_dt, ins_dt, ins_nm, upt_dt, upt_nm) "
                "VALUES (:e, :p, :n, :a, :t, :e, :t, :e)"
            ),
            {"e": email, "p": pw_hash, "n": name, "a": last["auth_dt"], "t": t},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AuthError(409, "EMAIL_EXISTS", "이미 사용된 이메일이에요. 다른 이메일로 가입해 주세요.")
    return {"email": email, "name": name}


# ---------- 로그인 (A01 · JWT) ----------
JWT_ALG = "HS256"
LOGIN_FAILED = "이메일 또는 비밀번호가 맞지 않아요."   # 어느 쪽이 틀렸는지 알려 주지 않음

# 가입되지 않은 이메일도 같은 시간이 걸리도록 비교에 쓰는 가짜 해시
_DUMMY_HASH = bcrypt.hashpw(b"safe-t-dummy-password", bcrypt.gensalt())


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret or len(secret) < 32:
        raise AuthError(503, "AUTH_NOT_CONFIGURED", "로그인 설정이 없어요. 관리자에게 문의해 주세요.")
    return secret


def _token_ttl() -> timedelta:
    return timedelta(minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "480")))


def has_workplace(db: Session, email: str) -> bool:
    """사용 중인 사업장이 있는지 (삭제한 사업장 use_yn='N' 은 제외)"""
    return db.execute(
        text("SELECT 1 FROM workplaces WHERE email = :e AND COALESCE(use_yn, 'Y') = 'Y' LIMIT 1"),
        {"e": email},
    ).first() is not None


def _pw_version(upt_dt) -> int:
    """비밀번호 버전 = 사용자 수정 시각(초). 재설정하면 바뀌어 이전 토큰이 무효가 됨"""
    return int(upt_dt.replace(tzinfo=KST).timestamp()) if upt_dt else 0


def login(db: Session, email: str, password: str) -> dict:
    row = db.execute(text("SELECT email, pw, name, upt_dt FROM `user` WHERE email = :e"), {"e": email}).mappings().first()
    stored = (row["pw"] if row and row["pw"] else None)
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), (stored or _DUMMY_HASH.decode()).encode("ascii"))
    except ValueError:                       # 저장값이 bcrypt 형식이 아님
        ok = False
    if not row or not stored or not ok:
        raise AuthError(401, "LOGIN_FAILED", LOGIN_FAILED)
    return _issue(db, row)


def _issue(db: Session, row) -> dict:
    """로그인 응답(토큰 발급). 일반 로그인·게스트 로그인 공통"""
    ttl = _token_ttl()
    issued = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": row["email"], "iat": issued, "exp": issued + ttl, "pwv": _pw_version(row["upt_dt"])},
        _jwt_secret(), algorithm=JWT_ALG,
    )
    return {
        "email": row["email"],
        "name": row["name"],
        "has_workplace": has_workplace(db, row["email"]),
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(ttl.total_seconds()),
    }


GUEST_NAME = "게스트(시연)"
GUEST_EMAIL_DEFAULT = "guest@safe-t.invalid"
GUEST_KEY_MIN = 24


def guest_enabled() -> bool:
    return len(os.getenv("SAFET_GUEST_KEY", "")) >= GUEST_KEY_MIN


def guest_email() -> str:
    return (os.getenv("SAFET_GUEST_EMAIL") or GUEST_EMAIL_DEFAULT).strip().lower()


def guest_login(db: Session, key: str) -> dict:
    """UX-001 시연용 게스트 로그인: QR 주소의 key 가 서버 SAFET_GUEST_KEY 와 같으면 게스트 계정으로 토큰 발급.
    - SAFET_GUEST_KEY 가 없거나 24자 미만이면 기능 꺼짐(404)
    - 게스트 계정이 없으면 만듦. 비밀번호는 임의 해시라 비밀번호로는 로그인할 수 없음
    - 게스트 데이터는 모든 시연자가 함께 씀(초기화는 운영 담당이 별도로)"""
    expected = os.getenv("SAFET_GUEST_KEY", "")
    if len(expected) < GUEST_KEY_MIN:
        raise AuthError(404, "GUEST_DISABLED", "게스트 로그인을 쓸 수 없어요. 이메일로 로그인해 주세요.")
    if not hmac.compare_digest((key or "").encode("utf-8"), expected.encode("utf-8")):
        raise AuthError(401, "GUEST_KEY_INVALID", "게스트 로그인 링크가 올바르지 않아요. 새 QR 코드를 받아 주세요.")
    email = guest_email()
    row = db.execute(text("SELECT email, pw, name, upt_dt FROM `user` WHERE email = :e"), {"e": email}).mappings().first()
    if not row:
        t = now()
        unusable = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode("ascii")
        try:
            db.execute(
                text("INSERT INTO `user` (email, pw, name, auth_dt, ins_dt, ins_nm, upt_dt, upt_nm) "
                     "VALUES (:e, :p, :n, :t, :t, 'guest', :t, 'guest')"),
                {"e": email, "p": unusable, "n": GUEST_NAME, "t": t},
            )
            db.commit()
        except IntegrityError:                 # 동시에 두 번 만들 때
            db.rollback()
        row = db.execute(text("SELECT email, pw, name, upt_dt FROM `user` WHERE email = :e"), {"e": email}).mappings().first()
    return {**_issue(db, row), "guest": True}


def user_from_token(db: Session, token: str | None) -> dict:
    """요청 헤더의 토큰으로 사용자 확인. 실패하면 401"""
    if not token:
        raise AuthError(401, "LOGIN_REQUIRED", "로그인이 필요해요.")
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALG], options={"require": ["sub", "exp"]})
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "TOKEN_EXPIRED", "로그인 시간이 지났어요. 다시 로그인해 주세요.")
    except jwt.InvalidTokenError:
        raise AuthError(401, "LOGIN_REQUIRED", "로그인이 필요해요.")
    row = db.execute(text("SELECT email, name, upt_dt FROM `user` WHERE email = :e"), {"e": payload["sub"]}).mappings().first()
    if not row:
        raise AuthError(401, "LOGIN_REQUIRED", "로그인이 필요해요.")
    if payload.get("pwv", 0) != _pw_version(row["upt_dt"]):       # 비밀번호를 바꾼 뒤의 이전 토큰
        raise AuthError(401, "LOGIN_REQUIRED", "비밀번호가 바뀌어 다시 로그인해 주세요.")
    return {"email": row["email"], "name": row["name"]}


# ---------- 비밀번호 재설정 (2026-11-16 결정 · 설계서에 화면 없음) ----------
# - 가입 여부와 관계없이 같은 응답 (가입된 이메일인지 알려 주지 않음)
# - 계정을 만든 뒤(또는 마지막으로 비밀번호를 바꾼 뒤)에 보낸 코드만 인정
#   → 회원가입 때 인증한 기록이나 이미 쓴 재설정 코드로는 바꿀 수 없음
# - 재설정하면 upt_dt 가 바뀌어 기존 로그인(토큰)이 모두 끝남
RESET_SENT = "가입된 이메일이면 인증 코드를 보냈어요. 메일을 확인해 주세요."


def _reset_user(db: Session, email: str):
    # UX-018: 탈퇴한 계정은 가입되지 않은 이메일과 같게 처리(재설정으로 되살리지 못함)
    return db.execute(
        text("SELECT email, COALESCE(upt_dt, ins_dt) AS since FROM `user` "
             "WHERE email = :e AND COALESCE(pw, '') <> :w"), {"e": email, "w": WITHDRAWN}
    ).mappings().first()


# ---------- 회원 탈퇴 (UX-018 · 2026-11-22) ----------
# - 비밀번호를 다시 확인한 뒤 처리. DB 구조는 바꾸지 않음
# - 로그인 불가(pw 표식), 이름 삭제, 기존 로그인(토큰) 모두 종료, 사업장 사용 중지, 공유 링크 중지
# - 위험성평가 기록(평가표·서명)은 법정 보존 기간 동안 남김(개인정보 안내 '보유 기간')
# - 같은 이메일로 다시 가입할 수 없음(기록 보존 중). 완전 삭제는 보존 기간 뒤 관리자 작업
WITHDRAWN = "WITHDRAWN"          # bcrypt 형식이 아니라 로그인 검사에서 항상 실패
WITHDRAW_GUARD = "withdraw:attempts"
WITHDRAW_WINDOW = timedelta(minutes=10)
WITHDRAWN_NAME = "탈퇴한 사용자"


def withdraw(db: Session, email: str, password: str) -> dict:
    row = db.execute(text("SELECT email, pw, upt_dt, ins_dt FROM `user` WHERE email = :e FOR UPDATE"), {"e": email}).mappings().first()
    # 사용자 행 잠금으로 동시 요청도 같은 계정의 한도를 공유한다.
    t = now()
    params = {"e": email, "guard": WITHDRAW_GUARD}
    guard = db.execute(text("SELECT seq, try_count, expiration_dt FROM email_verifications "
                            "WHERE email=:e AND auth_code=:guard ORDER BY seq DESC LIMIT 1 FOR UPDATE"),
                       params).mappings().first()
    active = guard and guard["expiration_dt"] > t
    if active and guard["try_count"] >= MAX_TRY:
        wait = int((guard["expiration_dt"] - t).total_seconds())
        raise AuthError(429, "WITHDRAW_TRY_LIMIT", f"{wait}초 뒤에 다시 시도해 주세요.", retry_after=wait)
    stored = row["pw"] if row else None
    try:
        ok = bool(stored) and bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii"))
    except ValueError:
        ok = False
    if not ok:
        until = guard["expiration_dt"] if active else t + WITHDRAW_WINDOW
        tries = guard["try_count"] + 1 if active else 1
        if guard:
            db.execute(text("UPDATE email_verifications SET try_count=:tries, expiration_dt=:until WHERE seq=:seq"),
                       {"tries": tries, "until": until, "seq": guard["seq"]})
        else:
            db.execute(text("INSERT INTO email_verifications (email,auth_code,try_count,expiration_dt,send_dt) "
                            "VALUES (:e,:guard,:tries,:until,:t)"), dict(params, tries=tries, until=until, t=t))
        db.commit()
        raise AuthError(400, "PASSWORD_MISMATCH", "비밀번호가 맞지 않아요. 다시 입력해 주세요.", field="password")
    t = now()
    since = row["upt_dt"] or row["ins_dt"]
    if since and t <= since:                       # 같은 초여도 토큰 버전이 바뀌게
        t = since + timedelta(seconds=1)
    db.execute(text("UPDATE `user` SET pw = :w, name = :n, upt_dt = :t, upt_nm = :e WHERE email = :e"),
               {"w": WITHDRAWN, "n": WITHDRAWN_NAME, "t": t, "e": email})
    db.execute(text("UPDATE workplaces SET use_yn = 'N', upt_dt = :t, upt_nm = :e WHERE email = :e AND COALESCE(use_yn, 'Y') = 'Y'"),
               {"t": t, "e": email})
    db.execute(text("UPDATE eval_share SET stop_yn = 'Y', upt_dt = :t, upt_nm = :e "
                    "WHERE COALESCE(stop_yn, 'N') = 'N' AND eval_no IN (SELECT eval_no FROM eval_mst WHERE email = :e)"),
               {"t": t, "e": email})
    db.commit()
    return {"email": email, "withdrawn": True}


def _latest_reset(db: Session, email: str, since):
    if since is None:
        return None
    return db.execute(
        text(
            "SELECT seq, auth_code, expiration_dt, try_count, send_dt, auth_dt FROM email_verifications "
            "WHERE email = :e AND auth_code <> :guard AND send_dt > :s ORDER BY seq DESC LIMIT 1"
        ),
        {"e": email, "s": since, "guard": WITHDRAW_GUARD},
    ).mappings().first()


def request_reset_code(db: Session, email: str, send: SendCode) -> dict:
    result = {"expires_in": int(CODE_TTL.total_seconds()), "resend_after": int(RESEND_GAP.total_seconds())}
    user = _reset_user(db, email)
    if not user:
        return result                       # 가입되지 않은 이메일도 같은 응답 (메일·기록 없음)

    t = now()
    last = _latest(db, email)
    if last and last["send_dt"] and t - last["send_dt"] < RESEND_GAP:
        wait = int((RESEND_GAP - (t - last["send_dt"])).total_seconds()) or 1
        raise AuthError(429, "RESEND_TOO_SOON", f"{wait}초 뒤에 다시 요청해 주세요.", retry_after=wait)

    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.execute(
        text(
            "INSERT INTO email_verifications (email, auth_code, expiration_dt, try_count, send_dt) "
            "VALUES (:e, :c, :x, 0, :s)"
        ),
        {"e": email, "c": _hash_code(email, code), "x": t + CODE_TTL, "s": t},
    )
    try:
        send(email, code, CODE_TTL)
    except MailConfigError:
        db.rollback()
        raise AuthError(503, "MAIL_NOT_CONFIGURED", "메일 발송 설정이 없어요. 관리자에게 문의해 주세요.")
    except Exception:
        db.rollback()
        raise AuthError(502, "MAIL_FAILED", "인증 메일을 보내지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    db.commit()
    return result


def verify_reset_code(db: Session, email: str, code: str) -> dict:
    user = _reset_user(db, email)
    last = _latest_reset(db, email, user["since"]) if user else None
    if not last:                            # 가입 안 함·요청 안 함을 구분하지 않음
        raise AuthError(400, "CODE_MISMATCH", "인증 코드가 맞지 않아요. 코드를 다시 요청해 주세요.")
    return _check_code_issue_token(db, email, last, code)


def reset_password(db: Session, email: str, password: str, verify_token: str) -> dict:
    """새 비밀번호 저장: 코드 확인 때 받은 인증 토큰을 가진 사람만"""
    user = _reset_user(db, email)
    last = _latest_reset(db, email, user["since"]) if user else None
    _consume_token(db, email, last, verify_token)

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    t = now()
    if user["since"] and t <= user["since"]:          # 같은 초에 두 번 바뀌어도 버전이 달라지게
        t = user["since"] + timedelta(seconds=1)
    try:
        updated = db.execute(
            text("UPDATE `user` SET pw = :p, upt_dt = :t, upt_nm = :e "
                 "WHERE email = :e AND COALESCE(pw, '') <> :withdrawn"),
            {"p": pw_hash, "t": t, "e": email, "withdrawn": WITHDRAWN},
        )
    except OperationalError as err:
        # MariaDB는 같은 행이 조회 뒤 변경되면 영향 행 수 대신 1020을 반환하기도 한다.
        db.rollback()
        if err.orig.args[:1] != (1020,):
            raise
        raise AuthError(400, "INVALID_VERIFY_TOKEN", "계정 상태가 변경됐어요. 인증 코드를 다시 요청해 주세요.") from err
    if updated.rowcount != 1:
        db.rollback()
        raise AuthError(400, "INVALID_VERIFY_TOKEN", "인증 정보가 맞지 않아요. 인증 코드를 다시 요청해 주세요.")
    db.commit()
    return {"email": email}
