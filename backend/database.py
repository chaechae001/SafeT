"""MariaDB 연결 (SQLAlchemy + PyMySQL)

접속 정보는 backend/.env 에서 읽습니다. 비밀번호를 코드나 로그에 남기지 않습니다.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import sessionmaker

# backend/.env 를 읽음 (이미 설정된 OS 환경변수가 있으면 그 값을 우선)
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


def _db_url() -> URL:
    missing = [k for k in ("DB_HOST", "DB_NAME", "DB_USER") if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"backend/.env 에 값이 없습니다: {', '.join(missing)}")
    return URL.create(
        drivername="mysql+pymysql",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD") or None,   # URL.create 가 특수문자를 안전하게 처리
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME"),
        query={"charset": "utf8mb4"},
    )


engine: Engine = create_engine(
    _db_url(),
    pool_pre_ping=True,     # 끊긴 연결을 사용 전에 확인
    pool_recycle=3600,      # 오래된 연결 교체 (MariaDB wait_timeout 대비)
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI 의존성: 요청마다 세션을 열고 끝나면 닫습니다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ping() -> dict:
    """연결 확인: 서버 버전, 현재 DB, 테이블 목록"""
    with engine.connect() as conn:
        version = conn.execute(text("SELECT VERSION()")).scalar()
        current = conn.execute(text("SELECT DATABASE()")).scalar()
        tables = [r[0] for r in conn.execute(text("SHOW TABLES"))]
    return {"version": version, "database": current, "tables": sorted(tables)}
