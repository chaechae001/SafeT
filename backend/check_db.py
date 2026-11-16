"""MariaDB 연결 확인 스크립트

실행 (저장소 루트에서):
    backend\\.venv\\Scripts\\python backend\\check_db.py

연결되면 서버 버전·DB 이름과, 테이블 정의서 V1.1 의 19개 테이블이 있는지 보여 줍니다.
데이터는 읽거나 바꾸지 않습니다(테이블 이름만 조회).
"""
import sys

from sqlalchemy.exc import SQLAlchemyError

# 테이블 정의서 V1.1 (Safe-T_ERD_V1.1 기준) 테이블 19개
EXPECTED = [
    "grp_code", "code_dtl", "user", "email_verifications", "biz_category",
    "workplaces", "workplace_machine", "machine_category", "job_category", "machine_job",
    "eval_mst", "eval_file", "eval_machine", "eval_dtl", "eval_action",
    "eval_member", "eval_sign", "eval_report", "eval_share",
]


def main() -> int:
    try:
        from database import ping
        info = ping()
    except RuntimeError as e:          # .env 값 누락
        print(f"[설정 오류] {e}")
        return 2
    except SQLAlchemyError as e:
        # 원인 메시지만 보여 줌 (접속 URL·비밀번호는 출력하지 않음)
        cause = getattr(e, "orig", e)
        print(f"[연결 실패] {type(cause).__name__}: {cause}")
        print("확인할 것: Docker 컨테이너 실행 여부, backend/.env 의 DB_PASSWORD·DB_NAME")
        return 1

    tables = {t.lower(): t for t in info["tables"]}
    missing = [t for t in EXPECTED if t not in tables]
    extra = [t for t in info["tables"] if t.lower() not in EXPECTED]

    print(f"[연결 성공] MariaDB {info['version']} · DB {info['database']}")
    print(f"테이블 {len(info['tables'])}개 · 정의서 기준 {len(EXPECTED) - len(missing)}/{len(EXPECTED)}개 있음")
    if missing:
        print("  없는 테이블:", ", ".join(missing))
    if extra:
        print("  정의서에 없는 테이블:", ", ".join(extra))
    return 0


if __name__ == "__main__":
    sys.exit(main())
