"""회원가입·로그인 API (A01 · A02)

POST /auth/signup/code           인증 요청 (메일 발송)
POST /auth/signup/code/verify    인증 코드 확인
POST /auth/signup                가입하기
POST /auth/login                 로그인 → 토큰(JWT) + 사업장 유무
GET  /auth/me                    현재 로그인한 사용자 (헤더 Authorization: Bearer <토큰>)
POST /auth/password/code         비밀번호 재설정 인증 요청 (가입 여부와 관계없이 같은 응답)
POST /auth/password/code/verify  재설정 인증 코드 확인
POST /auth/password/reset        새 비밀번호 저장 → 기존 로그인(토큰) 모두 끝남
오류 응답(임시 형식, contracts 합의 전): {"detail": {"code": "...", "message": "..."}}
"""
from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import get_db
from functools import partial

from schemas.auth import (
    CodeRequest, CodeSent, CodeVerified, CodeVerify, LoginRequest, LoginResult,
    PasswordReset, PasswordResetDone, SignupRequest, SignupResult, UserInfo,
)
from services import auth as service
from services import mailer

router = APIRouter(prefix="/auth", tags=["회원가입·로그인"])
bearer = HTTPBearer(auto_error=False)


def get_mailer() -> service.SendCode:
    """메일 발송 함수. 테스트에서는 이 의존성을 바꿔 실제 메일을 보내지 않습니다."""
    return mailer.send_code


def get_reset_mailer() -> service.SendCode:
    """비밀번호 재설정 메일 발송 함수. 테스트에서는 이 의존성을 바꿉니다."""
    return partial(mailer.send_code, purpose="reset")


def current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> dict:
    """로그인이 필요한 API 에서 쓰는 의존성: {email, name}"""
    return service.user_from_token(db, cred.credentials if cred else None)


@router.post("/signup/code", response_model=CodeSent, summary="인증 요청 (메일 발송)")
def request_code(body: CodeRequest, db: Session = Depends(get_db), send=Depends(get_mailer)):
    return service.request_code(db, body.email, send)


@router.post("/signup/code/verify", response_model=CodeVerified, summary="인증 코드 확인")
def verify_code(body: CodeVerify, db: Session = Depends(get_db)):
    return service.verify_code(db, body.email, body.code)


@router.post("/signup", response_model=SignupResult, status_code=201, summary="가입하기")
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    return service.signup(db, body.email, body.password, body.name, body.verify_token)


@router.post("/login", response_model=LoginResult, summary="로그인")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    return service.login(db, body.email, body.password)


@router.post("/password/code", response_model=CodeSent, summary="비밀번호 재설정 인증 요청")
def request_reset_code(body: CodeRequest, db: Session = Depends(get_db), send=Depends(get_reset_mailer)):
    return service.request_reset_code(db, body.email, send)


@router.post("/password/code/verify", response_model=CodeVerified, summary="재설정 인증 코드 확인")
def verify_reset_code(body: CodeVerify, db: Session = Depends(get_db)):
    return service.verify_reset_code(db, body.email, body.code)


@router.post("/password/reset", response_model=PasswordResetDone, summary="새 비밀번호 저장")
def reset_password(body: PasswordReset, db: Session = Depends(get_db)):
    return service.reset_password(db, body.email, body.password, body.verify_token)


@router.get("/me", response_model=UserInfo, summary="현재 로그인한 사용자")
def me(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return {**user, "has_workplace": service.has_workplace(db, user["email"])}
