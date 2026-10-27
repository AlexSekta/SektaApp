import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote


RESET_TOKEN_MINUTES = 30


def _smtp_config():
    host = (os.getenv("SMTP_HOST") or "").strip()
    port = int((os.getenv("SMTP_PORT") or "587").strip())
    user = (os.getenv("SMTP_USER") or "").strip()
    password = os.getenv("SMTP_PASSWORD") or ""
    sender = (os.getenv("SMTP_FROM") or user).strip()
    frontend_url = (
        os.getenv("FRONTEND_URL")
        or "http://localhost:5173"
    ).strip().rstrip("/")

    if not host:
        raise RuntimeError(
            "Восстановление пароля не настроено: отсутствует SMTP_HOST."
        )
    if not sender:
        raise RuntimeError(
            "Восстановление пароля не настроено: отсутствует SMTP_FROM."
        )

    return host, port, user, password, sender, frontend_url


def validate_password_reset_email_config() -> None:
    _smtp_config()


def send_password_reset_email(
    email: str,
    user_name: str,
    token: str,
) -> None:
    host, port, user, password, sender, frontend_url = _smtp_config()

    reset_url = (
        f"{frontend_url}/reset-password"
        f"?token={quote(token)}"
    )

    message = EmailMessage()
    message["Subject"] = "Восстановление пароля — Marketplace Analytics"
    message["From"] = sender
    message["To"] = email

    message.set_content(
        f"""Здравствуйте, {user_name}!

Мы получили запрос на восстановление пароля для вашего аккаунта.

Чтобы задать новый пароль, откройте ссылку:
{reset_url}

Ссылка действительна {RESET_TOKEN_MINUTES} минут и может быть использована только один раз.

Если вы не запрашивали восстановление пароля, просто проигнорируйте это письмо.

Marketplace Analytics
"""
    )

    context = ssl.create_default_context()

    if port == 465:
        with smtplib.SMTP_SSL(
            host,
            port,
            timeout=20,
            context=context,
        ) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(
        host,
        port,
        timeout=20,
    ) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        if user:
            smtp.login(user, password)
        smtp.send_message(message)
