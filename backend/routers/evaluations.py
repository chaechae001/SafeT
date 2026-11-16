"""내 평가표 API (H01) · 로그인 필요

GET /evals?tab=C&start=2026-11-01&end=2026-11-16&work_no=&page=1
    tab: W 작성 중 / C 확정 / S 서명 완료 / A 조치 완료 (기본 C)
"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import current_user
from schemas.evaluation import EvalList
from services import evaluations as service

router = APIRouter(tags=["평가표"])


@router.get("/evals", response_model=EvalList, summary="내 평가표 목록")
def list_evals(
    tab: str = Query("C", description="W 작성 중 / C 확정 / S 서명 완료 / A 조치 완료"),
    start: date | None = Query(None, description="평가일 시작 (YYYY-MM-DD)"),
    end: date | None = Query(None, description="평가일 종료 (YYYY-MM-DD, 포함)"),
    work_no: int | None = Query(None, description="사업장 번호 (비우면 전체)"),
    page: int = Query(1, ge=1),
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    return service.list_evals(db, user["email"], tab, start, end, work_no, page)
