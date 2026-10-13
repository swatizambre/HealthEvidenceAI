"""Map exceptions to structured JSON. Stack traces stay in server logs."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.logging import request_id_ctx

logger = logging.getLogger("healthevidence.errors")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        del request
        return _error(exc.status_code, exc.error_code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        del request
        return _error(422, "VALIDATION_ERROR", _validation_message(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        del request
        if exc.status_code == 404:
            return _error(404, "NOT_FOUND", "The requested resource was not found.")
        return _error(exc.status_code, "HTTP_ERROR", "The request could not be completed.")

    @app.exception_handler(SQLAlchemyError)
    async def database_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        del request
        logger.error("database_error type=%s detail=%s", type(exc).__name__, str(exc)[:240])
        return _error(503, "DATABASE_ERROR", "The database request could not be completed.")

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        del request
        logger.error("unhandled_error type=%s", type(exc).__name__)
        return _error(500, "INTERNAL_ERROR", "An unexpected error occurred.")


def _error(status_code: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "request_id": request_id_ctx.get(),
        },
    )


def _validation_message(exc: RequestValidationError) -> str:
    names: list[str] = []
    for error in exc.errors():
        location = error.get("loc", ())
        if location:
            names.append(str(location[-1]))
    unique = list(dict.fromkeys(names))
    if not unique:
        return "Request validation failed."
    return "Request validation failed for: " + ", ".join(unique)
