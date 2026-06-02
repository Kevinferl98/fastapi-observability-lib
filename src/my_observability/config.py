import logging
import sys
import structlog
from typing import Any, Dict, Optional
from my_observability.processor import inject_opentelemetry_context

def setup_observability(
    log_level: str = "INFO",
    extra_loggers: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Configures structured logging using structlog and integrates it with the
    Python standard logging library and OpenTelemetry.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Shared processors between structlog and standard logging
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.format_exc_info,
        structlog.processors.dict_tracebacks,
        inject_opentelemetry_context
    ]

    # Structlog configuration
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True
    )

    # Standard logging integration
    stdlib_handler = logging.StreamHandler(sys.stdout)
    stdlib_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors
        )
    )

    # Root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(stdlib_handler)
    root_logger.setLevel(numeric_level)

    # Third-party loggers
    target_loggers = {
        # FastAPI / Uvicorn
        "uvicorn": {"level": logging.INFO},
        "uvicorn.error": {"level": logging.INFO},
        "uvicorn.access": {"level": logging.WARNING},

        # Flask / Werkzeug
        "werkzeug": {"level": logging.INFO},

        # Django
        "django": {"level": logging.INFO},
        "django.request": {"level": logging.INFO},

        # Workers & Message Brokers
        "celery": {"level": logging.INFO},
        "amqp": {"level": logging.WARNING},
        "kafka": {"level": logging.WARNING},
    }

    if extra_loggers:
        target_loggers.update(extra_loggers)

    for logger_name, cfg in target_loggers.items():
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(stdlib_handler)
        logger.setLevel(cfg.get("level", numeric_level))
        logger.propagate = False