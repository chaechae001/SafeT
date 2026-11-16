"""메일 발송 (SMTP)

backend/.env 의 SMTP_* 값을 씁니다. Gmail 이면 계정 비밀번호가 아니라 '앱 비밀번호'를 넣습니다.
인증 코드는 메일 본문에만 넣고 로그에 남기지 않습니다.
"""
import os
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage


class MailConfigError(Exception):
    """SMTP 설정이 비어 있음"""


def configured() -> bool:
    return all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send_code(to: str, code: str, ttl: timedelta) -> None:
    """회원가입 인증 코드 메일 발송. 실패하면 예외를 그대로 올립니다."""
    if not configured():
        raise MailConfigError("SMTP 설정이 없습니다.")

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM") or user
    security = os.getenv("SMTP_SECURITY", "starttls").lower()   # starttls(587) | ssl(465)
    minutes = int(ttl.total_seconds() // 60)

    msg = EmailMessage()
    msg["Subject"] = "[Safe-T] 회원가입 인증 코드"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(
        f"Safe-T 회원가입 인증 코드입니다.\n\n"
        f"    {code}\n\n"
        f"{minutes}분 안에 회원가입 화면에 입력해 주세요.\n"
        f"본인이 요청하지 않았다면 이 메일을 무시해 주세요.\n"
    )

    context = ssl.create_default_context()
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, context=context, timeout=10) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.starttls(context=context)
            s.login(user, password)
            s.send_message(msg)
