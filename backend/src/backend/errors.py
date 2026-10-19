"""Public errors contain safe messages; internal details stay out of responses."""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.logging import request_id_context


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message  # Must be safe to expose publicly.
        self.status_code = status_code


def error_response(
    status_code: int, code: str, message: str, details=None, headers=None
):
    error = {
        "code": code,
        "message": message,
        "request_id": request_id_context.get(),
    }
    if details is not None:
        error["details"] = details
    return JSONResponse(
        status_code=status_code, content={"error": error}, headers=headers
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError):
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        # Arbitrary HTTPException.detail can contain internal information.
        try:
            message = HTTPStatus(exc.status_code).phrase
        except ValueError:
            message = "Request failed"
        return error_response(
            exc.status_code, f"HTTP_{exc.status_code}", message, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Never echo input, validator context, or user-controlled extra field names.
        details = [
            {
                "location": [
                    part
                    if isinstance(part, int)
                    or part
                    in {"body", "query", "path", "header", "username", "password"}
                    else "field"
                    for part in error["loc"]
                ],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return error_response(
            422, "VALIDATION_ERROR", "Request validation failed.", details
        )
