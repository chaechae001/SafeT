"""결과 공유 (SHARE · 화면설계서 30쪽)

- 참여자 전원이 서명한(sign_end_dt 있음) 확정 평가표에서만 링크를 만듦
- 평가표당 쓸 수 있는 링크는 1개, 유효기간 7일. 공유 중지·재발급하면 이전 링크는 바로 막힘(stop_yn='Y')
- 받는 사람은 로그인 없이 링크로 평가표 정보를 보고 PDF(공유본)를 내려받음. 다운로드 횟수만 기록
  (열람·다운로드는 결과 확인이나 서명으로 기록하지 않음)
- 공유본 PDF 에는 서명 원본 이미지를 넣지 않음 (report_service.build_context(share=True))
- 링크 주소: .env SHARE_BASE_URL(받는 사람 화면 주소) + ?t=토큰. QR 은 같은 주소로 만듦(segno, SVG)
"""
import os
import secrets
from datetime import timedelta
from urllib.parse import quote

from services.assessment import execute, owned, rows
from services.auth import AuthError, now

SHARE_DAYS = 7
DEFAULT_BASE = "http://localhost:8000/pages/share-download.html"
EXPIRED = AuthError(410, "SHARE_EXPIRED", "링크가 만료되었어요. 보낸 분께 다시 요청해 주세요.")


def base_url() -> str:
    return (os.getenv("SHARE_BASE_URL") or DEFAULT_BASE).strip()


def share_url(token: str) -> str:
    return f"{base_url()}?t={quote(token)}"


def qr_svg(url: str) -> str:
    """QR 코드 SVG 문자열 (화면에 바로 넣음)"""
    import segno
    return segno.make(url, error="m").svg_inline(scale=8, border=2, dark="#1d2420", light="#ffffff")


def _shareable(db, email, no, lock=False):
    m = owned(db, email, no, lock)
    if m["eval_status"] not in ("C", "S", "A") or not m["sign_end_dt"]:
        raise AuthError(409, "SIGN_NOT_DONE", "참여자 전원이 서명한 평가표만 공유할 수 있어요.")
    return m


def _active(db, no):
    r = rows(db, "SELECT * FROM eval_share WHERE eval_no = :n AND COALESCE(stop_yn, 'N') = 'N' "
                 "AND expire_dt > :t ORDER BY share_no DESC LIMIT 1", n=no, t=now())
    return r[0] if r else None


def _stop_all(db, no, email, t):
    execute(db, "UPDATE eval_share SET stop_yn = 'Y', upt_dt = :t, upt_nm = :e "
                "WHERE eval_no = :n AND COALESCE(stop_yn, 'N') = 'N'", n=no, t=t, e=email)


def _create(db, m, email, t):
    """공유본 문서 기록(eval_report, 서명 이미지 미포함) + 새 링크"""
    from services.report_service import file_name
    name = file_name({"eval_nm": m["eval_nm"], "draft": False})
    rep = execute(db, "INSERT INTO eval_report (eval_no, file_nm, sign_yn, ins_dt, ins_nm) "
                      "VALUES (:n, :f, 'N', :t, :e)", n=m["eval_no"], f=name[:100], t=t, e=email).lastrowid
    token = secrets.token_urlsafe(18)                 # 24자, 추측 불가
    execute(db, "INSERT INTO eval_share (eval_no, report_no, share_token, expire_dt, stop_yn, download_cnt, ins_dt, ins_nm) "
                "VALUES (:n, :r, :tok, :x, 'N', 0, :t, :e)",
            n=m["eval_no"], r=rep, tok=token, x=t + timedelta(days=SHARE_DAYS), t=t, e=email)


def _last_status(db, no, share):
    """지금 링크 상태: active(사용 중) / none(만든 적 없음) / stopped(중지) / expired(7일 지남)
    화면은 none 일 때만 열면서 자동 발급하고, 중지·만료 뒤에는 '새 링크 발급' 버튼으로만 만듦"""
    if share:
        return "active"
    last = rows(db, "SELECT stop_yn FROM eval_share WHERE eval_no = :n ORDER BY share_no DESC LIMIT 1", n=no)
    if not last:
        return "none"
    return "stopped" if last[0]["stop_yn"] == "Y" else "expired"


def _view(db, m, share):
    items = rows(db, "SELECT COUNT(*) c FROM eval_dtl WHERE eval_no = :n", n=m["eval_no"])[0]["c"]
    out = dict(eval_no=m["eval_no"], eval_nm=m["eval_nm"], eval_status=m["eval_status"], item_count=items,
               sign_end_dt=m["sign_end_dt"], share=None, status=_last_status(db, m["eval_no"], share))
    if share:
        url = share_url(share["share_token"])
        out["share"] = dict(url=url, expire_dt=share["expire_dt"], download_cnt=share["download_cnt"] or 0,
                            qr_svg=qr_svg(url))
    return out


def get(db, email, no):
    m = _shareable(db, email, no)
    return _view(db, m, _active(db, no))


def issue(db, email, no, reissue=False):
    """링크가 없으면 만들고, 있으면 그대로 돌려줌. reissue=True 면 이전 링크를 막고 새로 만듦"""
    try:
        m = _shareable(db, email, no, lock=True)      # 같은 평가표 동시 발급 직렬화
        t = now()
        if reissue:
            _stop_all(db, no, email, t)
        if reissue or not _active(db, no):
            _create(db, m, email, t)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _view(db, m, _active(db, no))


def stop(db, email, no):
    try:
        m = _shareable(db, email, no, lock=True)
        _stop_all(db, no, email, now())
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _view(db, m, None)


# ---------- 받는 사람 (로그인 없음) ----------

def _by_token(db, token, lock=False):
    if not token or len(token) > 50:
        raise EXPIRED
    r = rows(db, "SELECT s.*, m.eval_nm, m.eval_dt, m.confirm_dt, m.eval_writer, m.eval_status, m.sign_end_dt, "
                 "       w.workplace, (SELECT COUNT(*) FROM eval_dtl d WHERE d.eval_no = m.eval_no) AS item_count "
                 "  FROM eval_share s JOIN eval_mst m ON m.eval_no = s.eval_no "
                 "  LEFT JOIN workplaces w ON w.work_no = m.work_no "
                 " WHERE s.share_token = :tok AND COALESCE(m.del_yn, 'N') = 'N'" + (" FOR UPDATE" if lock else ""),
             tok=token)
    # 없는 링크·중지·만료·확정 아님은 모두 같은 안내 (토큰 존재 여부를 알려주지 않음)
    if not r or r[0]["stop_yn"] == "Y" or not r[0]["expire_dt"] or r[0]["expire_dt"] <= now() \
            or r[0]["eval_status"] not in ("C", "S", "A"):
        raise EXPIRED
    return r[0]


def public_info(db, token):
    s = _by_token(db, token)
    from services.report_service import file_name
    return dict(eval_nm=s["eval_nm"], workplace=s["workplace"], eval_dt=s["eval_dt"], confirm_dt=s["confirm_dt"],
                eval_writer=s["eval_writer"], item_count=s["item_count"], expire_dt=s["expire_dt"],
                file_nm=file_name({"eval_nm": s["eval_nm"], "draft": False}))


def public_pdf(db, token, fetch):
    """공유본 PDF 를 만들고 다운로드 횟수 +1. PDF 생성에 실패하면 횟수를 올리지 않음"""
    from services import report_service as rs
    s = _by_token(db, token)
    ctx = rs.build_context(s["eval_no"], fetch, share=True)
    pdf = rs.render_pdf(ctx)
    try:
        execute(db, "UPDATE eval_share SET download_cnt = COALESCE(download_cnt, 0) + 1 WHERE share_no = :n",
                n=s["share_no"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return pdf, rs.file_name(ctx)
