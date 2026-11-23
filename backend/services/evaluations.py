"""내 평가표 목록 (H01 · 화면설계서 10쪽)

- 탭 4개 (UX-022 · 2026-11-23 사용자 결정: 확정 탭에는 서명 완료 평가표를 넣지 않음. 서명 완료는 서명 완료 탭에만)
    ALL 전체    : 상태 조건 없음 (2026-11-17 추가, 화면 맨 앞 탭)
    W 작성 중   : eval_status = 'W'
    C 확정      : eval_status = 'C' AND sign_end_dt IS NULL   (확정했고 서명이 끝나지 않은 평가표)
    S 서명 완료 : sign_end_dt 가 있음
    A 조치 완료 : eval_status = 'A'
- 기간: 평가일(eval_dt) 기준, 시작일·종료일 포함
- 사업장: 내 사업장만. 삭제(use_yn='N')한 사업장의 평가표도 목록에는 계속 보임 (08쪽)
- 휴지통(del_yn='Y')은 제외, 10개씩, 평가일 최근 순
"""
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.auth import AuthError

PAGE_SIZE = 10

TAB_WHERE = {
    "ALL": "1 = 1",                                   # 전체: 상태 조건 없음 (휴지통·기간·사업장 조건은 그대로)
    "W": "m.eval_status = 'W'",
    "C": "m.eval_status = 'C' AND m.sign_end_dt IS NULL",   # UX-022: 서명 완료는 S 탭에만
    "S": "m.sign_end_dt IS NOT NULL",
    "A": "m.eval_status = 'A'",
}


def list_evals(db: Session, email: str, tab: str, start: date | None, end: date | None,
               work_no: int | None, page: int) -> dict:
    if tab not in TAB_WHERE:
        raise AuthError(400, "INVALID_TAB", "탭 값이 올바르지 않아요.")
    if start and end and start > end:
        raise AuthError(400, "INVALID_PERIOD", "시작일이 종료일보다 늦어요.")

    where = ["m.email = :e", "COALESCE(m.del_yn, 'N') = 'N'", TAB_WHERE[tab]]
    params: dict = {"e": email}
    if start:
        where.append("m.eval_dt >= :s")
        params["s"] = start
    if end:
        where.append("m.eval_dt < :t")                 # 종료일 포함 → 다음 날 0시 전까지
        params["t"] = end + timedelta(days=1)
    if work_no:
        where.append("m.work_no = :w")
        params["w"] = work_no
    cond = " AND ".join(where)

    total = db.execute(text(f"SELECT COUNT(*) FROM eval_mst m WHERE {cond}"), params).scalar() or 0
    page = max(1, page)
    rows = db.execute(
        text(
            "SELECT m.eval_no, m.eval_nm, m.work_no, w.workplace, m.eval_dt, m.eval_writer, m.eval_status, "
            "       m.confirm_dt, m.sign_end_dt, "
            "       (SELECT COUNT(*) FROM eval_member em WHERE em.eval_no = m.eval_no) AS member_count, "
            "       (SELECT COUNT(DISTINCT s.member_no) FROM eval_sign s "
            "         WHERE s.eval_no = m.eval_no AND s.sign_yn = 'Y' AND s.signer_type = 'WO') AS signed_count, "
            "       (SELECT COUNT(*) FROM eval_dtl d WHERE d.eval_no = m.eval_no) AS item_count, "  # UX-017 카드 '위험 항목 N건'
            # UX-018 확인 대기(등록 기기 기준 후보) 수: authoring_snapshot.rls_pending 길이. 추가·제외하면 목록에서 빠짐
            "       COALESCE(CASE WHEN JSON_VALID(m.authoring_snapshot) "
            "         THEN JSON_LENGTH(m.authoring_snapshot, '$.rls_pending') END, 0) AS pending_count "
            f"FROM eval_mst m LEFT JOIN workplaces w ON w.work_no = m.work_no WHERE {cond} "
            "ORDER BY m.eval_dt DESC, m.eval_no DESC LIMIT :lim OFFSET :off"
        ),
        {**params, "lim": PAGE_SIZE, "off": (page - 1) * PAGE_SIZE},
    ).mappings().all()
    return {"items": [dict(r) for r in rows], "total": int(total), "page": page, "size": PAGE_SIZE}
