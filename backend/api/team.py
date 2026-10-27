from datetime import datetime, timedelta
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from backend.auth.security import normalize_email, token_hash, require_current_user
from backend.dependencies import get_db
from backend.models.auth import OrganizationInvitation, User, UserAuditEvent, AuthSession
from sqlalchemy import func

router = APIRouter(prefix="/team", tags=["Команда"])

def owner(request):
    u = require_current_user(request)
    if u.role != "OWNER":
        raise HTTPException(403, "Приглашать сотрудников может только владелец")
    return u

def item(i):
    now = datetime.utcnow()
    state = "accepted" if i.accepted_at else "revoked" if i.revoked_at else "expired" if i.expires_at <= now else "pending"
    return {"id": i.id, "email": i.email, "role": i.role, "status": state,
            "created_at": i.created_at.isoformat(), "expires_at": i.expires_at.isoformat()}

@router.get("")
def list_team(request: Request, db: Session = Depends(get_db)):
    u = require_current_user(request)
    users = db.query(User).filter(User.organization_id == u.organization_id).order_by(User.id).all()
    latest = dict(db.query(AuthSession.user_id, func.max(AuthSession.last_activity_at))
        .join(User, User.id == AuthSession.user_id)
        .filter(User.organization_id == u.organization_id, AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.utcnow())
        .group_by(AuthSession.user_id).all())
    now = datetime.utcnow()
    inv = db.query(OrganizationInvitation).filter(OrganizationInvitation.organization_id == u.organization_id).order_by(OrganizationInvitation.id.desc()).limit(100).all()
    return {"members": [{"id": v.id, "name": v.name, "email": v.email, "role": v.role, "is_active": v.is_active,
        "last_seen_at": latest[v.id].isoformat() if latest.get(v.id) else None,
        "online": bool(v.is_active and latest.get(v.id) and (now - latest[v.id]).total_seconds() <= 300)} for v in users],
            "invitations": [item(v) for v in inv] if u.role == "OWNER" else []}

@router.post("/invitations")
def invite(data: dict, request: Request, db: Session = Depends(get_db)):
    u = owner(request)
    email = normalize_email(str(data.get("email") or ""))
    if len(email) > 320 or "@" not in email or len(email) < 5:
        raise HTTPException(400, "Укажите корректный email")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Этот email уже зарегистрирован. Присоединение существующих аккаунтов пока не поддерживается")
    active = db.query(OrganizationInvitation).filter(
        OrganizationInvitation.organization_id == u.organization_id,
        OrganizationInvitation.email == email,
        OrganizationInvitation.accepted_at.is_(None),
        OrganizationInvitation.revoked_at.is_(None),
        OrganizationInvitation.expires_at > datetime.utcnow(),
    ).first()
    if active:
        raise HTTPException(409, "Активное приглашение для этого адреса уже существует. Отзовите его, чтобы создать новое")
    raw = secrets.token_urlsafe(40)
    inv = OrganizationInvitation(organization_id=u.organization_id, email=email,
        token_hash=token_hash(raw), role="MEMBER", created_by_id=u.id,
        expires_at=datetime.utcnow() + timedelta(days=7))
    db.add(inv)
    db.add(UserAuditEvent(organization_id=u.organization_id, user_id=u.id, action="team.invitation_created"))
    db.commit()
    # Link is constructed client-side from its own origin; raw token never persisted.
    return {"invitation": item(inv), "token": raw}

@router.delete("/invitations/{invitation_id}")
def revoke(invitation_id: int, request: Request, db: Session = Depends(get_db)):
    u = owner(request)
    inv = db.query(OrganizationInvitation).filter(
        OrganizationInvitation.id == invitation_id,
        OrganizationInvitation.organization_id == u.organization_id,
    ).first()
    if inv is None: raise HTTPException(404, "Приглашение не найдено")
    if inv.accepted_at: raise HTTPException(409, "Приглашение уже использовано")
    inv.revoked_at = datetime.utcnow()
    db.add(UserAuditEvent(organization_id=u.organization_id, user_id=u.id, action="team.invitation_revoked"))
    db.commit()
    return {"status": "ok"}

@router.post("/members/{member_id}/deactivate")
def deactivate_member(member_id: int, request: Request, db: Session = Depends(get_db)):
    u = owner(request)
    if member_id == u.id:
        raise HTTPException(400, "Нельзя отключить собственную учётную запись")
    target = db.query(User).filter(User.id == member_id, User.organization_id == u.organization_id).with_for_update().first()
    if not target:
        raise HTTPException(404, "Сотрудник не найден")
    if target.role == "OWNER":
        raise HTTPException(403, "Нельзя отключить владельца организации")
    if not target.is_active:
        raise HTTPException(409, "Доступ сотрудника уже отключён")
    target.is_active = False
    db.query(AuthSession).filter(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None)).update(
        {AuthSession.revoked_at: datetime.utcnow()}, synchronize_session=False)
    db.add(UserAuditEvent(organization_id=u.organization_id, user_id=u.id,
                          action="team.member_deactivated", path=f"member:{target.id}"))
    db.commit()
    return {"status": "ok"}

@router.get("/audit")
def list_audit(request: Request, limit: int = 100, db: Session = Depends(get_db)):
    u = owner(request)
    limit = max(1, min(limit, 200))
    rows = db.query(UserAuditEvent).filter(UserAuditEvent.organization_id == u.organization_id).order_by(UserAuditEvent.id.desc()).limit(limit).all()
    names = dict(db.query(User.id, User.name).filter(User.organization_id == u.organization_id).all())
    return {"events": [{"id": e.id, "user_id": e.user_id, "user_name": names.get(e.user_id, "Система"), "action": e.action,
        "method": e.method, "path": e.path, "status_code": e.status_code,
        "created_at": e.created_at.isoformat()} for e in rows]}
