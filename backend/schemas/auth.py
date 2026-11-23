"""회원가입 요청·응답 형식 (A02 · 화면설계서 07쪽)

순서: 이메일 → 인증 코드 → 비밀번호 → 이름
테이블: user(email, pw, name, auth_dt) · email_verifications(email, auth_code, expiration_dt, try_count, send_dt, auth_dt)
"""
import re

from pydantic import BaseModel, field_validator

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
EMAIL_MAX = 50          # user.email varchar(50)
NAME_MAX = 50           # user.name varchar(50)
PASSWORD_MIN = 8        # 화면설계서: 8자 이상
PASSWORD_MAX_BYTES = 72  # bcrypt 가 쓰는 최대 길이


PASSWORD_RULE_MSG = "비밀번호는 대문자·소문자·숫자·특수문자를 모두 넣어 8자 이상으로 만들어 주세요."


def password_rule_ok(v: str) -> bool:
    """UX-001(2026-11-21): 영문 대문자·소문자·숫자·특수문자 모두 포함 + 8자 이상.
    화면(frontend/js/login.js pwRules)과 같은 규칙. 특수문자 = 영문·숫자·공백이 아닌 문자"""
    v = v or ""
    return (len(v) >= PASSWORD_MIN and re.search(r"[A-Z]", v) is not None and re.search(r"[a-z]", v) is not None
            and re.search(r"[0-9]", v) is not None and re.search(r"[^A-Za-z0-9\s]", v) is not None)


def check_password(v: str) -> str:
    """새 비밀번호 규칙 (회원가입·재설정 공통): 대·소문자·숫자·특수문자 포함 8자 이상, bcrypt 최대 72바이트.
    로그인은 이 규칙을 검사하지 않아 기존 계정은 그대로 로그인할 수 있습니다."""
    if len(v or "") < PASSWORD_MIN:
        raise ValueError(f"비밀번호는 {PASSWORD_MIN}자 이상 입력해 주세요.")
    if len(v.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError("비밀번호가 너무 길어요.")
    if not password_rule_ok(v):
        raise ValueError(PASSWORD_RULE_MSG)
    return v


def normalize_email(v: str) -> str:
    v = (v or "").strip().lower()
    if len(v) > EMAIL_MAX or not EMAIL_RE.match(v):
        raise ValueError("이메일 형식을 확인해 주세요.")
    return v


class CodeRequest(BaseModel):
    """인증 요청"""
    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)


class CodeVerify(BaseModel):
    """인증 코드 확인"""
    email: str
    code: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = (v or "").strip()
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("6자리 숫자 코드를 입력해 주세요.")
        return v


class SignupRequest(BaseModel):
    """가입하기 (코드 확인 때 받은 인증 토큰 필요)"""
    email: str
    password: str
    name: str
    verify_token: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = re.sub(r"\s+", " ", (v or "").strip())
        if not v:
            raise ValueError("이름을 입력해 주세요.")
        if len(v) > NAME_MAX:
            raise ValueError(f"이름은 {NAME_MAX}자 이내로 입력해 주세요.")
        return v


class PasswordReset(BaseModel):
    """비밀번호 재설정 (코드 확인 때 받은 인증 토큰 필요)"""
    email: str
    password: str
    verify_token: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password(v)


class PasswordResetDone(BaseModel):
    email: str


class LoginRequest(BaseModel):
    """로그인 (A01): 이메일·비밀번호만. 로그인 유지 기능 없음"""
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not v:
            raise ValueError("비밀번호를 입력해 주세요.")
        return v


class GuestLoginRequest(BaseModel):
    """게스트 로그인 (UX-001 · 시연용 QR). key = 서버 .env 의 SAFET_GUEST_KEY"""
    key: str


class UserInfo(BaseModel):
    email: str
    name: str | None = None
    has_workplace: bool          # 사용 중(use_yn='Y')인 사업장이 하나라도 있는지


class LoginResult(UserInfo):
    access_token: str
    token_type: str = "bearer"
    expires_in: int              # 토큰 유효 시간(초)


class CodeSent(BaseModel):
    expires_in: int        # 코드 유효 시간(초)
    resend_after: int      # 다시 요청할 수 있을 때까지(초)


class CodeVerified(BaseModel):
    verified: bool
    verify_token: str        # 일회용 인증 토큰: 가입하기·비밀번호 바꾸기에 함께 보냄 (30분 안, 한 번만)


class SignupResult(BaseModel):
    email: str
    name: str
