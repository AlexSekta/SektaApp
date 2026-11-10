"""Opt-in safeguards for a public browser deployment.

Enable with PUBLIC_SECURITY_ENABLED=true after staging checks. This is an
in-process limiter; use an edge/shared limiter for multi-worker production.
"""
import os
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_MUTATIONS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_LIMITS = {
    '/auth/login': (10, 300),
    '/auth/register': (5, 3600),
    '/auth/password-reset/request': (5, 3600),
    '/auth/password-reset/confirm': (10, 600),
}
# Internal endpoints must not be published by a public tunnel.
# Return 404 rather than revealing the existence of administrative probes.
_INTERNAL_EXACT = frozenset({
    '/database', '/docs', '/redoc', '/openapi.json',
    '/wb/stocks-test',
    # These legacy GET endpoints modify data or trigger remote syncs.
    '/wb/sync-products', '/wb/sync-stocks', '/wb/sync-warehouses',
})
_INTERNAL_PREFIXES = ('/docs/', '/redoc/')


def _is_internal_path(path: str) -> bool:
    path = path.rstrip('/') or '/'
    if path in _INTERNAL_EXACT or path.startswith(_INTERNAL_PREFIXES):
        return True
    # Diagnostic endpoints are deliberately unavailable over public HTTP.
    return path.startswith('/analytics/') and (
        path.endswith('-diagnostic') or path.endswith('-probe')
    )


_MAX_BUCKETS = 10000
_lock = threading.Lock()
_attempts = defaultdict(deque)


def _origin(value: str) -> str:
    try:
        url = urlsplit(value.strip())
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            return ''
        port = url.port
        if port is None or (url.scheme == 'https' and port == 443) or (url.scheme == 'http' and port == 80):
            return f'{url.scheme}://{url.hostname.lower()}'
        return f'{url.scheme}://{url.hostname.lower()}:{port}'
    except (ValueError, AttributeError):
        return ''


def _allowed_origins():
    values = os.getenv('PUBLIC_ALLOWED_ORIGINS', 'http://127.0.0.1:8080,http://localhost:5173,http://127.0.0.1:5173')
    return {_origin(part) for part in values.split(',') if _origin(part)}


def _client_address(request: Request) -> str:
    peer = request.client.host if request.client else 'unknown'
    # Only trust an upstream real-IP header if request came via the local proxy.
    if peer in ('127.0.0.1', '::1') and os.getenv('PUBLIC_TRUST_CF_CONNECTING_IP', 'false').lower() == 'true':
        value = request.headers.get('cf-connecting-ip', '').strip()
        if value:
            try:
                import ipaddress
                return str(ipaddress.ip_address(value))
            except ValueError:
                pass
    return peer


def _limited(path: str, identity: str) -> bool:
    threshold, seconds = _LIMITS[path]
    now = time.monotonic()
    key = (path, identity)
    with _lock:
        # Prevent unbounded memory use from spoofed/high-cardinality IP values.
        if len(_attempts) >= _MAX_BUCKETS and key not in _attempts:
            expired = [k for k, records in _attempts.items() if not records or now - records[-1] > _LIMITS[k[0]][1]]
            for k in expired:
                del _attempts[k]
            if len(_attempts) >= _MAX_BUCKETS:
                return True
        records = _attempts[key]
        while records and now - records[0] > seconds:
            records.popleft()
        if len(records) >= threshold:
            return True
        records.append(now)
        return False


class PublicProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if os.getenv('PUBLIC_SECURITY_ENABLED', 'false').strip().lower() != 'true':
            return await call_next(request)
        if request.method == 'OPTIONS':
            return await call_next(request)

        path = request.url.path
        if os.getenv('PUBLIC_BLOCK_INTERNAL_ROUTES', 'true').strip().lower() == 'true' and _is_internal_path(path):
            return JSONResponse({'detail': 'Not Found'}, status_code=404)
        if request.method in _MUTATIONS:
            origin = _origin(request.headers.get('origin', ''))
            if origin not in _allowed_origins():
                return JSONResponse({'detail': 'Недопустимый источник запроса'}, status_code=403)

        if request.method == 'POST' and path in _LIMITS:
            if _limited(path, _client_address(request)):
                return JSONResponse({'detail': 'Слишком много запросов. Повторите позже.'},
                                    status_code=429, headers={'Retry-After': '300'})
        response = await call_next(request)
        # Defense in depth (Caddy must also block the docs outside localhost).
        return response
