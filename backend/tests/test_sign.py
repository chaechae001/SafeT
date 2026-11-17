"""참여자 서명 API 테스트 (SIGN · 화면설계서 29쪽)

실행 (backend 폴더에서, 테스트용 DB 또는 ALLOW_DB_TESTS=1): .venv\\Scripts\\python -m pytest tests/test_sign.py -q
"""
import base64
import uuid

import pytest
from sqlalchemy import text

from conftest import db_one, engine, purge_user_rows
from test_workplaces import make_login

# 1×1 흰색 PNG 를 크게 만든 가짜 서명 (100바이트 이상)
PNG = "data:image/png;base64," + base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 120).decode()


@pytest.fixture
def setup(client, email, biz_code, machines):
    """로그인 + 사업장 1곳 + 확정 평가표(참여자 2명) + 작성 중 평가표(참여자 1명)"""
    auth = make_login(client, email)
    w = client.post("/workplaces", json={"workplace": "성수점", "biz_code": biz_code}, headers=auth).json()["work_no"]
    ids, members = {}, {}
    with engine.begin() as c:
        for name, st in (("확정", "C"), ("작성중", "W")):
            r = c.execute(text("INSERT INTO eval_mst (work_no, email, eval_nm, eval_dt, eval_status, del_yn) "
                               "VALUES (:w, :e, :n, '2026-11-14 10:00:00', :s, 'N')"), {"w": w, "e": email, "n": name, "s": st})
            ids[name] = r.lastrowid
        for i, nm in enumerate(["이민호", "박지수"]):
            members[nm] = c.execute(text("INSERT INTO eval_member (eval_no, member_nm, sort) VALUES (:e, :n, :s)"),
                                    {"e": ids["확정"], "n": nm, "s": i}).lastrowid
        members["작성중참여"] = c.execute(text("INSERT INTO eval_member (eval_no, member_nm, sort) VALUES (:e, '정유진', 0)"),
                                       {"e": ids["작성중"]}).lastrowid
    return {"auth": auth, "ids": ids, "members": members}


def sign(client, setup, member, **over):
    body = {"member_no": setup["members"][member], "confirm": True, "sign_img": PNG, **over}
    return client.post(f"/evals/{setup['ids']['확정']}/signs", json=body, headers=setup["auth"])


def test_로그인_없으면_401(client):
    assert client.get("/evals/1/signs").status_code == 401


def test_서명_현황_처음엔_모두_서명필요(client, setup):
    r = client.get(f"/evals/{setup['ids']['확정']}/signs", headers=setup["auth"])
    body = r.json()
    assert r.status_code == 200 and (body["member_count"], body["signed_count"]) == (2, 0)
    assert [m["member_nm"] for m in body["members"]] == ["이민호", "박지수"]
    assert all(not m["signed"] and "sign_img" not in m for m in body["members"])


def test_작성중_평가표는_서명_불가(client, setup):
    no = setup["ids"]["작성중"]
    assert client.get(f"/evals/{no}/signs", headers=setup["auth"]).json()["detail"]["code"] == "EVAL_NOT_CONFIRMED"
    r = client.post(f"/evals/{no}/signs", headers=setup["auth"],
                    json={"member_no": setup["members"]["작성중참여"], "confirm": True, "sign_img": PNG})
    assert r.status_code == 409


def test_서명_저장_후_정정_불가(client, setup):
    r = sign(client, setup, "이민호")
    assert r.status_code == 201 and r.json()["signed_count"] == 1
    assert sign(client, setup, "이민호").json()["detail"]["code"] == "ALREADY_SIGNED"
    row = db_one("SELECT signer_type, signer_nm, confirm_yn, sign_yn, sign_img, sign_dt FROM eval_sign WHERE member_no = :m",
                 m=setup["members"]["이민호"])
    assert (row["signer_type"], row["signer_nm"], row["confirm_yn"], row["sign_yn"]) == ("WO", "이민호", "Y", "Y")
    assert row["sign_img"] == PNG and row["sign_dt"] is not None
    m = db_one("SELECT eval_status, sign_end_dt FROM eval_mst WHERE eval_no = :n", n=setup["ids"]["확정"])
    assert m["eval_status"] == "C" and m["sign_end_dt"] is None                     # 아직 1/2


def test_전원_서명하면_서명완료(client, setup):
    sign(client, setup, "이민호")
    body = sign(client, setup, "박지수").json()
    assert (body["signed_count"], body["eval_status"]) == (2, "S") and body["sign_end_dt"]
    item = client.get("/evals", params={"tab": "S", "start": "2026-11-01", "end": "2026-11-30"},
                      headers=setup["auth"]).json()["items"][0]
    assert item["eval_nm"] == "확정" and (item["member_count"], item["signed_count"]) == (2, 2)


def test_입력_검사(client, setup):
    assert sign(client, setup, "이민호", confirm=False).status_code == 422          # 확인 체크 필수
    assert sign(client, setup, "이민호", sign_img="data:image/jpeg;base64,AAAA").status_code == 422
    assert sign(client, setup, "이민호", sign_img="https://example.invalid/a.png").status_code == 422
    other = sign(client, setup, "이민호", member_no=setup["members"]["작성중참여"])  # 다른 평가표의 참여자
    assert other.status_code == 404 and other.json()["detail"]["code"] == "MEMBER_NOT_FOUND"


def test_남의_평가표는_404(client, setup):
    other = f"o{uuid.uuid4().hex[:10]}@test.invalid"
    h = make_login(client, other)
    try:
        assert client.get(f"/evals/{setup['ids']['확정']}/signs", headers=h).status_code == 404
        r = client.post(f"/evals/{setup['ids']['확정']}/signs", headers=h,
                        json={"member_no": setup["members"]["이민호"], "confirm": True, "sign_img": PNG})
        assert r.status_code == 404
    finally:
        with engine.begin() as c:
            purge_user_rows(c, other)
