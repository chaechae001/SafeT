"""기기별 위험요인 추천 후보(RAG 인덱스 v2). 데이터는 SAFET_RAG_DIR(Cloud 비공개 폴더)에서 읽는다."""
from typing import List

from fastapi import APIRouter, Depends, Query

from routers.auth import current_user
from services import rag_retrieval

router = APIRouter(tags=['RAG 위험요인 후보'])


@router.get('/rag/hazard-candidates', summary='기기 ID로 위험요인 후보·근거 조회(모델 호출 없음)')
def hazard_candidates(equipment_id: List[str] = Query(...), k: int = Query(0, ge=0, le=14),
                      user: dict = Depends(current_user)):
    if not rag_retrieval.enabled():
        return {'enabled': False, 'candidates': [], 'no_evidence': []}
    return {'enabled': True, **rag_retrieval.candidates(equipment_id, k or None)}
