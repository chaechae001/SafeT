"""상태 확인 API"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from database import ping

router = APIRouter(prefix="/health", tags=["상태 확인"])


@router.get("/db", summary="DB 연결 확인")
def health_db():
    """DB 연결 상태. 실패해도 비밀번호 등 접속 정보는 응답에 넣지 않습니다."""
    try:
        info = ping()
        return {"status": "ok", **info, "table_count": len(info["tables"])}
    except SQLAlchemyError as e:
        return JSONResponse(status_code=503, content={"status": "error", "error": type(e).__name__})
