"""새 평가표 작성부터 저장·확정까지. 기존 /evals 목록과 경로 호환."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from routers.auth import current_user
from schemas.assessment import CreateAssessment, SaveAssessment, AddRisk, PendingReview, RemoveRisk
from services import assessment as service
from services import catalog_risk

router=APIRouter(tags=['평가표 작성'])
@router.get('/risk-catalog', summary='DB 위험요인·조치 후보 조회')
def catalog(user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return {'enabled': catalog_risk.enabled(), 'scenarios': catalog_risk.list_catalog(db) if catalog_risk.enabled() else []}

@router.post('/evals', status_code=201, summary='평가표 초안 생성·입력 저장')
def create(body:CreateAssessment,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.create(db,user['email'],body)
@router.get('/evals/{eval_no}', summary='평가표 상세·판정 근거 조회')
def detail(eval_no:int,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.detail(db,user['email'],eval_no)
@router.put('/evals/{eval_no}', summary='초안 저장·현재 및 개선 후 예상 위험도 계산')
def save(eval_no:int,body:SaveAssessment,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.save(db,user['email'],eval_no,body)
@router.post('/evals/{eval_no}/confirm', summary='평가표 검증·확정 및 작성 내용 잠금')
def confirm(eval_no:int,body:SaveAssessment,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.save(db,user['email'],eval_no,body,confirm=True)
@router.post('/evals/{eval_no}/items', summary='초안에 위험요인 후보 추가')
def add(eval_no:int,body:AddRisk,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.add_risk(db,user['email'],eval_no,body)
@router.post('/evals/{eval_no}/items/{dtl_no}/delete', summary='위험 항목 1개 삭제 (작성 중 평가표만)')
def remove(eval_no:int,dtl_no:int,body:RemoveRisk,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.remove_risk(db,user['email'],eval_no,dtl_no,body)
@router.post('/evals/{eval_no}/pending-rows', summary='확인 대기(등록 기기 기준) 위험을 평가표 행으로 추가하거나 제외')
def pending_rows(eval_no:int,body:PendingReview,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.review_pending(db,user['email'],eval_no,body)

from schemas.catalog_ai import RiskAnswers

@router.post('/evals/{eval_no}/risk-answers', summary='초안의 추가 답변 분석·근거 갱신')
def risk_answers(eval_no:int,body:RiskAnswers,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.answer_risks(db,user['email'],eval_no,body)
