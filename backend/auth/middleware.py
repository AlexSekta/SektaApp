from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from backend.database import SessionLocal
from backend.auth.tenant import tenant_session
from backend.models.auth import UserAuditEvent
from backend.logging_config import get_logger

audit_logger = get_logger("user_actions")
from backend.auth.security import authenticate_request

PUBLIC_EXACT = {"/", "/database", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}
PUBLIC_PREFIXES = ("/auth/",)

class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        db = SessionLocal()
        try:
            if not authenticate_request(db, request):
                return JSONResponse(status_code=401, content={"status":"error","message":"Требуется авторизация"})
            user = request.state.user
            response = await call_next(request)
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                audit_logger.info("USER_ACTION | user_id=%s | organization_id=%s | method=%s | path=%s | status=%s",
                    user.id, user.organization_id, request.method, path, response.status_code)
                try:
                    with tenant_session(user.organization_id) as audit_db:
                        audit_db.add(UserAuditEvent(organization_id=user.organization_id,
                            user_id=user.id, action="http.mutation", method=request.method,
                            path=path[:300], status_code=response.status_code))
                        audit_db.commit()
                except Exception:
                    audit_logger.exception("AUDIT_WRITE_ERROR | user_id=%s", user.id)
            return response
        finally:
            db.close()
