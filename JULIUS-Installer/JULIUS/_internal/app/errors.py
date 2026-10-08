"""Erros padronizados: o cliente sempre recebe {"error": {"code", "message"}} em português.

Detalhes internos (stack trace, SQL) ficam só no log, identificados por request_id.
"""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("julius")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details


class NotFound(AppError):
    def __init__(self, what: str = "Registro"):
        super().__init__(404, "not_found", f"{what} não encontrado(a).")


class Conflict(AppError):
    def __init__(self, message: str, code: str = "conflict", details: dict | None = None):
        super().__init__(409, code, message, details)


class BadRequest(AppError):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(400, code, message)


def _body(code: str, message: str, details=None) -> dict:
    err = {"code": code, "message": message}
    if details:
        err["details"] = details
    return {"error": err}


_HTTP_MESSAGES = {
    401: "Sua sessão expirou. Entre novamente.",
    403: "Você não tem permissão para esta ação.",
    404: "Recurso não encontrado.",
    405: "Operação não permitida.",
    429: "Muitas tentativas. Aguarde alguns minutos e tente novamente.",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else None
        message = _HTTP_MESSAGES.get(exc.status_code, message or "Não foi possível concluir.")
        return JSONResponse(_body(f"http_{exc.status_code}", message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = {}
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path")]
            fields[".".join(loc) or "_"] = e.get("msg", "inválido")
        return JSONResponse(
            _body("validation", "Alguns campos estão inválidos. Revise e tente novamente.", fields),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        request_id = uuid.uuid4().hex[:12]
        log.exception("Erro inesperado [%s] %s %s", request_id, request.method, request.url.path)
        return JSONResponse(
            _body(
                "internal",
                f"Algo deu errado do nosso lado. Tente novamente. (código {request_id})",
            ),
            status_code=500,
        )
