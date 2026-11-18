"""평가표 삭제·휴지통 (H02 · C02 · 화면설계서 31쪽)

- 작성 중(W) 평가표만 삭제 → 휴지통(eval_mst.del_yn='Y', del_dt). 확정·서명된 평가표는 삭제 불가(법정 기록 보존)
- 휴지통 보관 30일. 지난 평가표는 휴지통 목록을 열 때 영구 삭제 (별도 예약 작업 없음)
- 복원: del_yn='N' 으로 되돌려 이전 입력 그대로 작성 중 탭으로
- 영구 삭제: 평가표와 딸린 행을 참조 순서대로 지움. 복원 불가
"""
from datetime import timedelta

from services.assessment import execute, owned, rows, locked_rows
from services.auth import AuthError, now

KEEP_DAYS = 30


def delete(db, email, no):
    """작성 중 평가표를 휴지통으로"""
    try:
        m = owned(db, email, no, lock=True)          # 남의 것·이미 휴지통이면 404
        if m['eval_status'] != 'W':
            raise AuthError(409, 'EVAL_LOCKED', '확정한 평가표는 삭제할 수 없어요.')
        t = now()
        execute(db, "UPDATE eval_mst SET del_yn = 'Y', del_dt = :t, upt_dt = :t, upt_nm = :e WHERE eval_no = :n",
                n=no, t=t, e=email)
        db.commit()
    except Exception:
        db.rollback()
        raise


def _trashed(db, email, no, lock=False):
    r = (locked_rows if lock else rows)(db, "SELECT * FROM eval_mst WHERE eval_no = :n AND email = :e AND del_yn = 'Y' AND eval_status = 'W'"
                 + (" FOR UPDATE" if lock else ""), n=no, e=email)
    if not r:
        raise AuthError(404, 'TRASH_NOT_FOUND', '휴지통에서 평가표를 찾을 수 없어요.')
    return r[0]


def _expired(m, t):
    return not m['del_dt'] or m['del_dt'] + timedelta(days=KEEP_DAYS) <= t


def _purge_rows(db, no):
    """평가표 한 건과 딸린 행 삭제 (외래키 참조 순서)"""
    dtl = "SELECT eval_dtl_no FROM eval_dtl WHERE eval_no = :n"
    execute(db, f"DELETE FROM eval_action WHERE eval_dtl_no IN ({dtl})", n=no)
    execute(db, "DELETE FROM eval_file WHERE eval_no = :n", n=no)
    execute(db, f"DELETE FROM eval_file WHERE eval_dtl_no IN ({dtl})", n=no)
    for table in ('risk_event', 'eval_share', 'eval_sign', 'eval_report', 'eval_dtl', 'eval_machine', 'eval_member'):
        if table == 'risk_event' and not rows(db, "SHOW TABLES LIKE 'risk_event'"):
            continue                                  # DB 기준 마이그레이션 전이면 테이블 없음
        execute(db, f"DELETE FROM {table} WHERE eval_no = :n", n=no)
    execute(db, "DELETE FROM eval_mst WHERE eval_no = :n", n=no)


def _purge_expired(db, email, t):
    # 고를 때부터 잠금(FOR UPDATE): 동시에 복원이 들어오면 복원이 먼저 커밋됐을 땐 여기서 빠지고,
    # 여기가 먼저 잠갔을 땐 복원이 기다렸다가 404. '복원 성공 → 삭제'가 겹치지 않게 함.
    # 잠그지 않고 고르면 복원이 끼어든 뒤 그 평가표를 지우거나(snapshot isolation OFF),
    # 1020 오류로 목록이 실패함(MariaDB 11.6.2+ 기본 ON).
    old = locked_rows(db, "SELECT eval_no FROM eval_mst WHERE email = :e AND del_yn = 'Y' AND eval_status = 'W' "
                   "AND (del_dt IS NULL OR del_dt <= :limit) FOR UPDATE", e=email, limit=t - timedelta(days=KEEP_DAYS))
    for r in old:
        _purge_rows(db, r['eval_no'])
    return len(old)


def list_trash(db, email):
    """30일 지난 것을 먼저 지우고, 남은 휴지통 목록 (삭제 최근 순)"""
    t = now()
    try:
        _purge_expired(db, email, t)
        db.commit()
    except Exception:
        db.rollback()
        raise
    items = []
    for r in rows(db, "SELECT m.eval_no, m.eval_nm, m.eval_dt, m.del_dt, w.workplace FROM eval_mst m "
                      "LEFT JOIN workplaces w ON w.work_no = m.work_no "
                      "WHERE m.email = :e AND m.del_yn = 'Y' AND m.eval_status = 'W' "
                      "ORDER BY m.del_dt DESC, m.eval_no DESC", e=email):
        purge_at = r['del_dt'] + timedelta(days=KEEP_DAYS)
        days_left = max(1, (purge_at.date() - t.date()).days)
        items.append(dict(r, purge_dt=purge_at, days_left=days_left))
    return {'items': items, 'keep_days': KEEP_DAYS}


def restore(db, email, no):
    try:
        m = _trashed(db, email, no, lock=True)
        t = now()
        if _expired(m, t):                            # 보관 기간이 지났으면 복원하지 않고 지움
            _purge_rows(db, no)
            db.commit()
            raise AuthError(410, 'TRASH_EXPIRED', '보관 기간 30일이 지나 복원할 수 없어요.')
        execute(db, "UPDATE eval_mst SET del_yn = 'N', del_dt = NULL, upt_dt = :t, upt_nm = :e WHERE eval_no = :n",
                n=no, t=t, e=email)
        db.commit()
    except Exception:
        db.rollback()                                 # 만료 삭제는 위에서 이미 commit 됨 (rollback 영향 없음)
        raise
    # 화면이 내 평가표의 기간·사업장 선택을 이 평가표가 보이게 맞추는 데 씀
    return {'eval_no': no, 'eval_nm': m['eval_nm'], 'eval_dt': m['eval_dt'], 'work_no': m['work_no']}


def purge(db, email, no):
    try:
        _trashed(db, email, no, lock=True)
        _purge_rows(db, no)
        db.commit()
    except Exception:
        db.rollback()
        raise
