import structlog
from opentelemetry.propagate import inject

def build_rabbitmq_headers() -> dict:
    headers = {}

    inject(headers)

    ctx = structlog.contextvars.get_contextvars()

    request_id = ctx.get("request_id")
    if request_id:
        headers["x-request-id"] = request_id

    return headers