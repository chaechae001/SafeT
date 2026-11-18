"""개인 개발 DB로 API와 화면 실행: python backend/run_local.py --demo --migrate."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parent.parent


def check_db(migrate):
    from sqlalchemy import inspect, text
    from database import engine
    from check_db import EXPECTED
    inspector = inspect(engine)
    missing = sorted(set(EXPECTED) - set(inspector.get_table_names()))
    if missing:
        raise RuntimeError('기본 ERD 테이블이 없습니다: ' + ', '.join(missing))
    if migrate:
        sql = (ROOT / 'backend/migrations/20261116_assessment_authoring.sql').read_text(encoding='utf-8')
        if os.getenv('SAFET_ASSESSMENT_MODE') in ('catalog_v1','catalog_ai_v1','authoring_rag_v1'):
            sql += '\n' + (ROOT / 'backend/migrations/20261117_catalog_risk.sql').read_text(encoding='utf-8')
        with engine.begin() as conn:
            for stmt in sql.split(';'):
                if stmt.strip():
                    conn.execute(text(stmt))
    inspector = inspect(engine)
    columns = {c['name'] for c in inspector.get_columns('eval_mst')}
    indexes = {i['name'] for i in inspector.get_indexes('eval_mst')}
    if not {'request_key', 'revision', 'generation_source'} <= columns or 'uq_eval_request' not in indexes:
        raise RuntimeError('평가표 추가 필드가 필요합니다. 개인 개발 DB를 확인한 뒤 --migrate로 실행하세요.')
    if os.getenv('SAFET_ASSESSMENT_MODE') in ('catalog_v1','catalog_ai_v1','authoring_rag_v1'):
        from services.catalog_risk import seed
        with engine.begin() as conn:
            from domain.risk_policy import POLICY
            count = seed(conn) if migrate else conn.execute(text('SELECT COUNT(*) FROM risk_catalog WHERE version=:v'),{'v':POLICY}).scalar()
            if not count: raise RuntimeError('DB 기준 데이터가 없습니다. --migrate를 실행하세요.')
    engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ai', action='store_true', help='SAM 탐지·텍스트 AI 후보와 공통 위험도 계산')
    parser.add_argument('--authoring-rag', action='store_true', help='입력 기반 평가와 검색 문헌 저장·표시')
    parser.add_argument('--catalog', action='store_true', help='Cloud 없이 DB 기준 위험성평가')
    parser.add_argument('--demo', action='store_true', help='합성 데이터로 저장·확정 흐름 시험')
    parser.add_argument('--migrate', action='store_true', help='기존 개발 DB에 추가 필드 SQL 적용')
    parser.add_argument('--check', action='store_true', help='DB와 설정만 검사하고 종료')
    args = parser.parse_args()
    children = []
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / 'backend/.env', override=False)
        if len(os.getenv('JWT_SECRET', '')) < 32:
            raise RuntimeError('backend/.env에 32자 이상의 JWT_SECRET을 설정하세요.')
        if sum((args.catalog,args.demo,args.ai,args.authoring_rag))>1: raise RuntimeError('평가 실행 모드는 하나만 선택하세요.')
        if args.catalog: os.environ['SAFET_ASSESSMENT_MODE']='catalog_v1'
        if args.demo: os.environ['SAFET_ASSESSMENT_MODE']='demo'
        if args.ai: os.environ['SAFET_ASSESSMENT_MODE']='catalog_ai_v1'
        if args.authoring_rag: os.environ['SAFET_ASSESSMENT_MODE']='authoring_rag_v1'
        if os.getenv('SAFET_ASSESSMENT_MODE') in ('catalog_ai_v1','authoring_rag_v1'):
            from services.catalog_ai import configuration
            configuration()
        check_db(args.migrate)
        print('DB 및 평가표 필드 확인 완료.', flush=True)
        if args.check:
            return 0
        for port in (8000, 8001):
            with socket.socket() as sock:
                try:
                    sock.bind(('127.0.0.1', port))
                except OSError:
                    raise RuntimeError(f'{port} 포트를 사용 중입니다. 기존 개발 서버를 종료한 뒤 실행하세요.') from None
        env = os.environ.copy()
        if args.demo:
            env['SAFET_ASSESSMENT_MODE'] = 'demo'
        children.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8001'], cwd=ROOT / 'backend', env=env))
        # 화면 서버: 캐시를 끈 개발용 서버 (고친 JS·CSS 가 바로 반영되도록 · dev_static_server.py)
        children.append(subprocess.Popen([sys.executable, str(ROOT / 'backend/dev_static_server.py'), '8000', '--bind', '127.0.0.1', '--directory', str(ROOT / 'frontend')], cwd=ROOT, env=env))
        opener = build_opener(ProxyHandler({}))
        for attempt in range(100):
            if any(p.poll() is not None for p in children):
                raise RuntimeError('서버 실행에 실패했습니다. 위 오류를 확인하세요.')
            try:
                with opener.open('http://127.0.0.1:8001/health/db', timeout=1), opener.open('http://127.0.0.1:8000/pages/login.html', timeout=1):
                    break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('서버 응답을 확인하지 못했습니다.')
        print('실행 완료: http://localhost:8000/pages/login.html', flush=True)
        print('API: http://localhost:8001/docs | 종료: Ctrl+C', flush=True)
        print('평가 모드: ' + ('입력 기반 평가 · 검색 문헌' if env.get('SAFET_ASSESSMENT_MODE') == 'authoring_rag_v1' else 'AI 후보 · 공통 기준 계산' if env.get('SAFET_ASSESSMENT_MODE') == 'catalog_ai_v1' else 'DB 기준 · Cloud 미사용' if env.get('SAFET_ASSESSMENT_MODE') == 'catalog_v1' else '개발용 합성 데이터' if env.get('SAFET_ASSESSMENT_MODE') == 'demo' else 'AI 미연결 · 판단 필요'), flush=True)
        while all(p.poll() is None for p in children):
            time.sleep(.5)
        raise RuntimeError('개발 서버가 종료되었습니다.')
    except KeyboardInterrupt:
        return 0
    except ImportError:
        print('패키지가 필요합니다: python -m pip install -r backend/requirements.txt', file=sys.stderr)
        return 1
    except Exception as exc:
        # 접속 URL·자격증명은 출력하지 않음.
        from services.auth import AuthError
        message = str(exc) if isinstance(exc, (RuntimeError, AuthError)) else f'{type(exc).__name__}: Docker DB 실행 상태와 backend/.env 설정을 확인하세요.'
        print(message, file=sys.stderr)
        return 1
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    sys.exit(main())
