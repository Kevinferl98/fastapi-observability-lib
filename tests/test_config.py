import io
import logging
import pytest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from my_observability import config

MANAGED_LOGGERS = {
    "uvicorn": logging.INFO,
    "uvicorn.error": logging.INFO,
    "uvicorn.access": logging.WARNING,
    "werkzeug": logging.INFO,
    "django": logging.INFO,
    "django.request": logging.INFO,
    "celery": logging.INFO,
    "amqp": logging.WARNING,
    "kafka": logging.WARNING,
}

@dataclass
class StructlogHarness:
    stdout: io.StringIO
    configure_kwargs: dict[str, Any]
    filtering_levels: list[int]
    formatter_kwargs: list[dict[str, Any]]
    FilteringBoundLogger: type
    LoggerFactory: type
    TimeStamper: type
    JSONRenderer: type
    ProcessorFormatter: type

@pytest.fixture(autouse=True)
def preserve_logging_state():
    root_logger = logging.getLogger()
    original_root_handlers = list(root_logger.handlers)
    original_root_level = root_logger.level
    logger_names = (*MANAGED_LOGGERS, "custom.logger")
    original_loggers = {
        name: {
            "handlers": list(logging.getLogger(name).handlers),
            "level": logging.getLogger(name).level,
            "propagate": logging.getLogger(name).propagate,
        }
        for name in logger_names
    }

    yield

    root_logger.handlers = original_root_handlers
    root_logger.setLevel(original_root_level)

    for name, state in original_loggers.items():
        logger = logging.getLogger(name)
        logger.handlers = state["handlers"]
        logger.setLevel(state["level"])
        logger.propagate = state["propagate"]

@pytest.fixture
def structlog_harness(monkeypatch):
    stdout = io.StringIO()
    configure_kwargs = {}
    filtering_levels = []
    formatter_kwargs = []

    class FilteringBoundLogger:
        pass

    class PrintLoggerFactory:
        def __init__(self, file):
            self.file = file

    class LoggerFactory:
        pass

    class TimeStamper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class JSONRenderer:
        pass

    class ProcessorFormatter:
        @staticmethod
        def wrap_for_formatter(*args, **kwargs):
            return None

        def __init__(self, **kwargs):
            formatter_kwargs.append(kwargs)
            self.kwargs = kwargs

    def configure(**kwargs):
        configure_kwargs.update(kwargs)

    def make_filtering_bound_logger(level):
        filtering_levels.append(level)
        return FilteringBoundLogger

    monkeypatch.setattr(config, "sys", SimpleNamespace(stdout=stdout))
    monkeypatch.setattr(config.structlog, "configure", configure)
    monkeypatch.setattr(
        config.structlog,
        "make_filtering_bound_logger",
        make_filtering_bound_logger,
    )

    monkeypatch.setattr(
        config.structlog,
        "PrintLoggerFactory",
        PrintLoggerFactory,
    )

    monkeypatch.setattr(
        config.structlog.stdlib,
        "LoggerFactory",
        LoggerFactory,
    )

    monkeypatch.setattr(
        config.structlog.processors,
        "TimeStamper",
        TimeStamper,
    )

    monkeypatch.setattr(
        config.structlog.processors,
        "JSONRenderer",
        JSONRenderer,
    )

    monkeypatch.setattr(
        config.structlog.stdlib,
        "ProcessorFormatter",
        ProcessorFormatter,
    )

    return StructlogHarness(
        stdout=stdout,
        configure_kwargs=configure_kwargs,
        filtering_levels=filtering_levels,
        formatter_kwargs=formatter_kwargs,
        FilteringBoundLogger=FilteringBoundLogger,
        LoggerFactory=LoggerFactory,
        TimeStamper=TimeStamper,
        JSONRenderer=JSONRenderer,
        ProcessorFormatter=ProcessorFormatter,
    )

def processor_pipeline_names(
    processors: list[Any],
    harness: StructlogHarness,
) -> list[str]:
    names = []

    for processor in processors:
        if processor is config.structlog.contextvars.merge_contextvars:
            names.append("merge_contextvars")
        elif processor is config.structlog.processors.add_log_level:
            names.append("add_log_level")
        elif isinstance(processor, harness.TimeStamper):
            names.append("timestamp")
        elif processor is config.structlog.processors.format_exc_info:
            names.append("format_exc_info")
        elif processor is config.structlog.processors.dict_tracebacks:
            names.append("dict_tracebacks")
        elif processor is config.inject_opentelemetry_context:
            names.append("inject_opentelemetry_context")
        elif isinstance(processor, harness.JSONRenderer):
            names.append("json_renderer")
        elif processor is harness.ProcessorFormatter.wrap_for_formatter:
            names.append("wrap_for_formatter")
        else:
            names.append(repr(processor))

    return names

def test_configures_structlog_with_shared_processors(structlog_harness):
    config.setup_observability(log_level="debug")

    processors = structlog_harness.configure_kwargs["processors"]

    assert processor_pipeline_names(processors, structlog_harness) == [
        "merge_contextvars",
        "add_log_level",
        "timestamp",
        "format_exc_info",
        "dict_tracebacks",
        "inject_opentelemetry_context",
        "wrap_for_formatter",
    ]

    assert processors[2].kwargs == {
        "fmt": "iso",
        "utc": True,
        "key": "timestamp",
    }

    assert structlog_harness.configure_kwargs["wrapper_class"] is (
        structlog_harness.FilteringBoundLogger
    )
    assert structlog_harness.configure_kwargs["cache_logger_on_first_use"] is True

    assert isinstance(
        structlog_harness.configure_kwargs["logger_factory"],
        structlog_harness.LoggerFactory,
    )
    assert structlog_harness.filtering_levels == [logging.DEBUG]

def test_configures_root_logger_with_structlog_formatter(structlog_harness):
    config.setup_observability()

    root_logger = logging.getLogger()

    assert root_logger.level == logging.INFO
    assert len(root_logger.handlers) == 1
    assert root_logger.handlers[0].stream is structlog_harness.stdout
    assert isinstance(
        root_logger.handlers[0].formatter,
        structlog_harness.ProcessorFormatter,
    )

    formatter_kwargs = structlog_harness.formatter_kwargs[0]

    assert isinstance(
        formatter_kwargs["processor"],
        structlog_harness.JSONRenderer,
    )

    assert processor_pipeline_names(
        formatter_kwargs["foreign_pre_chain"],
        structlog_harness,
    ) == [
        "merge_contextvars",
        "add_log_level",
        "timestamp",
        "format_exc_info",
        "dict_tracebacks",
        "inject_opentelemetry_context",
    ]

@pytest.mark.parametrize(
    ("log_level", "expected_level"),
    [
        ("warning", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("not-a-real-level", logging.INFO),
    ],
)
def test_applies_configured_log_level_to_root_and_structlog(
    structlog_harness,
    log_level,
    expected_level,
):
    config.setup_observability(log_level=log_level)

    assert logging.getLogger().level == expected_level
    assert structlog_harness.filtering_levels == [expected_level]

def test_configures_default_framework_loggers(structlog_harness):
    config.setup_observability(log_level="ERROR")

    root_handler = logging.getLogger().handlers[0]

    for logger_name, expected_level in MANAGED_LOGGERS.items():
        logger = logging.getLogger(logger_name)
        assert logger.handlers == [root_handler]
        assert logger.level == expected_level
        assert logger.propagate is False

def test_extra_loggers_can_override_defaults(structlog_harness):
    config.setup_observability(
        log_level="ERROR",
        extra_loggers={
            "uvicorn.access": {"level": logging.DEBUG},
            "custom.logger": {"level": logging.CRITICAL},
        },
    )

    root_handler = logging.getLogger().handlers[0]

    assert logging.getLogger("uvicorn.access").handlers == [root_handler]
    assert logging.getLogger("uvicorn.access").level == logging.DEBUG
    assert logging.getLogger("uvicorn.access").propagate is False
    assert logging.getLogger("custom.logger").handlers == [root_handler]
    assert logging.getLogger("custom.logger").level == logging.CRITICAL
    assert logging.getLogger("custom.logger").propagate is False

def test_extra_logger_without_level_uses_configured_level(structlog_harness):
    config.setup_observability(
        log_level="ERROR",
        extra_loggers={"custom.logger": {}},
    )

    assert logging.getLogger("custom.logger").level == logging.ERROR