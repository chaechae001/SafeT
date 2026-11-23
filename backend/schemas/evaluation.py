"""내 평가표 목록 응답 형식 (H01 · 화면설계서 10쪽)

테이블: eval_mst(eval_no, work_no, email, eval_nm, eval_writer, eval_dt, eval_status, confirm_dt, sign_end_dt, del_yn)
        workplaces(workplace) · eval_member(서명이 필요한 참여 근로자) · eval_sign(sign_yn, signer_type)
"""
from datetime import datetime

from pydantic import BaseModel


class EvalCard(BaseModel):
    eval_no: int
    eval_nm: str | None = None
    work_no: int
    workplace: str | None = None        # 삭제(사용 안 함)한 사업장의 평가표도 계속 보임
    eval_dt: datetime | None = None
    eval_writer: str | None = None
    eval_status: str | None = None      # W 작성 중 / C 확정 / S 서명 완료 / A 조치 완료 (공통코드 EVAL_STATUS)
    confirm_dt: datetime | None = None
    sign_end_dt: datetime | None = None
    member_count: int                   # 서명이 필요한 참여 근로자 수
    signed_count: int                   # 서명한 참여 근로자 수
    item_count: int = 0                 # 위험 항목 수(eval_dtl) · UX-017 카드 표시용, 읽기 전용


class EvalList(BaseModel):
    items: list[EvalCard]
    total: int
    page: int
    size: int
