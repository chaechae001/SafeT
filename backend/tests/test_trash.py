"""평가표 삭제·휴지통 API 테스트 (H02 · C02 · 화면설계서 31쪽)

실행 (backend 폴더에서, 테스트용 DB 또는 ALLOW_DB_TESTS=1): .venv\\Scripts\\python -m pytest tests/test_trash.py -q
"""
import uuid

import pytest
from sqlalchemy import text

from conftest import db_exec, db_one, engine, purge_user_rows
from test_workplaces import make_login


@pytest.fixture
def setup(client, email, biz_code, machines):
    """로그인 + 작성 중 평가표(위험·조치·참여자·기기·입력 포함) + 확정 평가표"""
    auth = make_login(client, email)
    w = client.post("/workplaces", json={"workplace": "성수점", "biz_code": biz_code}, headers=auth).json()["work_no"]
    ids = {}
    with engine.begin() as c:
        for name, st in (("작성중", "W"), ("확정", "C")):
            ids[name] = c.execute(text("INSERT INTO eval_mst (work_no, email, eval_nm, eval_dt, eval_status, del_yn) "
                                       "VALUES (:w, :e, :n, '2026-11-14 10:00:00', :s, 'N')"),
                                  {"w": w, "e": email, "n": name, "s": st}).lastrowid
        no = ids["작성중"]
        d = c.execute(text("INSERT INTO eval_dtl (eval_no, job, risk_factor, curr_risk_grade, curr_none_yn, sort) "
                           "VALUES (:n, '튀김', '기름 튐', 'R', 'N', 0)"), {"n": no}).lastrowid
        c.execute(text("INSERT INTO eval_action (eval_dtl_no, action_type, action_text, check_yn, ai_yn, sort) "
                       "VALUES (:d, 'C', '집게', 'Y', 'Y', 0)"), {"d": d})
        c.execute(text("INSERT INTO eval_member (eval_no, member_nm, sort) VALUES (:n, '이민호', 0)"), {"n": no})
        c.execute(text("INSERT INTO eval_machine (eval_no, machine_nm, ai_yn, check_yn) VALUES (:n, '튀김기', 'N', 'Y')"), {"n": no})
        c.execute(text("INSERT INTO eval_file (eval_no, file_type, file_text) VALUES (:n, 'T', '현장 설명')"), {"n": no})
    yield {"auth": auth, "ids": ids}
    with engine.begin() as c:                         # 공통 정리에 없는 하위 행
        for n in ids.values():
            c.execute(text("DELETE FROM eval_action WHERE eval_dtl_no IN (SELECT eval_dtl_no FROM eval_dtl WHERE eval_no = :n)"), {"n": n})
            for t in ("eval_file", "eval_machine", "eval_dtl"):
                c.execute(text(f"DELETE FROM {t} WHERE eval_no = :n"), {"n": n})


def trash(client, setup):
    return client.get("/trash", headers=setup["auth"]).json()


def test_로그인_없으면_401(client):
    assert client.get("/trash").status_code == 401
    assert client.delete("/evals/1").status_code == 401


def test_작성중만_휴지통으로(client, setup):
    h, ids = setup["auth"], setup["ids"]
    r = client.delete(f"/evals/{ids['확정']}", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EVAL_LOCKED"   # 확정은 삭제 불가
    assert client.delete(f"/evals/{ids['작성중']}", headers=h).status_code == 204
    m = db_one("SELECT del_yn, del_dt FROM eval_mst WHERE eval_no = :n", n=ids["작성중"])
    assert m["del_yn"] == "Y" and m["del_dt"] is not None
    assert client.get(f"/evals/{ids['작성중']}", headers=h).status_code == 404        # 편집 화면에서 안 열림
    names = [i["eval_nm"] for i in client.get("/evals", params={"tab": "ALL"}, headers=h).json()["items"]]
    assert "작성중" not in names                                                       # 내 평가표 목록에서 빠짐
    items = trash(client, setup)["items"]
    assert [i["eval_nm"] for i in items] == ["작성중"] and items[0]["days_left"] == 30
    assert client.delete(f"/evals/{ids['작성중']}", headers=h).status_code == 404     # 이미 휴지통


def test_복원하면_입력_그대로_작성중(client, setup):
    h, no = setup["auth"], setup["ids"]["작성중"]
    client.delete(f"/evals/{no}", headers=h)
    r = client.post(f"/trash/{no}/restore", headers=h)
    assert r.status_code == 200 and r.json()["eval_nm"] == "작성중"
    assert r.json()["eval_dt"].startswith("2026-11-14") and r.json()["work_no"]      # 화면이 기간·사업장 맞추는 데 씀
    doc = client.get(f"/evals/{no}", headers=h).json()
    assert doc["eval_status"] == "W" and len(doc["items"]) == 1 and doc["members"] == ["이민호"]
    assert trash(client, setup)["items"] == []


def test_영구삭제는_딸린_행까지_지움(client, setup):
    h, no = setup["auth"], setup["ids"]["작성중"]
    assert client.delete(f"/trash/{no}", headers=h).status_code == 404               # 휴지통에 없으면 404
    client.delete(f"/evals/{no}", headers=h)
    assert client.delete(f"/trash/{no}", headers=h).status_code == 204
    assert db_one("SELECT COUNT(*) c FROM eval_mst WHERE eval_no = :n", n=no)["c"] == 0
    for t in ("eval_dtl", "eval_member", "eval_machine", "eval_file"):
        assert db_one(f"SELECT COUNT(*) c FROM {t} WHERE eval_no = :n", n=no)["c"] == 0
    assert client.post(f"/trash/{no}/restore", headers=h).status_code == 404         # 복원 불가


def test_30일_지나면_자동_영구삭제(client, setup):
    h, no = setup["auth"], setup["ids"]["작성중"]
    client.delete(f"/evals/{no}", headers=h)
    db_exec("UPDATE eval_mst SET del_dt = DATE_SUB(NOW(), INTERVAL 31 DAY) WHERE eval_no = :n", n=no)
    r = client.post(f"/trash/{no}/restore", headers=h)
    assert r.status_code == 410 and r.json()["detail"]["code"] == "TRASH_EXPIRED"
    assert db_one("SELECT COUNT(*) c FROM eval_mst WHERE eval_no = :n", n=no)["c"] == 0


def test_목록을_열면_지난_것_정리(client, setup):
    h, no = setup["auth"], setup["ids"]["작성중"]
    client.delete(f"/evals/{no}", headers=h)
    db_exec("UPDATE eval_mst SET del_dt = DATE_SUB(NOW(), INTERVAL 30 DAY) WHERE eval_no = :n", n=no)
    assert trash(client, setup)["items"] == []
    assert db_one("SELECT COUNT(*) c FROM eval_mst WHERE eval_no = :n", n=no)["c"] == 0


def test_남의_평가표는_404(client, setup):
    no = setup["ids"]["작성중"]
    other = f"o{uuid.uuid4().hex[:10]}@test.invalid"
    oh = make_login(client, other)
    try:
        assert client.delete(f"/evals/{no}", headers=oh).status_code == 404
        client.delete(f"/evals/{no}", headers=setup["auth"])
        assert client.post(f"/trash/{no}/restore", headers=oh).status_code == 404
        assert client.delete(f"/trash/{no}", headers=oh).status_code == 404
        assert client.get("/trash", headers=oh).json()["items"] == []
    finally:
        with engine.begin() as c:
            purge_user_rows(c, other)



def _race_setup(client, setup):
    """만료 경계의 휴지통 평가표 → (email, no, base). base 시각엔 아직 만료 전, base+2분엔 만료"""
    from datetime import timedelta

    from services import trash as service
    h, no = setup["auth"], setup["ids"]["작성중"]
    email = db_one("SELECT email FROM eval_mst WHERE eval_no = :n", n=no)["email"]
    client.delete(f"/evals/{no}", headers=h)
    base = service.now()
    db_exec("UPDATE eval_mst SET del_dt = :d WHERE eval_no = :n",
            d=base - timedelta(days=service.KEEP_DAYS) + timedelta(minutes=1), n=no)
    return email, no, base


def _list_trash(email, snapshot):
    """별도 DB 연결로 휴지통 목록 (이 연결만 innodb_snapshot_isolation 을 바꿨다가 되돌림)"""
    from database import SessionLocal
    from services import trash as service
    db = SessionLocal()
    try:
        db.execute(text(f"SET SESSION innodb_snapshot_isolation = {snapshot}"))
        db.commit()
        return service.list_trash(db, email)
    finally:
        db.rollback()
        db.execute(text("SET SESSION innodb_snapshot_isolation = DEFAULT"))   # 풀로 돌아가는 연결 원상복구
        db.commit()
        db.close()


def _restore(email, no):
    from database import SessionLocal
    from services import trash as service
    db = SessionLocal()
    try:
        return service.restore(db, email, no)
    finally:
        db.close()


def _exists(no):
    return db_one("SELECT COUNT(*) c FROM eval_mst WHERE eval_no = :n", n=no)["c"] == 1


# snapshot: MariaDB 11.6.2+ 기본 ON. OFF 는 이전 MariaDB·MySQL 동작.
# 수정 전 코드는 ON 이면 목록이 1020 오류, OFF 면 복원 성공한 평가표가 지워졌음.
@pytest.mark.parametrize("snapshot", ["ON", "OFF"])
def test_만료_경계_복원이_먼저면_자동삭제에서_빠짐(client, setup, monkeypatch, snapshot):
    from datetime import timedelta

    from services import trash as service
    email, no, base = _race_setup(client, setup)
    clock = {"t": base}
    monkeypatch.setattr(service, "now", lambda: clock["t"])
    assert _restore(email, no)["eval_no"] == no          # 복원: 아직 만료 전
    clock["t"] = base + timedelta(minutes=2)
    assert _list_trash(email, snapshot)["items"] == []   # 목록: 만료 시각 지남
    m = db_one("SELECT del_yn, del_dt FROM eval_mst WHERE eval_no = :n", n=no)
    assert m["del_yn"] == "N" and m["del_dt"] is None
    for t in ("eval_dtl", "eval_member", "eval_machine", "eval_file"):
        assert db_one(f"SELECT COUNT(*) c FROM {t} WHERE eval_no = :n", n=no)["c"] == 1, t


@pytest.mark.parametrize("snapshot", ["ON", "OFF"])
def test_만료_경계_자동삭제가_먼저면_복원은_404(client, setup, monkeypatch, snapshot):
    """목록이 만료 대상을 고른 직후 복원 요청이 들어옴 → 복원은 잠금을 기다렸다가 404, 성공 응답 없음"""
    import threading
    from datetime import timedelta

    from services import trash as service
    from services.auth import AuthError
    email, no, base = _race_setup(client, setup)
    clock = {"t": base + timedelta(minutes=2)}           # 목록: 만료 시각 지남
    monkeypatch.setattr(service, "now", lambda: clock["t"])
    real_rows, result = service.rows, {}

    def run_restore():
        try:
            result["ok"] = _restore(email, no)
        except AuthError as e:
            result["err"] = e

    def rows_then_restore(db, sql, **p):
        out = real_rows(db, sql, **p)
        if "thread" not in result and "del_dt <= :limit" in sql:   # 만료 대상을 고른 직후 끼어들기
            clock["t"] = base                                       # 복원: 아직 만료 전
            result["thread"] = threading.Thread(target=run_restore)
            result["thread"].start()
            result["thread"].join(timeout=1)                         # 잠금이 없으면 이 안에 끝남
            assert result["thread"].is_alive(), f"복원 요청이 잠금을 기다리지 않음: {result}"
        return out

    monkeypatch.setattr(service, "rows", rows_then_restore)
    assert _list_trash(email, snapshot)["items"] == []
    result["thread"].join(timeout=30)
    assert "ok" not in result                                       # 복원 성공 응답이 나가지 않음
    assert result["err"].status == 404 and not _exists(no)
