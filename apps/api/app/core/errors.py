"""Uniform error envelope: `{"error": {"code", "message", "details"}}`."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def not_found(entity: str = "resource") -> ApiError:
    return ApiError(404, "not_found", f"{entity.capitalize()} not found")


def conflict(code: str, message: str, details: Any = None) -> ApiError:
    return ApiError(409, code, message, details)


def bad_request(code: str, message: str, details: Any = None) -> ApiError:
    return ApiError(400, code, message, details)


def forbidden(message: str = "You do not have permission to do that") -> ApiError:
    return ApiError(403, "permission_denied", message)


def _envelope(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthenticated", 403: "permission_denied", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return _envelope(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return _envelope(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _envelope(500, "internal_error", "Unexpected server error")
