"""사업장 API (B01 · B02 · B02-E) · 모두 로그인 필요

GET    /biz-categories                    업종 목록
GET    /biz-categories/{biz_code}/machines 업종별 기기 목록
GET    /workplaces                        내 사업장 목록 (사용 중만)
GET    /workplaces/{work_no}              사업장 한 곳
POST   /workplaces                        등록
PUT    /workplaces/{work_no}              수정 (사업장명·보유 기기, 업종 변경 불가)
DELETE /workplaces/{work_no}              삭제 = 사용 안 함(use_yn='N')
"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import current_user
from schemas.workplace import BizCategory, Machine, WorkplaceCreate, WorkplaceCreated, WorkplaceInfo, WorkplaceSave
from services import workplaces as service

router = APIRouter(tags=["사업장"], dependencies=[Depends(current_user)])


@router.get("/biz-categories", response_model=list[BizCategory], summary="업종 목록")
def biz_categories(db: Session = Depends(get_db)):
    return service.biz_categories(db)


@router.get("/biz-categories/{biz_code}/machines", response_model=list[Machine], summary="업종별 기기 목록")
def machines(biz_code: str, db: Session = Depends(get_db)):
    return service.machines(db, biz_code)


@router.get("/workplaces", response_model=list[WorkplaceInfo], summary="내 사업장 목록")
def list_workplaces(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.list_workplaces(db, user["email"])


@router.get("/workplaces/{work_no}", response_model=WorkplaceInfo, summary="사업장 한 곳")
def get_workplace(work_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.get_workplace(db, user["email"], work_no)


@router.post("/workplaces", response_model=WorkplaceCreated, status_code=201, summary="사업장 등록")
def create_workplace(body: WorkplaceCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.create_workplace(db, user["email"], body.workplace, body.biz_code, body.machine_codes, body.custom_machines)


@router.put("/workplaces/{work_no}", response_model=WorkplaceInfo, summary="사업장 수정")
def update_workplace(work_no: int, body: WorkplaceSave, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.update_workplace(db, user["email"], work_no, body.workplace, body.machine_codes, body.custom_machines)


@router.delete("/workplaces/{work_no}", status_code=204, summary="사업장 삭제(사용 안 함)")
def delete_workplace(work_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    service.delete_workplace(db, user["email"], work_no)
    return Response(status_code=204)
