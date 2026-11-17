"""평가표 삭제·휴지통 API (H02 · C02 · 화면설계서 31쪽) · 로그인 필요, 내 평가표만

DELETE /evals/{eval_no}          작성 중 평가표를 휴지통으로 (확정·서명된 평가표는 409 EVAL_LOCKED)
GET    /trash                    휴지통 목록 (30일 지난 것은 이때 영구 삭제) · 남은 일수 포함
POST   /trash/{eval_no}/restore  복원 → 작성 중 탭 (보관 기간이 지났으면 410 TRASH_EXPIRED)
DELETE /trash/{eval_no}          영구 삭제 (복원 불가)
"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import current_user
from services import trash as service

router = APIRouter(tags=["휴지통"])


@router.delete("/evals/{eval_no}", status_code=204, summary="평가표 삭제 (휴지통으로)")
def delete_eval(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    service.delete(db, user["email"], eval_no)
    return Response(status_code=204)


@router.get("/trash", summary="휴지통 목록")
def list_trash(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.list_trash(db, user["email"])


@router.post("/trash/{eval_no}/restore", summary="휴지통에서 복원")
def restore(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.restore(db, user["email"], eval_no)


@router.delete("/trash/{eval_no}", status_code=204, summary="영구 삭제")
def purge(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    service.purge(db, user["email"], eval_no)
    return Response(status_code=204)
