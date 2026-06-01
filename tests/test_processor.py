import pytest
from dataclasses import dataclass
from my_observability import processor

@dataclass(frozen=True)
class FakeSpanContext:
    trace_id: int
    span_id: int
    trace_flags: int
    is_valid: bool

class FakeSpan:
    def __init__(self, span_context):
        self._span_context = span_context

    def get_span_context(self):
        return self._span_context

@pytest.mark.parametrize("current_span", [None, FakeSpan(None)])
def test_inject_opentelemetry_context_returns_event_unchanged_without_context(
    monkeypatch,
    current_span,
):
    event_dict = {"event": "request.completed", "existing": "value"}
    monkeypatch.setattr(processor.trace, "get_current_span", lambda: current_span)

    result = processor.inject_opentelemetry_context(None, None, event_dict)

    assert result is event_dict
    assert result == {"event": "request.completed", "existing": "value"}

def test_inject_opentelemetry_context_ignores_invalid_span_context(monkeypatch):
    event_dict = {"event": "request.completed"}
    invalid_span_context = FakeSpanContext(
        trace_id=0x123,
        span_id=0x456,
        trace_flags=0x01,
        is_valid=False,
    )
    monkeypatch.setattr(
        processor.trace,
        "get_current_span",
        lambda: FakeSpan(invalid_span_context),
    )

    result = processor.inject_opentelemetry_context(None, None, event_dict)

    assert result is event_dict
    assert result == {"event": "request.completed"}

def test_inject_opentelemetry_context_adds_zero_padded_hex_identifiers(monkeypatch):
    event_dict = {"event": "request.completed"}
    valid_span_context = FakeSpanContext(
        trace_id=0xABCDEF,
        span_id=0x12345,
        trace_flags=0x01,
        is_valid=True,
    )
    monkeypatch.setattr(
        processor.trace,
        "get_current_span",
        lambda: FakeSpan(valid_span_context),
    )

    result = processor.inject_opentelemetry_context(None, None, event_dict)

    assert result is event_dict
    assert result == {
        "event": "request.completed",
        "trace_id": "00000000000000000000000000abcdef",
        "span_id": "0000000000012345",
        "trace_flags": "01",
    }

def test_inject_opentelemetry_context_preserves_existing_fields(monkeypatch):
    event_dict = {
        "event": "request.completed",
        "trace_id": "previous-trace-id",
        "span_id": "previous-span-id",
        "trace_flags": "previous-trace-flags",
    }
    valid_span_context = FakeSpanContext(
        trace_id=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        span_id=0xFFFFFFFFFFFFFFFF,
        trace_flags=0x00,
        is_valid=True,
    )
    monkeypatch.setattr(
        processor.trace,
        "get_current_span",
        lambda: FakeSpan(valid_span_context),
    )

    result = processor.inject_opentelemetry_context(None, None, event_dict)

    assert result is event_dict
    assert result == {
        "event": "request.completed",
        "trace_id": "ffffffffffffffffffffffffffffffff",
        "span_id": "ffffffffffffffff",
        "trace_flags": "00",
    }