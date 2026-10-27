from datetime import datetime, timedelta
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from backend.dependencies import get_db
from backend.database import SessionLocal

def registration_db():
    # Public invitation lookup must not rely on a guessed tenant context.
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
from backend.auth.security import normalize_email, hash_password, verify_password, create_session, set_session_cookie, clear_session_cookie, token_hash, SESSION_COOKIE, require_current_user
from backend.models.auth import Organization, User, AuthSession, PasswordResetToken, OrganizationInvitation, UserAuditEvent
from backend.logging_config import get_logger
from backend.services.password_reset import (
    RESET_TOKEN_MINUTES,
    send_password_reset_email,
    validate_password_reset_email_config,
)

router = APIRouter(prefix="/auth", tags=["Авторизация"])
logger = get_logger("auth")

def _payload(user):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role,
            "organization_id": user.organization_id,
            "organization_name": user.organization.name if user.organization else None}

@router.get("/invitation/{raw_token}")
def invitation_details(raw_token: str, db: Session = Depends(registration_db)):
    i = db.query(OrganizationInvitation).filter(OrganizationInvitation.token_hash == token_hash(raw_token)).first()
    if not i or i.revoked_at or i.accepted_at or i.expires_at <= datetime.utcnow():
        raise HTTPException(404, "Приглашение недействительно или срок его действия истёк")
    return {"organization_name": i.organization.name, "email": i.email,
            "role": i.role, "expires_at": i.expires_at.isoformat()}

@router.post("/register")
def register(data: dict, response: Response, db: Session = Depends(registration_db)):
    first_name = str(data.get("first_name") or "").strip()
    last_name = str(data.get("last_name") or "").strip()
    name = " ".join((first_name, last_name)).strip() if (first_name or last_name) else str(data.get("name") or "").strip()
    if len(name) > 120: raise HTTPException(400, "Имя и фамилия слишком длинные")
    email = normalize_email(str(data.get("email") or ""))
    password = str(data.get("password") or "")
    organization_name = str(data.get("organization_name") or "").strip()
    if len(name) < 2: raise HTTPException(400, "Укажите имя")
    if "@" not in email or len(email) < 5: raise HTTPException(400, "Укажите корректный email")
    if len(password) < 8: raise HTTPException(400, "Пароль должен содержать минимум 8 символов")
    if db.query(User).filter(User.email == email).first(): raise HTTPException(409, "Пользователь с таким email уже зарегистрирован")
    raw_invite = str(data.get("invitation_token") or "").strip()
    invite = None
    if raw_invite:
        # Lock prevents two concurrent registrations from consuming one invitation.
        invite = db.query(OrganizationInvitation).filter(
            OrganizationInvitation.token_hash == token_hash(raw_invite)).with_for_update().first()
        if not invite or invite.accepted_at or invite.revoked_at or invite.expires_at <= datetime.utcnow():
            raise HTTPException(400, "Приглашение недействительно или истекло")
        if email != invite.email:
            raise HTTPException(400, "Для приглашения используйте указанный в нём email")
        org = invite.organization
        role = "MEMBER"
    else:
        if not organization_name:
            raise HTTPException(400, "Укажите название организации")
        org = Organization(name=organization_name)
        db.add(org)
        db.flush()
        role = "OWNER"
    user = User(organization_id=org.id, name=name, email=email,
                password_hash=hash_password(password), role=role, is_active=True)
    if invite:
        invite.accepted_at = datetime.utcnow()
    db.add(user); db.flush()
    db.add(UserAuditEvent(organization_id=org.id, user_id=user.id,
                          action="team.invitation_accepted" if invite else "organization.created"))
    token = create_session(db, user)
    db.refresh(user); set_session_cookie(response, token)
    logger.info("AUTH_REGISTER | user_id=%s | organization_id=%s", user.id, org.id)
    return {"status":"ok", "user":_payload(user)}

@router.post("/login")
def login(data: dict, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(str(data.get("email") or "")); password = str(data.get("password") or "")
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        logger.warning("AUTH_LOGIN_FAILED | email=%s", email)
        raise HTTPException(401, "Неверный email или пароль")
    token = create_session(db, user); set_session_cookie(response, token)
    logger.info("AUTH_LOGIN_OK | user_id=%s | organization_id=%s", user.id, user.organization_id)
    return {"status":"ok", "user":_payload(user)}

@router.post("/password-reset/request")
def request_password_reset(
    data: dict,
    db: Session = Depends(get_db),
):
    """
    Запрашивает письмо для восстановления пароля.

    Ответ намеренно одинаковый для существующего и несуществующего email,
    чтобы не раскрывать наличие аккаунта.
    """
    email = normalize_email(str(data.get("email") or ""))

    if "@" not in email or len(email) < 5:
        raise HTTPException(400, "Укажите корректный email")

    generic_message = (
        "Если аккаунт с этим email существует, "
        "мы отправили письмо с инструкцией по восстановлению пароля."
    )

    # Check global mail configuration before looking up the account.
    # This keeps the endpoint behavior independent of account existence.
    try:
        validate_password_reset_email_config()
    except Exception as error:
        logger.error(
            "PASSWORD_RESET_EMAIL_CONFIG_ERROR | %s",
            error,
        )
        raise HTTPException(
            503,
            "Восстановление пароля сейчас недоступно: "
            "не настроена отправка почты.",
        )

    user = (
        db.query(User)
        .filter(
            User.email == email,
            User.is_active.is_(True),
        )
        .first()
    )

    if user is None:
        logger.info("PASSWORD_RESET_REQUEST | account_exists=false")
        return {"status": "ok", "message": generic_message}

    now = datetime.utcnow()

    recent = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at >= now - timedelta(seconds=60),
            PasswordResetToken.used_at.is_(None),
        )
        .first()
    )

    if recent:
        logger.info(
            "PASSWORD_RESET_REQUEST | user_id=%s | rate_limited=true",
            user.id,
        )
        return {"status": "ok", "message": generic_message}

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update(
        {"used_at": now},
        synchronize_session=False,
    )

    raw_token = secrets.token_urlsafe(48)

    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash(raw_token),
            created_at=now,
            expires_at=now + timedelta(minutes=RESET_TOKEN_MINUTES),
        )
    )
    db.commit()

    try:
        send_password_reset_email(
            email=user.email,
            user_name=user.name,
            token=raw_token,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "PASSWORD_RESET_EMAIL_FAILED | user_id=%s",
            user.id,
        )
        # Do not disclose whether the account exists. The failure is logged
        # for the operator; the public response remains generic.
        return {"status": "ok", "message": generic_message}

    logger.info(
        "PASSWORD_RESET_REQUEST | user_id=%s | email_sent=true",
        user.id,
    )
    return {"status": "ok", "message": generic_message}


@router.post("/password-reset/confirm")
def confirm_password_reset(
    data: dict,
    response: Response,
    db: Session = Depends(get_db),
):
    raw_token = str(data.get("token") or "").strip()
    password = str(data.get("password") or "")

    if not raw_token:
        raise HTTPException(400, "Ссылка восстановления недействительна")

    if len(password) < 8:
        raise HTTPException(
            400,
            "Пароль должен содержать минимум 8 символов",
        )

    now = datetime.utcnow()

    reset = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash(raw_token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .first()
    )

    if reset is None or reset.user is None or not reset.user.is_active:
        raise HTTPException(
            400,
            "Ссылка восстановления недействительна или истекла",
        )

    user = reset.user
    user.password_hash = hash_password(password)
    reset.used_at = now

    # После смены пароля старые сессии должны стать недействительными.
    db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).update(
        {"revoked_at": now},
        synchronize_session=False,
    )

    db.commit()

    token = create_session(db, user)
    set_session_cookie(response, token)

    logger.info(
        "PASSWORD_RESET_OK | user_id=%s | organization_id=%s",
        user.id,
        user.organization_id,
    )

    return {
        "status": "ok",
        "message": "Пароль изменён. Вы вошли в аккаунт.",
        "user": _payload(user),
    }


@router.post("/change-password")
def change_password(
    data: dict,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    user = require_current_user(request)

    current_password = str(data.get("current_password") or "")
    new_password = str(data.get("new_password") or "")

    if not verify_password(current_password, user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно")

    if len(new_password) < 8:
        raise HTTPException(
            400,
            "Новый пароль должен содержать минимум 8 символов",
        )

    if verify_password(new_password, user.password_hash):
        raise HTTPException(
            400,
            "Новый пароль должен отличаться от текущего",
        )

    now = datetime.utcnow()
    user.password_hash = hash_password(new_password)

    db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).update(
        {"revoked_at": now},
        synchronize_session=False,
    )

    db.commit()

    token = create_session(db, user)
    set_session_cookie(response, token)

    logger.info(
        "PASSWORD_CHANGE_OK | user_id=%s | organization_id=%s",
        user.id,
        user.organization_id,
    )

    return {
        "status": "ok",
        "message": "Пароль изменён.",
    }


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).first()
        if session and session.revoked_at is None:
            session.revoked_at = datetime.utcnow(); db.commit()
    clear_session_cookie(response)
    return {"status":"ok"}

@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    from backend.auth.security import authenticate_request
    user = authenticate_request(db, request) or require_current_user(request)
    return {"status":"ok", "user":_payload(user)}

@router.put("/profile")
def update_profile(data: dict, request: Request, db: Session = Depends(get_db)):
    """Change only the authenticated user's details; never trust a supplied user ID."""
    user = require_current_user(request)
    first_name = str(data.get("first_name") or "").strip()
    last_name = str(data.get("last_name") or "").strip()
    name = " ".join(part for part in (first_name, last_name) if part)
    email = normalize_email(str(data.get("email") or ""))
    if not first_name or len(name) > 120:
        raise HTTPException(400, "Укажите имя (не более 120 символов вместе с фамилией)")
    if len(email) > 320 or "@" not in email or len(email) < 5:
        raise HTTPException(400, "Укажите корректный email")
    email_changed = email != user.email
    if email_changed:
        if not verify_password(str(data.get("current_password") or ""), user.password_hash):
            raise HTTPException(400, "Для смены email укажите текущий пароль")
        if db.query(User.id).filter(User.email == email, User.id != user.id).first():
            raise HTTPException(409, "Этот email уже используется")
    user.name = name
    if email_changed:
        user.email = email
    db.add(UserAuditEvent(organization_id=user.organization_id, user_id=user.id,
                          action="profile.updated"))
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("PROFILE_UPDATE_FAILED | user_id=%s", user.id)
        raise HTTPException(409, "Не удалось сохранить профиль. Проверьте email")
    db.refresh(user)
    return {"status": "ok", "user": _payload(user)}


@router.post("/sessions/revoke-all")
def revoke_all(request: Request, response: Response, db: Session = Depends(get_db)):
    user = require_current_user(request)
    now = datetime.utcnow()
    db.query(AuthSession).filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).update({"revoked_at":now}, synchronize_session=False)
    db.commit(); clear_session_cookie(response)
    return {"status":"ok"}
