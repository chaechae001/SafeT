"""결과 공유 API 테스트 (SHARE · 화면설계서 30쪽)

실행 (backend 폴더에서, 테스트용 DB 또는 ALLOW_DB_TESTS=1): .venv\\Scripts\\python -m pytest tests/test_share.py -q
"""
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text

from conftest import db_exec, db_one, engine, purge_user_rows
from test_workplaces import make_login


@pytest.fixture
def setup(client, email, biz_code, machines):
    """로그인 + 서명 완료 평가표(위험 1건·참여자 1명) + 서명 전 확정 평가표"""
    auth = make_login(client, email)
    w = client.post("/workplaces", json={"workplace": "성수점", "biz_code": biz_code}, headers=auth).json()["work_no"]
    ids = {}
    with engine.begin() as c:
        for name, st, end in (("서명완료", "S", "2026-11-15 10:00:00"), ("서명전", "C", None)):
            ids[name] = c.execute(text(
                "INSERT INTO eval_mst (work_no, email, eval_nm, eval_writer, eval_dt, confirm_dt, eval_status, sign_end_dt, del_yn) "
                "VALUES (:w, :e, :n, '김하늘', '2026-11-14 10:00:00', '2026-11-14 12:00:00', :s, :se, 'N')"),
                {"w": w, "e": email, "n": name, "s": st, "se": end}).lastrowid
        no = ids["서명완료"]
        c.execute(text("INSERT INTO eval_dtl (eval_no, job, risk_factor, risk_type, curr_risk_grade, curr_none_yn, sort) "
                       "VALUES (:n, '튀김', '기름 튐', '화상', 'R', 'N', 0)"), {"n": no})
        m = c.execute(text("INSERT INTO eval_member (eval_no, member_nm, sort) VALUES (:n, '이민호', 0)"), {"n": no}).lastrowid
        c.execute(text("INSERT INTO eval_sign (eval_no, member_no, signer_type, signer_nm, sign_img, confirm_yn, sign_yn, sign_dt) "
                       "VALUES (:n, :m, 'WO', '이민호', 'data:image/png;base64,SECRET', 'Y', 'Y', '2026-11-15 10:00:00')"),
                  {"n": no, "m": m})
    yield {"auth": auth, "ids": ids}
    with engine.begin() as c:           # eval_dtl 은 공통 정리 대상이 아니라 여기서 지움
        c.execute(text("DELETE FROM eval_dtl WHERE eval_no IN (:a, :b)"), {"a": ids["서명완료"], "b": ids["서명전"]})


def token_of(res):
    return parse_qs(urlparse(res.json()["share"]["url"]).query)["t"][0]


def test_로그인_없으면_401(client):
    assert client.post("/evals/1/share").status_code == 401


def test_전원_서명_전에는_공유_불가(client, setup):
    r = client.post(f"/evals/{setup['ids']['서명전']}/share", headers=setup["auth"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SIGN_NOT_DONE"


def test_링크는_평가표당_1개_7일(client, setup):
    no = setup["ids"]["서명완료"]
    assert client.get(f"/evals/{no}/share", headers=setup["auth"]).json()["share"] is None
    a = client.post(f"/evals/{no}/share", headers=setup["auth"])
    b = client.post(f"/evals/{no}/share", headers=setup["auth"])
    assert a.status_code == 200 and token_of(a) == token_of(b)                     # 다시 눌러도 같은 링크
    body = a.json()
    assert body["item_count"] == 1 and body["share"]["qr_svg"].startswith("<svg")
    row = db_one("SELECT COUNT(*) c, MAX(DATEDIFF(expire_dt, ins_dt)) d FROM eval_share WHERE eval_no = :n", n=no)
    assert (row["c"], row["d"]) == (1, 7)
    rep = db_one("SELECT r.sign_yn FROM eval_share s JOIN eval_report r ON r.report_no = s.report_no WHERE s.eval_no = :n", n=no)
    assert rep["sign_yn"] == "N"                                                   # 공유본: 서명 이미지 미포함


def test_받는_사람_정보와_PDF_다운로드_횟수(client, setup):
    tok = token_of(client.post(f"/evals/{setup['ids']['서명완료']}/share", headers=setup["auth"]))
    info = client.get(f"/share/{tok}")                                             # 로그인 없음
    assert info.status_code == 200
    assert (info.json()["eval_nm"], info.json()["workplace"], info.json()["item_count"]) == ("서명완료", "성수점", 1)
    pdf = client.get(f"/share/{tok}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert db_one("SELECT download_cnt FROM eval_share WHERE share_token = :t", t=tok)["download_cnt"] == 1


def test_공유본에는_서명_원본_없음():
    from services import report_service as rs

    def fetch(sql, p):
        if "FROM eval_mst" in sql:
            return [dict(workplace="a", biz_nm="b", eval_nm="c", eval_writer="d", eval_dt=None, confirm_dt=None,
                         sign_end_dt=None, eval_status="S", generation_source="demo")]
        if "FROM eval_member" in sql:
            return [dict(member_no=1, member_nm="이민호")]
        if "FROM eval_sign" in sql:
            return [dict(member_no=1, sign_img="data:image/png;base64,SECRET", confirm_yn="Y", sign_dt=None)]
        return []
    ctx = rs.build_context(1, fetch, share=True)
    assert ctx["signs"][0]["img"] is None and ctx["signs"][0]["signed"]
    assert "SECRET" not in rs.render_html(ctx) and "서명 완료" in rs.render_html(ctx)


def test_재발급하면_이전_링크_막힘(client, setup):
    no = setup["ids"]["서명완료"]
    old = token_of(client.post(f"/evals/{no}/share", headers=setup["auth"]))
    new = token_of(client.post(f"/evals/{no}/share/reissue", headers=setup["auth"]))
    assert old != new
    r = client.get(f"/share/{old}")
    assert r.status_code == 410 and r.json()["detail"]["code"] == "SHARE_EXPIRED"
    assert client.get(f"/share/{old}/pdf").status_code == 410
    assert client.get(f"/share/{new}").status_code == 200


def test_공유_중지와_만료(client, setup):
    no = setup["ids"]["서명완료"]
    tok = token_of(client.post(f"/evals/{no}/share", headers=setup["auth"]))
    assert client.post(f"/evals/{no}/share/stop", headers=setup["auth"]).json()["share"] is None
    assert client.get(f"/share/{tok}").status_code == 410
    tok2 = token_of(client.post(f"/evals/{no}/share", headers=setup["auth"]))   # 다시 발급
    db_exec("UPDATE eval_share SET expire_dt = '2020-01-01 00:00:00' WHERE share_token = :t", t=tok2)
    assert client.get(f"/share/{tok2}").status_code == 410                        # 7일 지남
    assert client.get("/share/없는토큰").status_code == 410                         # 없는 링크도 같은 안내


def test_남의_평가표는_404(client, setup):
    other = f"o{uuid.uuid4().hex[:10]}@test.invalid"
    h = make_login(client, other)
    try:
        assert client.post(f"/evals/{setup['ids']['서명완료']}/share", headers=h).status_code == 404
    finally:
        with engine.begin() as c:
            purge_user_rows(c, other)
