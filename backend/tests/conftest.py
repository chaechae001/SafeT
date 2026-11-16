"""테스트 공통 설정

- backend/.env 의 MariaDB 에 테스트 데이터를 넣었다가 지웁니다.
  안전장치(2026-11-16): 아래 둘 중 하나일 때만 실행하고, 아니면 DB 에 손대지 않고 전부 건너뜁니다.
    · DB 이름이 _test 로 끝남 (예: DB_NAME=safeT_test)
    · .env 또는 환경변수에 ALLOW_DB_TESTS=1 (개인 로컬 DB 를 그대로 쓸 때)
  팀 공용·운영 DB 를 가리키는 .env 로는 실행하지 마세요.
- 연결이 안 되면 테스트를 건너뜁니다.
- 메일은 실제로 보내지 않고 가짜 발송 함수로 코드를 받습니다.
- 테스트용 이메일(@test.invalid)·업종(T로 시작)으로 만든 행은 테스트가 끝나면 지웁니다.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # backend 폴더

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from database import engine  # noqa: E402
from main import app  # noqa: E402
from routers.auth import get_mailer, get_reset_mailer  # noqa: E402


def db_tests_allowed() -> bool:
    """테스트용 DB 이거나 명시적으로 허락했을 때만 (database.py 가 .env 를 먼저 읽음)"""
    return os.getenv("DB_NAME", "").lower().endswith("_test") or os.getenv("ALLOW_DB_TESTS") == "1"


@pytest.fixture(scope="session", autouse=True)
def _db_available():
    if not db_tests_allowed():
        pytest.skip(
            f"테스트용 DB 가 아니라 DB 테스트를 건너뜁니다 (DB_NAME={os.getenv('DB_NAME', '')}). "
            "개인 로컬 DB 라면 backend/.env 에 ALLOW_DB_TESTS=1 을 넣거나, DB 이름을 _test 로 끝나게 하세요."
        )
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except SQLAlchemyError:
        pytest.skip("MariaDB 에 연결할 수 없어 DB 테스트를 건너뜁니다 (backend/.env 확인).")


class FakeMailer:
    def __init__(self):
        self.sent = []          # (받는 사람, 코드)
        self.fail = None        # 예외를 넣으면 발송 실패를 흉내

    def __call__(self, to, code, ttl):
        if self.fail:
            raise self.fail
        self.sent.append((to, code))

    def last_code(self, to):
        return [c for t, c in self.sent if t == to][-1]


@pytest.fixture
def mailer():
    m = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: m
    app.dependency_overrides[get_reset_mailer] = lambda: m
    yield m
    app.dependency_overrides.pop(get_mailer, None)
    app.dependency_overrides.pop(get_reset_mailer, None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def email():
    """테스트 전용 이메일. 끝나면 관련 행 삭제"""
    addr = f"t{uuid.uuid4().hex[:10]}@test.invalid"
    yield addr
    with engine.begin() as c:
        purge_user_rows(c, addr)


def purge_user_rows(c, addr):
    """테스트 이메일로 만든 평가표·사업장·사용자 행 삭제 (참조 순서대로)"""
    for t in ("eval_sign", "eval_member"):
        c.execute(text(f"DELETE FROM {t} WHERE eval_no IN (SELECT eval_no FROM eval_mst WHERE email = :e)"), {"e": addr})
    c.execute(text("DELETE FROM eval_mst WHERE email = :e"), {"e": addr})
    c.execute(text("DELETE FROM workplace_machine WHERE work_no IN (SELECT work_no FROM workplaces WHERE email = :e)"), {"e": addr})
    c.execute(text("DELETE FROM workplaces WHERE email = :e"), {"e": addr})     # user 를 참조하므로 먼저
    c.execute(text("DELETE FROM `user` WHERE email = :e"), {"e": addr})
    c.execute(text("DELETE FROM email_verifications WHERE email = :e"), {"e": addr})


@pytest.fixture
def biz_code():
    """테스트용 업종 (사업장 등록에 필요). 끝나면 삭제"""
    code = "T" + uuid.uuid4().hex[:8]
    with engine.begin() as c:
        c.execute(text("INSERT INTO biz_category (biz_code, biz_nm) VALUES (:b, '테스트 업종')"), {"b": code})
    yield code
    with engine.begin() as c:
        # 이 업종 사업장에 달린 평가표부터 (참조 순서)
        ev = "SELECT eval_no FROM eval_mst WHERE work_no IN (SELECT work_no FROM workplaces WHERE biz_code = :b)"
        c.execute(text(f"DELETE FROM eval_sign WHERE eval_no IN ({ev})"), {"b": code})
        c.execute(text(f"DELETE FROM eval_member WHERE eval_no IN ({ev})"), {"b": code})
        c.execute(text("DELETE FROM eval_mst WHERE work_no IN (SELECT work_no FROM workplaces WHERE biz_code = :b)"), {"b": code})
        c.execute(text("DELETE FROM workplace_machine WHERE work_no IN (SELECT work_no FROM workplaces WHERE biz_code = :b)"), {"b": code})
        c.execute(text("DELETE FROM workplaces WHERE biz_code = :b"), {"b": code})
        c.execute(text("DELETE FROM machine_category WHERE biz_code = :b"), {"b": code})
        c.execute(text("DELETE FROM biz_category WHERE biz_code = :b"), {"b": code})


@pytest.fixture
def machines(biz_code):
    """테스트 업종의 기기 3개 + 사용 안 함 1개 → {이름: 코드}"""
    names = ["튀김기", "가스레인지", "업소용 냉장고"]
    out = {}
    with engine.begin() as c:
        for i, n in enumerate(names + ["단종 기기"]):
            code = f"X{uuid.uuid4().hex[:8]}"
            c.execute(text("INSERT INTO machine_category (machine_code, biz_code, machine_nm, use_yn) VALUES (:m, :b, :n, :y)"),
                      {"m": code, "b": biz_code, "n": n, "y": "N" if n == "단종 기기" else "Y"})
            out[n] = code
    return out


def db_one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).mappings().first()


def db_exec(sql, **params):
    with engine.begin() as c:
        c.execute(text(sql), params)
