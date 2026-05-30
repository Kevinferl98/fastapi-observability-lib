import json
import logging
from datetime import datetime, timezone
from opentelemetry.trace import get_current_span

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Inject trace/span IDs into every log line produced inside an active
        # span so logs can be pivoted directly from distributed traces.
        span = get_current_span()
        span_ctx = span.get_span_context() if span else None
        if span_ctx and span_ctx.is_valid:
            log_record["trace_id"] = f"{span_ctx.trace_id:032x}"
            log_record["span_id"] = f"{span_ctx.span_id:016x}"

        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            )
        }

        log_record.update(extra_fields)

        return json.dumps(log_record)