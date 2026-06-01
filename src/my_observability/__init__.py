from structlog import get_logger as get_structlog_logger
from .config import setup_observability
from .middleware import setup_http_logging, StructuredLoggingMiddleware
from .telemetry import init_telemetry, shutdown_telemetry

get_logger = get_structlog_logger

__all__ = [
    "setup_observability",
    "setup_http_logging",
    "StructuredLoggingMiddleware",
    "init_telemetry",
    "shutdown_telemetry",
    "get_logger",
]