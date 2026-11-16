"""새 평가표 작성부터 저장·확정까지. 기존 /evals 목록과 경로 호환."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from routers.auth import current_user
from schemas.assessment import CreateAssessment, SaveAssessment, AddRisk
from services import assessment as service

router=APIRouter(tags=['평가표 작성'])
@router.post('/evals',status_code=201)
def create(body:CreateAssessment,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.create(db,user['email'],body)
@router.get('/evals/{eval_no}')
def detail(eval_no:int,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.detail(db,user['email'],eval_no)
@router.put('/evals/{eval_no}')
def save(eval_no:int,body:SaveAssessment,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.save(db,user['email'],eval_no,body)
@router.post('/evals/{eval_no}/confirm')
def confirm(eval_no:int,body:SaveAssessment,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.save(db,user['email'],eval_no,body,confirm=True)
@router.post('/evals/{eval_no}/items')
def add(eval_no:int,body:AddRisk,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.add_risk(db,user['email'],eval_no,body)
