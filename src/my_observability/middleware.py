import time
import uuid
import structlog
from contextlib import contextmanager
from typing import Set, Dict, Any, Callable, Iterator

logger = structlog.get_logger("my_observability.middleware")

SENSITIVE_HEADERS: Set[str] = {"authorization", "cookie", "set-cookie", "x-api-key", "token", "proxy-authorization"}

def _sanitize_headers(headers_iterable) -> Dict[str, str]:
    """Sanitizes sensitive headers from ASGI scope headers."""
    sanitized = {}
    for key, value in headers_iterable:
        try:
            key_str = key.decode("latin-1").lower() if isinstance(key, bytes) else key.lower()
            value_str = value.decode("latin-1") if isinstance(value, bytes) else value
            if key_str in SENSITIVE_HEADERS:
                sanitized[key_str] = "[REDACTED]"
            else:
                sanitized[key_str] = value_str
        except Exception:
            # Fallback if binary formatting or decoding fails
            continue
    return sanitized

class FastAPILoggingMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()

        # Extract or generate request ID from ASGI scope headers
        headers_dict = dict(scope.get("headers", []))
        request_id_bytes = headers_dict.get(b"x-request-id")
        request_id = request_id_bytes.decode("latin-1") if request_id_bytes else str(uuid.uuid4())

        # Clear and bind contextvars for the entire async execution path
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=scope["method"],
            path=scope["path"]
        )

        # Extract Client IP safely
        client = scope.get("client")
        client_host = client[0] if client else "unknown"
        query_string = scope.get("query_string", b"").decode("latin-1")

        logger.debug("http_request_started", client_ip=client_host, query_string=query_string)

        status_code = [500]  # Default fallback if the app crashes before sending response headers

        async def send_wrapper(message: Dict[str, Any]) -> None:
            """Intercepts ASGI send events to capture the HTTP status code and inject headers."""
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
                # Inject x-request-id back into the response headers dynamically
                headers = message.get("headers", [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            process_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "http_request_failed",
                duration_ms=round(process_time_ms, 2),
                client_ip=client_host,
                exception_message=str(exc),
                request_headers=_sanitize_headers(scope.get("headers", [])),
            )
            raise exc
        else:
            process_time_ms = (time.perf_counter() - start_time) * 1000
            final_status = status_code[0]

            log_payload = {
                "status_code": final_status,
                "duration_ms": round(process_time_ms, 2),
                "client_ip": client_host,
                "query_string": query_string,
                "request_headers": _sanitize_headers(scope.get("headers", [])),
            }

            if final_status >= 500:
                logger.error("http_request_completed", **log_payload)
            elif final_status >= 400:
                logger.warning("http_request_completed", **log_payload)
            else:
                logger.info("http_request_completed", **log_payload)

def setup_fastapi_logging(app: Any) -> None:
    app.add_middleware(FastAPILoggingMiddleware)

@contextmanager
def rabbitmq_trace_context(properties_headers: Dict[str, Any], queue_name: str = "unknown") -> Iterator[None]:
    """
    Context manager to trace and log RabbitMQ message processing.
    Extracts or generates a request_id/correlation_id from headers.
    """
    start_time = time.perf_counter()

    headers = properties_headers or {}

    request_id = headers.get("x-request-id") or headers.get("correlation-id") or str(uuid.uuid4())
    if isinstance(request_id, bytes):
        request_id = request_id.decode("latin-1")

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        queue=queue_name
    )

    logger.info("message_processing_started", request_headers=_sanitize_headers(headers.items()))

    try:
        yield

        process_time_ms = (time.perf_counter() - start_time) * 1000
        logger.info("message_processing_completed", duration_ms=round(process_time_ms, 2))

    except Exception as exc:
        process_time_ms = (time.perf_counter() - start_time) * 1000
        logger.exception(
            "message_processing_failed",
            duration_ms=round(process_time_ms, 2),
            exception_message=str(exc),
            request_headers=_sanitize_headers(headers.items())
        )
        raise exc