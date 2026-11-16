"""사업장 API 테스트 (B01 · B02 · B02-E)

실행 (backend 폴더에서): .venv\\Scripts\\python -m pytest -q
"""
import uuid

import bcrypt
import pytest

from conftest import db_exec, db_one


def make_login(client, email):
    db_exec("INSERT INTO `user` (email, pw, name) VALUES (:e, :p, '테스트')",
            e=email, p=bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode())
    token = client.post("/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth(client, email):
    return make_login(client, email)


@pytest.fixture
def other(client):
    """다른 사용자 (남의 사업장 접근 확인용)"""
    addr = f"o{uuid.uuid4().hex[:10]}@test.invalid"
    h = make_login(client, addr)
    yield addr, h
    from conftest import engine, purge_user_rows
    with engine.begin() as c:
        purge_user_rows(c, addr)


def create(client, auth, biz_code, machines, name="온기치킨 성수점", codes=None, custom=None):
    body = {"workplace": name, "biz_code": biz_code,
            "machine_codes": codes if codes is not None else [machines["튀김기"]],
            "custom_machines": custom or []}
    return client.post("/workplaces", json=body, headers=auth)


# ---------- 로그인 필요 ----------
def test_로그인_없으면_401(client):
    assert client.get("/workplaces").status_code == 401
    assert client.get("/biz-categories").status_code == 401


# ---------- 업종·기기 ----------
def test_업종과_업종별_기기(client, auth, biz_code, machines):
    bizs = client.get("/biz-categories", headers=auth).json()
    assert {"biz_code": biz_code, "biz_nm": "테스트 업종"} in bizs
    ms = client.get(f"/biz-categories/{biz_code}/machines", headers=auth).json()
    names = [m["machine_nm"] for m in ms]
    assert set(names) == {"튀김기", "가스레인지", "업소용 냉장고"}          # 사용 안 함 기기 제외
    assert client.get("/biz-categories/NOPE/machines", headers=auth).status_code == 404


# ---------- 등록 ----------
def test_등록_기기와_직접추가(client, auth, email, biz_code, machines):
    r = create(client, auth, biz_code, machines,
               codes=[machines["튀김기"], machines["튀김기"]],                 # 중복 체크는 하나로
               custom=["  반죽기 ", "반죽기", "가스레인지", ""])              # 공백 정리·중복 합침·목록 이름은 그 기기로
    assert r.status_code == 201, r.text
    no = r.json()["work_no"]
    row = db_one("SELECT email, workplace, biz_code, use_yn FROM workplaces WHERE work_no = :w", w=no)
    assert row["email"] == email and row["use_yn"] == "Y"
    got = client.get(f"/workplaces/{no}", headers=auth).json()
    pairs = {(m["machine_code"], m["machine_nm"], m["custom"]) for m in got["machines"]}
    assert pairs == {(machines["튀김기"], "튀김기", False), (machines["가스레인지"], "가스레인지", False), (None, "반죽기", True)}
    assert got["biz_nm"] == "테스트 업종" and got["draft_count"] == 0


def test_기기없이도_등록(client, auth, biz_code, machines):
    assert create(client, auth, biz_code, machines, codes=[]).status_code == 201


def test_로그인하면_사업장있음(client, auth, email, biz_code, machines):
    create(client, auth, biz_code, machines)
    assert client.get("/auth/me", headers=auth).json()["has_workplace"] is True


def test_다른업종_기기나_사용안함_기기는_거부(client, auth, biz_code, machines):
    r = create(client, auth, biz_code, machines, codes=[machines["단종 기기"]])
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_MACHINE"
    r = create(client, auth, biz_code, machines, codes=["ZZZ_NONE"])
    assert r.status_code == 400


def test_입력형식(client, auth, biz_code, machines):
    assert create(client, auth, biz_code, machines, name="   ").status_code == 422
    assert create(client, auth, biz_code, machines, name="가" * 51).status_code == 422
    assert create(client, auth, biz_code, machines, custom=["가" * 51]).status_code == 422
    r = client.post("/workplaces", json={"workplace": "매장", "biz_code": "NOPE"}, headers=auth)
    assert r.status_code == 404


# ---------- 목록·수정·삭제 ----------
def test_목록은_내것_사용중만(client, auth, other, biz_code, machines):
    a = create(client, auth, biz_code, machines, name="A 매장").json()["work_no"]
    b = create(client, auth, biz_code, machines, name="B 매장").json()["work_no"]
    create(client, other[1], biz_code, machines, name="남의 매장")
    client.delete(f"/workplaces/{b}", headers=auth)
    lst = client.get("/workplaces", headers=auth).json()
    assert [w["work_no"] for w in lst] == [a]
    assert lst[0]["machines"][0]["machine_nm"] == "튀김기"


def test_수정_이름과_기기만_업종은_그대로(client, auth, biz_code, machines):
    no = create(client, auth, biz_code, machines, custom=["반죽기"]).json()["work_no"]
    r = client.put(f"/workplaces/{no}", headers=auth, json={
        "workplace": "  새 이름  ", "machine_codes": [machines["업소용 냉장고"]], "custom_machines": ["포장 실링기"],
        "biz_code": "OTHER"})                                             # 업종은 보내도 바뀌지 않음
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workplace"] == "새 이름" and body["biz_code"] == biz_code
    assert {m["machine_nm"] for m in body["machines"]} == {"업소용 냉장고", "포장 실링기"}


def test_삭제는_사용안함_데이터는_남음(client, auth, biz_code, machines):
    no = create(client, auth, biz_code, machines).json()["work_no"]
    assert client.delete(f"/workplaces/{no}", headers=auth).status_code == 204
    row = db_one("SELECT use_yn FROM workplaces WHERE work_no = :w", w=no)
    assert row["use_yn"] == "N"                                            # 지우지 않음
    assert db_one("SELECT COUNT(*) n FROM workplace_machine WHERE work_no = :w", w=no)["n"] == 1
    assert client.get(f"/workplaces/{no}", headers=auth).status_code == 404
    assert client.delete(f"/workplaces/{no}", headers=auth).status_code == 404
    assert client.get("/auth/me", headers=auth).json()["has_workplace"] is False


def test_남의_사업장은_조회_수정_삭제_불가(client, auth, other, biz_code, machines):
    no = create(client, other[1], biz_code, machines, name="남의 매장").json()["work_no"]
    assert client.get(f"/workplaces/{no}", headers=auth).status_code == 404
    assert client.put(f"/workplaces/{no}", headers=auth, json={"workplace": "x"}).status_code == 404
    assert client.delete(f"/workplaces/{no}", headers=auth).status_code == 404
    assert db_one("SELECT workplace, use_yn FROM workplaces WHERE work_no = :w", w=no) == {"workplace": "남의 매장", "use_yn": "Y"}


def test_작성중_평가표_수(client, auth, email, biz_code, machines):
    no = create(client, auth, biz_code, machines).json()["work_no"]
    db_exec("INSERT INTO eval_mst (work_no, email, eval_nm, eval_status, del_yn) VALUES (:w, :e, '작성 중', 'W', 'N'), (:w, :e, '확정', 'C', 'N'), (:w, :e, '휴지통', 'W', 'Y')", w=no, e=email)
    try:
        assert client.get(f"/workplaces/{no}", headers=auth).json()["draft_count"] == 1
    finally:
        db_exec("DELETE FROM eval_mst WHERE work_no = :w", w=no)
