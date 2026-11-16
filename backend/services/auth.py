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


def _user_exists(db: Session, email: str) -> bool:
    return db.execute(text("SELECT 1 FROM `user` WHERE email = :e"), {"e": email}).first() is not None


def _latest(db: Session, email: str):
    return db.execute(
        text(
            "SELECT seq, auth_code, expiration_dt, try_count, send_dt, auth_dt "
            "FROM email_verifications WHERE email = :e ORDER BY seq DESC LIMIT 1"
        ),
        {"e": email},
    ).mappings().first()


def request_code(db: Session, email: str, send: SendCode) -> dict:
    """인증 요청: 코드를 만들어 저장하고 메일로 보냅니다. 메일 발송에 실패하면 저장하지 않습니다."""
    if _user_exists(db, email):
        raise AuthError(409, "EMAIL_EXISTS", "이미 가입한 이메일이에요. 로그인해 주세요.")

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
    """인증 코드 확인: 가장 최근에 보낸 코드와 비교합니다."""
    last = _latest(db, email)
    if not last:
        raise AuthError(400, "CODE_NOT_REQUESTED", "인증 요청을 먼저 해 주세요.")
    if last["auth_dt"]:
        return {"verified": True}
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

    db.execute(text("UPDATE email_verifications SET auth_dt = :t WHERE seq = :q"), {"t": now(), "q": last["seq"]})
    db.commit()
    return {"verified": True}


def signup(db: Session, email: str, password: str, name: str) -> dict:
    """가입하기: 인증을 마친 이메일만 가입합니다."""
    if _user_exists(db, email):
        raise AuthError(409, "EMAIL_EXISTS", "이미 가입한 이메일이에요. 로그인해 주세요.")
    last = _latest(db, email)
    if not last or not last["auth_dt"]:
        raise AuthError(400, "NOT_VERIFIED", "이메일 인증을 먼저 해 주세요.")
    if now() - last["auth_dt"] > SIGNUP_WINDOW:
        raise AuthError(400, "VERIFY_EXPIRED", "인증한 지 30분이 지났어요. 인증 코드를 다시 요청해 주세요.")

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
        raise AuthError(409, "EMAIL_EXISTS", "이미 가입한 이메일이에요. 로그인해 주세요.")
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


def login(db: Session, email: str, password: str) -> dict:
    row = db.execute(text("SELECT email, pw, name FROM `user` WHERE email = :e"), {"e": email}).mappings().first()
    stored = (row["pw"] if row and row["pw"] else None)
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), (stored or _DUMMY_HASH.decode()).encode("ascii"))
    except ValueError:                       # 저장값이 bcrypt 형식이 아님
        ok = False
    if not row or not stored or not ok:
        raise AuthError(401, "LOGIN_FAILED", LOGIN_FAILED)

    ttl = _token_ttl()
    issued = datetime.now(timezone.utc)
    token = jwt.encode({"sub": row["email"], "iat": issued, "exp": issued + ttl}, _jwt_secret(), algorithm=JWT_ALG)
    return {
        "email": row["email"],
        "name": row["name"],
        "has_workplace": has_workplace(db, row["email"]),
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(ttl.total_seconds()),
    }


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
    row = db.execute(text("SELECT email, name FROM `user` WHERE email = :e"), {"e": payload["sub"]}).mappings().first()
    if not row:
        raise AuthError(401, "LOGIN_REQUIRED", "로그인이 필요해요.")
    return {"email": row["email"], "name": row["name"]}
