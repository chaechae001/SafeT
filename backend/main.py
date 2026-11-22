"""Safe-T 백엔드 앱 시작점

실행 (backend 폴더에서):
    .venv\\Scripts\\python -m uvicorn main:app --reload --port 8001
확인:
    http://localhost:8001/health/db   ·   API 문서 http://localhost:8001/docs
기존 작성·초안·조회 화면과 같은 평가표 API를 사용합니다.
"""
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import database  # noqa: F401  (.env 를 먼저 읽음)
from routers import auth, evaluations, health, workplaces, assessment, report, sign, share, rag, trash, dev_outbox
from services.auth import AuthError

app = FastAPI(title="Safe-T API", version="0.1.0")

# 화면(프런트엔드 확인 서버 8000번)에서 API(8001번)를 부를 수 있게 허용할 주소
FRONTEND_ORIGINS = [
    o.strip()
    for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Retry-After", "Content-Disposition"],   # 문서 다운로드 파일 이름
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(workplaces.router)
app.include_router(evaluations.router)
app.include_router(assessment.router)
app.include_router(report.router)
app.include_router(sign.router)
app.include_router(share.router)
app.include_router(rag.router)
app.include_router(trash.router)
app.include_router(dev_outbox.router)   # 개발용 메일 보관함 (SAFET_DEV_MAIL_OUTBOX 설정 + 이 PC 요청만)


@app.exception_handler(AuthError)
def auth_error_handler(request: Request, exc: AuthError):
    """업무 오류 → {"detail": {"code", "message", ...}} (임시 형식, contracts 합의 전)"""
    headers = {"Retry-After": str(exc.extra["retry_after"])} if "retry_after" in exc.extra else None
    if exc.status == 401:
        headers = {**(headers or {}), "WWW-Authenticate": "Bearer"}
    return JSONResponse(
        status_code=exc.status,
        content={"detail": {"code": exc.code, "message": exc.message, **exc.extra}},
        headers=headers,
    )
