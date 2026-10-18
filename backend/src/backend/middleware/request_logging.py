"""Request correlation, safe access logs, and unexpected-error boundary."""

from time import perf_counter
from uuid import uuid4

from backend.errors import error_response
from backend.logging import get_logger, request_id_context

logger = get_logger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())  # Never trust client-supplied correlation IDs.
        token = request_id_context.set(request_id)
        start = perf_counter()
        status_code = 500
        started = False
        failed = False

        async def send_with_id(message):
            nonlocal status_code, started
            if message["type"] == "http.response.start":
                started = True
                status_code = message["status"]
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                message = {
                    **message,
                    "headers": headers + [(b"x-request-id", request_id.encode())],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            failed = True
            logger.exception(
                "Unhandled request failure", extra={"event": "request.failed"}
            )
            if started:
                # A streaming response already sent cannot be replaced by JSON.
                raise
            response = error_response(
                500, "INTERNAL_ERROR", "An unexpected error occurred."
            )
            await response(scope, receive, send_with_id)
        finally:
            route = scope.get("route")
            logger.log(
                40
                if failed or status_code >= 500
                else 30
                if status_code >= 400
                else 20,
                "Request completed",
                extra={
                    "event": "request.completed",
                    "method": scope["method"],
                    # Templates only: raw paths and query strings may contain secrets.
                    "route": getattr(route, "path", "<unmatched>"),
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - start) * 1000, 2),
                },
            )
            request_id_context.reset(token)
