"""내 평가표 목록 API 테스트 (H01)

실행 (backend 폴더에서): .venv\\Scripts\\python -m pytest -q
"""
import uuid

import pytest

from conftest import db_exec, db_one, engine, purge_user_rows
from test_workplaces import make_login


@pytest.fixture
def setup(client, email, biz_code, machines):
    """로그인 + 사업장 2곳(1곳은 삭제) + 평가표 여러 개"""
    auth = make_login(client, email)
    w1 = client.post("/workplaces", json={"workplace": "성수점", "biz_code": biz_code}, headers=auth).json()["work_no"]
    w2 = client.post("/workplaces", json={"workplace": "분식점", "biz_code": biz_code}, headers=auth).json()["work_no"]
    rows = [
        # (이름, 사업장, 평가일, 상태, 서명완료일, 삭제)
        ("작성중A", w1, "2026-11-10 09:00:00", "W", None, "N"),
        ("확정B",   w1, "2026-11-14 10:00:00", "C", None, "N"),
        ("서명C",   w2, "2026-11-03 10:00:00", "S", "2026-11-04 10:00:00", "N"),
        ("조치D",   w1, "2026-11-05 10:00:00", "A", "2026-11-06 10:00:00", "N"),
        ("지난달E", w1, "2026-10-14 10:00:00", "A", None, "N"),
        ("휴지통F", w1, "2026-11-11 10:00:00", "W", None, "Y"),
    ]
    ids = {}
    for name, w, dt, st, sign_end, deleted in rows:
        with engine.begin() as c:
            r = c.execute(__import__("sqlalchemy").text(
                "INSERT INTO eval_mst (work_no, email, eval_nm, eval_writer, eval_dt, eval_status, sign_end_dt, del_yn) "
                "VALUES (:w, :e, :n, '김하늘', :d, :s, :se, :dy)"),
                {"w": w, "e": email, "n": name, "d": dt, "s": st, "se": sign_end, "dy": deleted})
            ids[name] = r.lastrowid
    # 확정B: 참여자 3명 중 1명 서명
    for i, nm in enumerate(["이민호", "박지수", "정유진"]):
        db_exec("INSERT INTO eval_member (eval_no, member_nm, sort) VALUES (:e, :n, :s)", e=ids["확정B"], n=nm, s=i)
    first = db_one("SELECT MIN(member_no) m FROM eval_member WHERE eval_no = :e", e=ids["확정B"])["m"]
    db_exec("INSERT INTO eval_sign (eval_no, member_no, signer_type, signer_nm, sign_yn) VALUES (:e, :m, 'WO', '이민호', 'Y')", e=ids["확정B"], m=first)
    client.delete(f"/workplaces/{w2}", headers=auth)      # 분식점 삭제 → 평가표는 계속 보여야 함
    return {"auth": auth, "w1": w1, "w2": w2, "ids": ids}


def names(r):
    return [i["eval_nm"] for i in r.json()["items"]]


def get(client, setup, **q):
    q.setdefault("start", "2026-11-01")
    q.setdefault("end", "2026-11-16")
    return client.get("/evals", params={k: v for k, v in q.items() if v is not None}, headers=setup["auth"])


def test_로그인_없으면_401(client):
    assert client.get("/evals").status_code == 401


def test_탭별_목록_중복표시_최근순(client, setup):
    assert names(get(client, setup, tab="ALL")) == ["확정B", "작성중A", "조치D", "서명C"]  # 상태 무관, 휴지통 제외
    assert names(get(client, setup, tab="W")) == ["작성중A"]                       # 휴지통 제외
    assert names(get(client, setup, tab="C")) == ["확정B"]                          # UX-022: 서명 끝난 평가표는 확정 탭에 없음
    assert names(get(client, setup, tab="S")) == ["조치D", "서명C"]                 # 서명완료일 있음
    assert names(get(client, setup, tab="A")) == ["조치D"]                          # 기간 밖 '지난달E' 제외


def test_기간_종료일_포함과_검사(client, setup):
    assert names(get(client, setup, tab="C", start="2026-11-14", end="2026-11-14")) == ["확정B"]
    assert names(get(client, setup, tab="A", start="2026-10-01")) == ["조치D", "지난달E"]
    r = get(client, setup, tab="C", start="2026-11-20", end="2026-11-01")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_PERIOD"
    assert get(client, setup, tab="X").status_code == 400
    assert get(client, setup, tab="C", start="2026-13-01").status_code == 422


def test_사업장_선택_삭제한_사업장도_보임(client, setup):
    assert names(get(client, setup, tab="ALL", work_no=setup["w1"])) == ["확정B", "작성중A", "조치D"]
    r = get(client, setup, tab="S", work_no=setup["w2"])
    assert names(r) == ["서명C"] and r.json()["items"][0]["workplace"] == "분식점"


def test_카드_정보와_서명_현황(client, setup):
    item = get(client, setup, tab="C").json()["items"][0]
    assert item["eval_nm"] == "확정B" and item["workplace"] == "성수점" and item["eval_writer"] == "김하늘"
    assert item["eval_status"] == "C"
    assert (item["member_count"], item["signed_count"]) == (3, 1)                 # 서명하기 1/3


def test_남의_평가표는_안보임(client, setup):
    other = f"o{uuid.uuid4().hex[:10]}@test.invalid"
    h = make_login(client, other)
    try:
        assert client.get("/evals", params={"tab": "C"}, headers=h).json()["total"] == 0
        r = client.get("/evals", params={"tab": "C", "work_no": setup["w1"]}, headers=h)   # 남의 사업장 번호로도
        assert r.json()["total"] == 0
    finally:
        with engine.begin() as c:
            purge_user_rows(c, other)


def test_10개씩_나눠보기(client, setup, email):
    for i in range(11):
        db_exec("INSERT INTO eval_mst (work_no, email, eval_nm, eval_dt, eval_status, del_yn) VALUES (:w, :e, :n, '2026-11-02 10:00:00', 'W', 'N')",
                w=setup["w1"], e=email, n=f"추가{i:02d}")
    p1 = get(client, setup, tab="W").json()
    p2 = get(client, setup, tab="W", page=2).json()
    assert p1["total"] == 12 and len(p1["items"]) == 10 and len(p2["items"]) == 2
    assert p1["items"][0]["eval_nm"] == "작성중A"
