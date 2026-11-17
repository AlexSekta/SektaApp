# mppulse: preparation for Cloudflare Tunnel (NOT public deployment)

## Contents
- frontend/src/main.tsx: converts legacy :8000 fetch URLs to same-origin URLs on the public site; preserves http://localhost:5173 local development.
- deployment/Caddyfile: local-only HTTP proxy at 127.0.0.1:8080 for production dist + existing FastAPI.

## On the old Windows PC
1. Back up `frontend/src/main.tsx`; unpack the patch into the project root.
2. In `frontend` run `npm run build`; verify no TypeScript errors.
3. Install Caddy from https://caddyserver.com/docs/install (do not confuse with cloudflared).
4. From project root run `caddy validate --config deployment/Caddyfile --adapter caddyfile`.
5. The Caddyfile uses relative path `./frontend/dist`; start Caddy from project root: `caddy run --config deployment/Caddyfile --adapter caddyfile`.
6. Check http://127.0.0.1:8080/login, and test login and read-only pages. Keep cloudflared public routes UNCONFIGURED.

## Security gates BEFORE public publication
- Protect public auth endpoints: login/registration/password reset rate limits, anti-abuse and registration policy.
- CSRF protection / Origin verification for state-changing authenticated routes; SameSite=Lax alone is not a complete defense.
- RLS isolation across two organizations and permissions of all API endpoints.
- Audit potentially unauthenticated routes, route-specific authorization, and diagnostic routes.
- Remove/replace vulnerable `xlsx` dependency (npm audit high).
- Set AUTH_COOKIE_SECURE=true only when external HTTPS is correctly served and tested; protect production admin interfaces.
- Set up backups, Windows service for local reverse proxy and HTTPS origin/proxy verification.

## Cloudflare later
Once security gates pass: public hostname app.alexgutt.ru -> HTTP http://127.0.0.1:8080. Never expose PostgreSQL/8000/router ports publicly.
