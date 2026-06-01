import logging
import sys
import structlog
from typing import Any, Dict, Optional
from my_observability.processor import inject_opentelemetry_context

def setup_observability(
        log_level: str = "INFO",
        extra_loggers: Optional[Dict[str, Any]] = None,
) -> None:
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.format_exc_info,
        structlog.processors.dict_tracebacks,
        inject_opentelemetry_context,
        structlog.processors.JSONRenderer()
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level
    )

    stdlib_handler = logging.StreamHandler(sys.stdout)
    stdlib_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor = structlog.processors.JSONRenderer(),
        foreign_pre_chain = [
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        ]
    ))

    target_loggers = {
        "uvicorn": {"level": logging.INFO},
        "uvicorn.error": {"level": logging.INFO},
        "uvicorn.access": {"level": logging.WARNING}
    }

    if extra_loggers:
        target_loggers.update(extra_loggers)

    for logger_name, cfg in target_loggers.items():
        tgt_logger = logging.getLogger(logger_name)
        tgt_logger.handles = [stdlib_handler]
        tgt_logger.setLevel(cfg.get("level", numeric_level))
        tgt_logger.propagate = False