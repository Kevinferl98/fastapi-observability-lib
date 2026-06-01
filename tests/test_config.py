import io
import logging
import pytest
from types import SimpleNamespace
from my_observability import config
from my_observability.processor import inject_opentelemetry_context

TARGET_LOGGER_NAMES = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "custom.logger",
)

@pytest.fixture(autouse=True)
def restore_logging_state():
    root_logger = logging.getLogger()
    original_root_handlers = list(root_logger.handlers)
    original_root_level = root_logger.level
    original_logger_state = {}

    for logger_name in TARGET_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        original_logger_state[logger_name] = {
            "handlers": list(logger.handlers),
            "level": logger.level,
            "propagate": logger.propagate,
            "handles": getattr(logger, "handles", None),
            "had_handles": hasattr(logger, "handles"),
        }

    yield

    root_logger.handlers = original_root_handlers
    root_logger.setLevel(original_root_level)

    for logger_name, state in original_logger_state.items():
        logger = logging.getLogger(logger_name)
        logger.handlers = state["handlers"]
        logger.setLevel(state["level"])
        logger.propagate = state["propagate"]
        if state["had_handles"]:
            logger.handles = state["handles"]
        elif hasattr(logger, "handles"):
            delattr(logger, "handles")

@pytest.fixture
def structlog_spies(monkeypatch):
    stdout = io.StringIO()
    calls = {
        "basic_config": None,
        "configure": None,
        "filtering_levels": [],
        "print_logger_files": [],
        "formatter_kwargs": [],
        "timestamp_kwargs": [],
        "json_renderer_calls": 0,
    }

    class FakeFilteringBoundLogger:
        pass

    class FakePrintLoggerFactory:
        def __init__(self, file):
            calls["print_logger_files"].append(file)
            self.file = file

    class FakeTimeStamper:
        def __init__(self, **kwargs):
            calls["timestamp_kwargs"].append(kwargs)
            self.kwargs = kwargs

    class FakeJSONRenderer:
        def __init__(self):
            calls["json_renderer_calls"] += 1

    class FakeProcessorFormatter:
        def __init__(self, **kwargs):
            calls["formatter_kwargs"].append(kwargs)
            self.kwargs = kwargs

    def fake_basic_config(**kwargs):
        calls["basic_config"] = kwargs

    def fake_configure(**kwargs):
        calls["configure"] = kwargs

    def fake_make_filtering_bound_logger(level):
        calls["filtering_levels"].append(level)
        return FakeFilteringBoundLogger

    monkeypatch.setattr(config, "sys", SimpleNamespace(stdout=stdout))
    monkeypatch.setattr(config.logging, "basicConfig", fake_basic_config)
    monkeypatch.setattr(config.structlog, "configure", fake_configure)
    monkeypatch.setattr(
        config.structlog,
        "make_filtering_bound_logger",
        fake_make_filtering_bound_logger,
    )
    monkeypatch.setattr(config.structlog, "PrintLoggerFactory", FakePrintLoggerFactory)
    monkeypatch.setattr(config.structlog.processors, "TimeStamper", FakeTimeStamper)
    monkeypatch.setattr(config.structlog.processors, "JSONRenderer", FakeJSONRenderer)
    monkeypatch.setattr(
        config.structlog.stdlib,
        "ProcessorFormatter",
        FakeProcessorFormatter,
    )

    return calls, stdout, FakeFilteringBoundLogger, FakeProcessorFormatter

def test_setup_observability_configures_structlog_processors_in_expected_order(
    structlog_spies,
):
    calls, stdout, fake_filtering_bound_logger, _ = structlog_spies

    config.setup_observability(log_level="debug")

    configure_kwargs = calls["configure"]
    assert configure_kwargs["processors"][:2] == [
        config.structlog.contextvars.merge_contextvars,
        config.structlog.processors.add_log_level,
    ]
    assert isinstance(configure_kwargs["processors"][2], config.structlog.processors.TimeStamper)
    assert configure_kwargs["processors"][3:6] == [
        config.structlog.processors.format_exc_info,
        config.structlog.processors.dict_tracebacks,
        inject_opentelemetry_context,
    ]
    assert isinstance(configure_kwargs["processors"][6], config.structlog.processors.JSONRenderer)
    assert configure_kwargs["wrapper_class"] is fake_filtering_bound_logger
    assert configure_kwargs["logger_factory"].file is stdout
    assert configure_kwargs["cache_logger_on_first_use"] is True
    assert calls["filtering_levels"] == [logging.DEBUG]
    assert calls["timestamp_kwargs"][0] == {"fmt": "iso", "utc": True, "key": "timestamp"}

@pytest.mark.parametrize(
    ("log_level", "expected_level"),
    [
        ("warning", logging.WARNING),
        ("NOT_A_LEVEL", logging.INFO),
    ],
)
def test_setup_observability_configures_basic_logging_level(
    structlog_spies,
    log_level,
    expected_level,
):
    calls, stdout, _, _ = structlog_spies

    config.setup_observability(log_level=log_level)

    assert calls["basic_config"] == {
        "format": "%(message)s",
        "stream": stdout,
        "level": expected_level,
    }
    assert calls["filtering_levels"] == [expected_level]

def test_setup_observability_configures_root_logger_with_structlog_formatter(
    structlog_spies,
):
    calls, stdout, _, fake_processor_formatter = structlog_spies

    config.setup_observability()

    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 1
    handler = root_logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is stdout
    assert isinstance(handler.formatter, fake_processor_formatter)
    assert calls["formatter_kwargs"] == [
        {
            "processor": handler.formatter.kwargs["processor"],
            "foreign_pre_chain": [
                config.structlog.processors.add_log_level,
                handler.formatter.kwargs["foreign_pre_chain"][1],
            ],
        }
    ]
    assert isinstance(
        handler.formatter.kwargs["processor"],
        config.structlog.processors.JSONRenderer,
    )
    assert isinstance(
        handler.formatter.kwargs["foreign_pre_chain"][1],
        config.structlog.processors.TimeStamper,
    )

def test_setup_observability_configures_default_uvicorn_loggers(structlog_spies):
    config.setup_observability(log_level="ERROR")

    root_handler = logging.getLogger().handlers[0]
    expected_levels = {
        "uvicorn": logging.INFO,
        "uvicorn.error": logging.INFO,
        "uvicorn.access": logging.WARNING,
    }

    for logger_name, expected_level in expected_levels.items():
        logger = logging.getLogger(logger_name)
        assert logger.handlers == [root_handler]
        assert logger.level == expected_level
        assert logger.propagate is False

def test_setup_observability_merges_extra_loggers_and_allows_overrides(
    structlog_spies,
):
    config.setup_observability(
        log_level="ERROR",
        extra_loggers={
            "uvicorn.access": {"level": logging.DEBUG},
            "custom.logger": {"level": logging.CRITICAL},
        },
    )

    root_handler = logging.getLogger().handlers[0]
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    custom_logger = logging.getLogger("custom.logger")

    assert uvicorn_access_logger.handlers == [root_handler]
    assert uvicorn_access_logger.level == logging.DEBUG
    assert uvicorn_access_logger.propagate is False
    assert custom_logger.handlers == [root_handler]
    assert custom_logger.level == logging.CRITICAL
    assert custom_logger.propagate is False

def test_extra_logger_without_level_falls_back_to_configured_level(structlog_spies):
    config.setup_observability(
        log_level="ERROR",
        extra_loggers={"custom.logger": {}},
    )

    assert logging.getLogger("custom.logger").level == logging.ERROR