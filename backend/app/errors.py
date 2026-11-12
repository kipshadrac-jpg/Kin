"""One error shape for every failure: {"error": {"code", "message", "details"}}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("kin.errors")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(what: str = "resource") -> AppError:
    return AppError(404, "not_found", f"{what} not found")


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only field locations and messages; never echo the submitted values back.
        fields = [{"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "Request is not valid", {"fields": fields}), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(_body("internal_error", "Something went wrong"), status_code=500)
