from fastapi import APIRouter, Request, Response

from app.api.deps import DB, SESSION_COOKIE, CurrentUser, client_ip
from app.config import get_settings
from app.errors import AppError
from app.schemas import LoginIn, PasswordChangeIn, RegisterIn, SettingsIn, UserOut
from app.security.ratelimit import login_limiter, register_limiter
from app.services import audit
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOO_MANY = AppError(429, "rate_limited", "Muitas tentativas. Aguarde alguns minutos e tente novamente.")


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=s.is_production,
        samesite="lax",
        max_age=s.session_days * 24 * 3600,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: DB):
    if not get_settings().allow_registration:
        raise AppError(403, "registration_closed", "Novos cadastros estão desativados.")
    if not register_limiter.hit(client_ip(request) or "?"):
        raise TOO_MANY
    user = auth_service.register(db, body.email, body.name, body.password)
    token = auth_service.create_session(db, user, request.headers.get("user-agent"), client_ip(request))
    _set_session_cookie(response, token)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: DB):
    key = f"{client_ip(request)}|{body.email.lower()}"
    if not login_limiter.hit(key):
        raise TOO_MANY
    user = auth_service.authenticate(db, body.email, body.password)
    login_limiter.reset(key)
    token = auth_service.create_session(db, user, request.headers.get("user-agent"), client_ip(request))
    _set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB):
    auth_service.revoke_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.get("/session", response_model=UserOut | None)
def session(request: Request, db: DB):
    """Usuário logado ou null — sem 401, para a checagem inicial do app não gerar erro."""
    return auth_service.resolve_session(db, request.cookies.get(SESSION_COOKIE))


@router.patch("/me", response_model=UserOut)
def update_me(body: SettingsIn, user: CurrentUser, db: DB):
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        user.name = data.pop("name")
    user.settings = {**(user.settings or {}), **data}
    audit.record(db, user.id, "user", user.id, "update", "Preferências atualizadas.")
    db.commit()
    return user


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeIn, request: Request, user: CurrentUser, db: DB):
    auth_service.change_password(
        db, user, body.current_password, body.new_password, request.cookies.get(SESSION_COOKIE, "")
    )
