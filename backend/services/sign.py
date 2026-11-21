"""참여자 서명 (SIGN · 화면설계서 29쪽)

- 확정된 평가표(eval_status C·S·A)에서만 조회·저장. 작성 중(W)은 409
- 참여 근로자(eval_member)별 1회. 저장한 서명은 정정할 수 없음 (다시 저장하면 409)
- 서명 기록: eval_sign(signer_type='WO' 참여 근로자, confirm_yn='Y', sign_yn='Y', sign_img, sign_dt)
- 전원 서명하면 eval_mst.sign_end_dt 기록, 상태 C → S (조치 완료 A 는 그대로)
- 조회 응답에는 서명 이미지를 넣지 않음 (다른 사람의 서명 원본 노출 방지)
"""
from services.assessment import execute, owned, rows
from services.auth import AuthError, now

CONFIRMED = ('C', 'S', 'A')


def _confirmed(db, email, no, lock=False):
    m = owned(db, email, no, lock)
    if m['eval_status'] not in CONFIRMED:
        raise AuthError(409, 'EVAL_NOT_CONFIRMED', '확정한 평가표만 서명할 수 있어요.')
    return m


def _members(db, no):
    return rows(db, """
        SELECT em.member_no, em.member_nm,
               (SELECT MIN(s.sign_dt) FROM eval_sign s
                 WHERE s.eval_no = em.eval_no AND s.member_no = em.member_no
                   AND s.sign_yn = 'Y' AND s.signer_type = 'WO') AS sign_dt
          FROM eval_member em
         WHERE em.eval_no = :n
         ORDER BY em.sort, em.member_no""", n=no)


def summary(db, email, no):
    m = _confirmed(db, email, no)
    members = [dict(member_no=r['member_no'], member_nm=r['member_nm'],
                    signed=r['sign_dt'] is not None, sign_dt=r['sign_dt']) for r in _members(db, no)]
    return dict(eval_no=no, eval_nm=m['eval_nm'], eval_status=m['eval_status'], sign_end_dt=m['sign_end_dt'],
                members=members, member_count=len(members), signed_count=sum(x['signed'] for x in members))


def add_member(db, email, no, body):
    """UX-016: 확정된 평가표에 서명할 사람 추가 (참여자 0명이면 서명할 수 없던 문제).
    - 기존 eval_member 테이블에 한 줄 추가(구조 변경 없음)
    - 전원 서명이 끝난 평가표(sign_end_dt 있음)에는 추가하지 않음: 409 SIGN_CLOSED
    - 같은 이름이 이미 있으면 409 MEMBER_EXISTS"""
    try:
        m = _confirmed(db, email, no, lock=True)
        if m['sign_end_dt'] is not None:
            raise AuthError(409, 'SIGN_CLOSED', '모두 서명을 마친 평가표에는 사람을 추가할 수 없어요.')
        names = [r['member_nm'] for r in _members(db, no)]
        if body.member_nm in names:
            raise AuthError(409, 'MEMBER_EXISTS', '이미 있는 이름이에요.')
        if len(names) >= 30:
            raise AuthError(409, 'MEMBER_LIMIT', '참여자는 30명까지 추가할 수 있어요.')
        execute(db, 'INSERT INTO eval_member (eval_no, member_nm, sort) VALUES (:n, :nm, :s)',
                n=no, nm=body.member_nm, s=len(names))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return summary(db, email, no)


def save(db, email, no, body):
    try:
        _confirmed(db, email, no, lock=True)          # 같은 평가표 동시 서명 직렬화
        member = rows(db, 'SELECT member_no, member_nm FROM eval_member WHERE eval_no = :n AND member_no = :m',
                      n=no, m=body.member_no)
        if not member:
            raise AuthError(404, 'MEMBER_NOT_FOUND', '이 평가표의 참여 근로자가 아니에요.')
        done = rows(db, "SELECT sign_no FROM eval_sign WHERE eval_no = :n AND member_no = :m "
                        "AND sign_yn = 'Y' AND signer_type = 'WO'", n=no, m=body.member_no)
        if done:
            raise AuthError(409, 'ALREADY_SIGNED', '이미 서명했어요. 저장한 서명은 정정할 수 없어요.')
        t = now()
        execute(db, "INSERT INTO eval_sign (eval_no, member_no, signer_type, signer_nm, sign_img, confirm_yn, "
                    "sign_yn, sign_dt, ins_dt, ins_nm) VALUES (:n, :m, 'WO', :nm, :img, 'Y', 'Y', :t, :t, :e)",
                n=no, m=body.member_no, nm=member[0]['member_nm'], img=body.sign_img, t=t, e=email)
        if all(r['sign_dt'] is not None for r in _members(db, no)):
            execute(db, "UPDATE eval_mst SET sign_end_dt = :t, "
                        "eval_status = CASE WHEN eval_status = 'C' THEN 'S' ELSE eval_status END, "
                        "upt_dt = :t, upt_nm = :e WHERE eval_no = :n AND sign_end_dt IS NULL", n=no, t=t, e=email)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return summary(db, email, no)
