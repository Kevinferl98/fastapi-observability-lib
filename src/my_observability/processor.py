from opentelemetry import trace
from typing import Any, Dict

def inject_opentelemetry_context(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    span = trace.get_current_span()
    if span is None:
        return event_dict

    span_ctx = span.get_span_context()
    if span_ctx and span_ctx.is_valid:
        event_dict["trace_id"] = f"{span_ctx.trace_id:032x}"
        event_dict["span_id"] = f"{span_ctx.span_id:016x}"
        event_dict["trace_flags"] = f"{span_ctx.trace_flags:02x}"
        
    return event_dict