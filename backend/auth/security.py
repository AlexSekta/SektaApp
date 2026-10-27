import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from fastapi import HTTPException, Request, Response
from backend.models.auth import AuthSession, User

SESSION_COOKIE = "marketplace_session"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 600_000

def normalize_email(email: str) -> str:
    return email.strip().lower()

def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Пароль должен содержать минимум 8 символов")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (TypeError, ValueError):
        return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def create_session(db, user: User) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.utcnow()
    db.add(AuthSession(user_id=user.id, token_hash=token_hash(token), created_at=now,
                       expires_at=now + timedelta(days=SESSION_DAYS), last_activity_at=now))
    db.commit()
    return token

def set_session_cookie(response: Response, token: str):
    secure = os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true"
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400,
                        httponly=True, secure=secure, samesite="lax", path="/")

def clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")

def authenticate_request(db, request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.query(AuthSession).filter(
        AuthSession.token_hash == token_hash(token),
        AuthSession.revoked_at.is_(None),
    ).first()
    if not session:
        return None
    now = datetime.utcnow()
    if session.expires_at <= now:
        session.revoked_at = now
        db.commit()
        return None
    user = db.query(User).filter(User.id == session.user_id, User.is_active.is_(True)).first()
    if not user:
        return None
    request.state.user = user
    request.state.organization_id = user.organization_id
    session.last_activity_at = now
    db.commit()
    return user

def require_current_user(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Требуется авторизация")
    return user
