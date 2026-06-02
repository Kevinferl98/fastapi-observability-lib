from structlog import get_logger as get_structlog_logger
from .config import setup_observability
from .telemetry import init_telemetry, shutdown_telemetry
from .middleware import setup_fastapi_logging, rabbitmq_trace_context

get_logger = get_structlog_logger

__all__ = [
    "setup_observability",
    "init_telemetry",
    "shutdown_telemetry",
    "get_logger",
    "setup_fastapi_logging",
    "rabbitmq_trace_context"
]