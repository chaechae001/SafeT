"""참여자 서명 API (SIGN · 화면설계서 29쪽) · 로그인 필요, 내 평가표만

GET  /evals/{eval_no}/signs   참여 근로자별 서명 여부·시각 (서명 이미지는 내려주지 않음)
POST /evals/{eval_no}/signs   {member_no, confirm: true, sign_img: "data:image/png;base64,..."} → 갱신된 목록
     409 EVAL_NOT_CONFIRMED(작성 중) / 409 ALREADY_SIGNED(정정 불가) / 404 MEMBER_NOT_FOUND / 422 형식
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import current_user
from schemas.sign import SaveSign
from services import sign as service

router = APIRouter(tags=["참여자 서명"])


@router.get("/evals/{eval_no}/signs", summary="참여자 서명 현황")
def signs(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.summary(db, user["email"], eval_no)


@router.post("/evals/{eval_no}/signs", status_code=201, summary="참여자 서명 저장 (정정 불가)")
def save_sign(eval_no: int, body: SaveSign, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.save(db, user["email"], eval_no, body)
