"""결과 공유 API (SHARE · 화면설계서 30쪽)

공유하는 사람 (로그인 필요, 내 평가표, 참여자 전원 서명 후):
  GET  /evals/{eval_no}/share          지금 쓸 수 있는 링크 (없으면 share: null)
  POST /evals/{eval_no}/share          링크가 없으면 만들고 있으면 그대로 (평가표당 1개, 7일)
  POST /evals/{eval_no}/share/reissue  이전 링크를 막고 새 링크 발급
  POST /evals/{eval_no}/share/stop     공유 중지 (이전 링크 바로 막힘)
  409 SIGN_NOT_DONE: 전원 서명 전

받는 사람 (로그인 없음):
  GET /share/{token}       평가표 이름·사업장·평가일·확정일·위험 수·작성자·만료일
  GET /share/{token}/pdf   공유본 PDF (서명 원본 이미지 없음) · 다운로드 횟수 +1
  410 SHARE_EXPIRED: 없는·중지·만료된 링크 (모두 같은 안내)
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import current_user
from services import share as service

router = APIRouter(tags=["결과 공유"])


@router.get("/evals/{eval_no}/share", summary="공유 링크 조회")
def get_share(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.get(db, user["email"], eval_no)


@router.post("/evals/{eval_no}/share", summary="공유 링크 만들기 (있으면 그대로)")
def issue(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.issue(db, user["email"], eval_no)


@router.post("/evals/{eval_no}/share/reissue", summary="공유 링크 재발급 (이전 링크 막힘)")
def reissue(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.issue(db, user["email"], eval_no, reissue=True)


@router.post("/evals/{eval_no}/share/stop", summary="공유 중지")
def stop(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.stop(db, user["email"], eval_no)


@router.get("/share/{token}", summary="받는 사람: 공유 평가표 정보 (로그인 없음)")
def public_info(token: str, db: Session = Depends(get_db)):
    return service.public_info(db, token)


@router.get("/share/{token}/pdf", summary="받는 사람: 공유본 PDF (로그인 없음)",
            response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
def public_pdf(token: str, db: Session = Depends(get_db)):
    def fetch(sql, params):
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]

    pdf, name = service.public_pdf(db, token, fetch)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"safet-report.pdf\"; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex",
        },
    )
