import json
import logging
import time
import uuid
from fastapi import FastAPI, Request
from starlette.responses import Response

logger = logging.getLogger("my_observability.middleware")

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}
VISIBLE_HEADERS = {"content-type", "content-length", "user-agent", "x-request-id"}
VISIBLE_RESPONSE_HEADERS = {"content-type", "content-length", "x-request-id"}
TEXT_BODY_CONTENT_TYPES = (
    "application/json",
    "application/problem+json",
    "application/xml",
    "text/",
)

def _sanitize_headers(raw_headers: dict[str, str], visible_set: set[str]) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for key, value in raw_headers.items():
        key_lower = key.lower()
        if key_lower in SENSITIVE_HEADERS:
            sanitized[key_lower] = "[REDACTED]"
            continue
        if key_lower in visible_set:
            sanitized[key_lower] = value
    return sanitized


def _truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated, True


def _is_text_payload(content_type: str | None) -> bool:
    if not content_type:
        return False
    content_type = content_type.lower()
    return any(content_type.startswith(prefix) for prefix in TEXT_BODY_CONTENT_TYPES)


def _decode_body(body_bytes: bytes, content_type: str | None, max_bytes: int) -> tuple[str | None, bool]:
    if not body_bytes:
        return None, False
    if not _is_text_payload(content_type):
        return f"[BINARY:{len(body_bytes)} bytes]", False
    text = body_bytes.decode("utf-8", errors="replace")
    return _truncate_text(text, max_bytes)


def setup_http_logging(app: FastAPI, log_bodies: bool = False, max_body_bytes: int = 1024):
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.perf_counter()
        # Preserve upstream request ID when present; otherwise create one so
        # cross-service debugging can still correlate logs deterministically.
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id

        client_host = request.client.host if request.client else "unknown"
        path = request.url.path
        method = request.method
        query_string = request.url.query

        req_headers = _sanitize_headers(dict(request.headers), VISIBLE_HEADERS)
        req_headers["x-request-id"] = request_id

        request_body_text = None
        request_body_truncated = False
        request_content_type = request.headers.get("content-type")

        if log_bodies:
            raw_request_body = await request.body()
            request_body_text, request_body_truncated = _decode_body(
                raw_request_body,
                request_content_type,
                max_body_bytes,
            )

        try:
            response = await call_next(request)
        except Exception:
            process_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "http_request_failed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "query": query_string,
                    "client_ip": client_host,
                    "duration_ms": round(process_time_ms, 2),
                    "request_headers": req_headers,
                    "request_body": request_body_text,
                    "request_body_truncated": request_body_truncated,
                },
            )
            raise

        response.headers["x-request-id"] = request_id
        process_time_ms = (time.perf_counter() - start_time) * 1000

        response_body_text = None
        response_body_truncated = False
        response_content_type = response.headers.get("content-type")

        if log_bodies:
            # body_iterator is a one-shot stream; buffer and rebuild the
            # response to avoid consuming payload before it reaches the client.
            response_body_chunks = [chunk async for chunk in response.body_iterator]
            response_body_bytes = b"".join(response_body_chunks)
            response_body_text, response_body_truncated = _decode_body(
                response_body_bytes,
                response_content_type,
                max_body_bytes,
            )

            response = Response(
                content=response_body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        resp_headers = _sanitize_headers(dict(response.headers), VISIBLE_RESPONSE_HEADERS)

        log_data = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "query": query_string,
            "status_code": response.status_code,
            "duration_ms": round(process_time_ms, 2),
            "client_ip": client_host,
            "request_headers": req_headers,
            "response_headers": resp_headers,
        }

        if log_bodies:
            if request_body_text:
                try:
                    log_data["request_body"] = json.loads(request_body_text)
                except json.JSONDecodeError:
                    log_data["request_body"] = request_body_text
            if response_body_text:
                try:
                    log_data["response_body"] = json.loads(response_body_text)
                except json.JSONDecodeError:
                    log_data["response_body"] = response_body_text
            # Explicit truncation flags avoid ambiguity when long bodies are cut.
            log_data["request_body_truncated"] = request_body_truncated
            log_data["response_body_truncated"] = response_body_truncated

        if response.status_code >= 500:
            logger.error("http_request", extra=log_data)
        else:
            logger.info("http_request", extra=log_data)

        return response