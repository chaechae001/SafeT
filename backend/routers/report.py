"""문서 다운로드 (위험성평가 결과서 PDF) · 로그인 필요

GET /evals/{eval_no}/report   → application/pdf (첨부 파일)
- 내 평가표만 (남의 것·휴지통은 404). 작성 중(W)도 '미확정본'으로 내려받을 수 있음 (화면설계서 33쪽)
- 아직 eval_report 에 파일을 저장하지 않고 요청할 때마다 새로 만듦 (파일 보관 위치 결정 전)
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import current_user
from services import report_service as service
from services.assessment import owned

router = APIRouter(tags=["문서 다운로드"])


@router.get("/evals/{eval_no}/report", summary="위험성평가 결과서 PDF",
            response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
def report(eval_no: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    owned(db, user["email"], eval_no)

    def fetch(sql, params):
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]

    ctx = service.build_context(eval_no, fetch)
    pdf = service.render_pdf(ctx)
    name = service.file_name(ctx)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            # 한글 파일 이름: filename*(UTF-8) + 영문 대체 이름
            "Content-Disposition": f"attachment; filename=\"safet-report-{eval_no}.pdf\"; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "no-store",
        },
    )
