"""새 평가표 작성부터 저장·확정까지. 기존 /evals 목록과 경로 호환."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from routers.auth import current_user
from schemas.assessment import CreateAssessment, SaveAssessment, AddRisk, AnswerRisk
from services import assessment as service
from services import catalog_risk, catalog_ai

router=APIRouter(tags=['평가표 작성'])
@router.get('/risk-catalog', summary='DB 위험요인·조치 후보 조회')
def catalog(user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return {'enabled': (catalog_risk.enabled() or catalog_ai.enabled()), 'scenarios': catalog_risk.list_catalog(db) if (catalog_risk.enabled() or catalog_ai.enabled()) else []}

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

@router.post('/evals/{eval_no}/risk-answers', summary='추가 확인 답변을 반영해 DB 시나리오·근거 갱신')
def answer(eval_no:int,body:AnswerRisk,user:dict=Depends(current_user),db:Session=Depends(get_db)):
    return service.reanalyze(db,user['email'],eval_no,body.revision,body.answers,body.additional_text)
