"""개발용 메일 보관함 보기 (UX-001 · 2026-11-21)

GET /dev/outbox   SMTP 없이 보관한 인증 메일(최근 20개)을 HTML 표로 보여 줍니다.
- SAFET_DEV_MAIL_OUTBOX 가 설정된 경우에만 동작하고, 아니면 404 입니다.
- 이 PC(127.0.0.1·::1)에서 연 요청만 허용합니다. 운영 서버에서는 환경변수를 비워 둡니다.
"""
import html
import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from services import mailer

router = APIRouter(prefix="/dev", tags=["개발용"], include_in_schema=False)
LOCAL = {"127.0.0.1", "::1", "localhost"}


@router.get("/outbox", response_class=HTMLResponse)
def outbox(request: Request):
    folder = mailer.dev_outbox()
    if not folder or (request.client and request.client.host not in LOCAL):
        raise HTTPException(status_code=404)
    rows = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder), reverse=True)[:20]:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    rows.append(json.load(f))
            except (OSError, ValueError):
                continue
    purpose = {"signup": "회원가입", "reset": "비밀번호 재설정"}
    body = "".join(
        f"<tr><td>{html.escape(r.get('sent_at', ''))}</td><td>{html.escape(purpose.get(r.get('purpose'), r.get('purpose', '')))}</td>"
        f"<td>{html.escape(r.get('to', ''))}</td><td class='code'>{html.escape(r.get('code', ''))}</td>"
        f"<td>{int(r.get('expires_min', 0))}분</td></tr>"
        for r in rows
    ) or "<tr><td colspan='5'>아직 보관된 메일이 없어요. 화면에서 '인증 요청'을 눌러 주세요.</td></tr>"
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="5">
<title>개발용 메일 보관함 · Safe-T</title>
<style>body{{font-family:system-ui,'Malgun Gothic',sans-serif;margin:16px;color:#1d2420}}
h1{{font-size:20px}}p{{color:#5b645f}}table{{border-collapse:collapse;width:100%;font-size:15px}}
td,th{{border:1px solid #dde2dc;padding:8px;text-align:left}}th{{background:#eef0ea}}
.code{{font-size:22px;font-weight:800;letter-spacing:3px;color:#1f5a47}}</style></head><body>
<h1>개발용 메일 보관함</h1>
<p>SMTP 없이 시험할 때만 쓰는 화면입니다. 실제 메일은 보내지 않았어요. 5초마다 새로 고칩니다.</p>
<table><thead><tr><th>보낸 시각</th><th>용도</th><th>받는 사람</th><th>인증 코드</th><th>유효</th></tr></thead>
<tbody>{body}</tbody></table></body></html>"""
