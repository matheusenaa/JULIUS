"""CSRF (double-submit cookie) e cabeçalhos de segurança."""

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.deps import CSRF_COOKIE, CSRF_HEADER
from app.config import get_settings

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' "
    "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
    "form-action 'self'"
)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        cookie_token = request.cookies.get(CSRF_COOKIE)
        if request.method in UNSAFE and request.url.path.startswith("/api/"):
            header_token = request.headers.get(CSRF_HEADER)
            if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
                return JSONResponse(
                    {
                        "error": {
                            "code": "csrf",
                            "message": "Sua sessão de segurança expirou. Recarregue a página.",
                        }
                    },
                    status_code=403,
                )

        response = await call_next(request)

        if not cookie_token:
            response.set_cookie(
                CSRF_COOKIE,
                secrets.token_urlsafe(24),
                httponly=False,  # o frontend precisa ler para enviar no cabeçalho
                secure=get_settings().is_production,
                samesite="lax",
                max_age=60 * 60 * 24 * 365,
                path="/",
            )
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        h.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if get_settings().is_production:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
