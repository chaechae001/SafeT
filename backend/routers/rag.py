"""기기별 위험요인 추천 후보(RAG 인덱스 v2). 데이터는 SAFET_RAG_DIR(Cloud 비공개 폴더)에서 읽는다."""
import os
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import current_user
from services import rag_retrieval, risk_cards
from services.auth import AuthError

router = APIRouter(tags=['RAG 위험요인 후보'])


@router.get('/rag/hazard-candidates', summary='기기 ID로 위험요인 후보·근거 조회(모델 호출 없음)')
def hazard_candidates(equipment_id: List[str] = Query(...), k: int = Query(0, ge=0, le=14),
                      user: dict = Depends(current_user)):
    if not rag_retrieval.enabled():
        return {'enabled': False, 'candidates': [], 'no_evidence': []}
    return {'enabled': True, **rag_retrieval.candidates(equipment_id, k or None)}


@router.get('/rag/risk-cards', summary='기기·시나리오 ID로 근거 카드 조회')
def list_risk_cards(equipment_id: str | None = None, scenario_id: str | None = None,
                    limit: int = Query(50, ge=1, le=100), user: dict = Depends(current_user),
                    db: Session = Depends(get_db)):
    if os.getenv('SAFET_RISK_CARDS_ENABLED') != '1':
        return {'enabled': False, 'cards': []}
    if (equipment_id is None and scenario_id is None
            or equipment_id is not None and equipment_id not in risk_cards.EQUIPMENT_IDS
            or scenario_id is not None and scenario_id not in risk_cards.SCENARIO_IDS):
        raise AuthError(422, 'INVALID_RISK_CARD_FILTER', '등록된 기기 또는 시나리오 ID를 지정해 주세요.')
    try:
        cards = risk_cards.load_cards(db, equipment_id=equipment_id, scenario_id=scenario_id, limit=limit)
    except SQLAlchemyError:
        raise AuthError(503, 'RISK_CARD_DB_UNAVAILABLE', '카드 DB 연결과 마이그레이션 상태를 확인해 주세요.') from None
    return {'enabled': True, 'cards': cards}
