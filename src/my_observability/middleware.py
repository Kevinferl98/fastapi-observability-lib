import time
import uuid
import structlog
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from typing import Set

logger = structlog.get_logger("my_observability.middleware")

SENSITIVE_HEADERS: Set[str] = {"authorization", "cookie", "set-cookie", "x-api-key", "token"}

def _sanitize_headers(headers_dict: dict) -> dict:
    sanitized = {}
    for key, value in headers_dict.items():
        key_lower = key.lower()
        if key_lower in SENSITIVE_HEADERS:
            sanitized[key_lower] = "[REDACTED]"
        else:
            sanitized[key_lower] = value
    return sanitized

class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path
        )

        client_host = request.client.host if request.client else "unknown"

        try:
            response = await call_next(request)

            process_time_ms = (time.perf_counter() - start_time) * 1000

            response.headers["x-request-id"] = request_id

            log_payload = {
                "status_code": response.status_code,
                "duration_ms": round(process_time_ms, 2),
                "client_ip": client_host,
                "query_string": request.url.query,
                "request_headers": _sanitize_headers(dict(request.headers)),
            }

            if response.status_code >= 500:
                logger.error("http_request_completed", **log_payload)
            elif response.status_code >= 400:
                logger.warning("http_request_completed", **log_payload)
            else:
                logger.info("http_request_completed", **log_payload)

            return response

        except Exception as exc:
            process_time_ms = (time.perf_counter() - start_time) * 1000

            logger.exception(
                "http_request_failed",
                duration_ms = round(process_time_ms, 2),
                client_ip = client_host,
                exception_message = str(exc),
                request_headers = _sanitize_headers(dict(request.headers)),
            )
            raise exc

def setup_http_logging(app: FastAPI) -> None:
    app.add_middleware(StructuredLoggingMiddleware)