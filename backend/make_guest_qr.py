"""시연용 게스트 로그인 QR 만들기 (UX-001 · 2026-11-21)

backend/.env 의 SAFET_GUEST_KEY 로 'login.html#g=<키>' 주소의 QR 그림을 만듭니다.
QR 을 찍으면 게스트 계정으로 자동 로그인됩니다(POST /auth/guest).

사용 (저장소 루트):
    backend\\.venv\\Scripts\\python backend/make_guest_qr.py --base http://localhost:8000/pages/login.html
    backend\\.venv\\Scripts\\python backend/make_guest_qr.py --base https://<배포 주소>/pages/login.html --out guest-qr.png

- 키가 들어 있는 QR 그림과 주소는 공유 범위를 정해 다루고 저장소에 올리지 않습니다(기본 저장 위치 backend/.venv/).
- 키를 바꾸면(SAFET_GUEST_KEY 새 값 + API 재시작) 이전 QR 은 더 이상 동작하지 않습니다.
- 키 만들기: backend\\.venv\\Scripts\\python -c "import secrets; print(secrets.token_urlsafe(32))"
"""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    from dotenv import load_dotenv
    import segno

    load_dotenv(HERE / ".env", override=False)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True, help="login.html 전체 주소")
    p.add_argument("--out", default=str(HERE / ".venv" / "guest-qr.png"), help="저장할 그림(.png 또는 .svg)")
    a = p.parse_args()
    key = os.getenv("SAFET_GUEST_KEY", "")
    if len(key) < 24:
        print("backend/.env 에 24자 이상의 SAFET_GUEST_KEY 를 설정하세요.", file=sys.stderr)
        return 1
    if not a.base.split("#")[0].endswith("login.html"):
        print("--base 는 .../pages/login.html 주소여야 합니다.", file=sys.stderr)
        return 1
    url = a.base.split("#")[0] + "#g=" + key
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    segno.make(url, error="m").save(str(out), scale=10, border=2)
    print(f"QR 저장: {out}  (주소: {a.base.split('#')[0]}#g=<키 생략>)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
