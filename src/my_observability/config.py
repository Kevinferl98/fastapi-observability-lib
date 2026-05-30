import logging
import logging.config
from my_observability.formatter import JsonFormatter

def setup_logging(log_level: str = "INFO", extra_loggers: dict = None):
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": JsonFormatter,
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "level": log_level
            }
        },
        "root": {
            "level": log_level,
            "handlers": ["console"]
        },
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"level": "WARNING"}
        }
    }

    if extra_loggers:
        logging_config["loggers"].update(extra_loggers)

    logging.config.dictConfig(logging_config)