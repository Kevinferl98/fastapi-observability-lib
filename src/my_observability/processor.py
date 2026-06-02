from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id
from typing import Any, Dict

def inject_opentelemetry_context(_: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Structlog processor that injects OpenTelemetry trace context into the event dict.

    Extracts trace_id, span_id, and trace_flags from the current active span
    and formats them according to standard hexadecimal representations.
    """
    span = trace.get_current_span()
    if span is None:
        return event_dict

    span_ctx = span.get_span_context()
    # OpenTelemetry trace_id and span_id are only valid if a trace is actively recording
    if span_ctx and span_ctx.is_valid:
        event_dict["trace_id"] = format_trace_id(span_ctx.trace_id)
        event_dict["span_id"] = format_span_id(span_ctx.span_id)
        event_dict["trace_flags"] = f"{span_ctx.trace_flags:02x}"
        
    return event_dict