import threading
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from typing import Optional

_init_lock = threading.Lock()
_trace_provider: Optional[TracerProvider] = None

def _build_sampler(sampler_ratio: float = 1.0) -> ParentBased:
    return ParentBased(root=TraceIdRatioBased(sampler_ratio))

def init_telemetry(
        service_name: str,
        environment: str,
        endpoint: str,
        protocol: str = "http/protobuf",
        sampler_ratio: float = 1.0,
        service_version: str = "1.0.0",
        insecure: bool = True
) -> None:
    """
    Initializes OpenTelemetry with a flexible OTLP exporter (HTTP or gRPC).
    """
    global _trace_provider
    if _trace_provider is not None:
        return

    with _init_lock:
        if _trace_provider is not None:
            return

        resource = Resource.create(
            {
                "service.name": service_name,
                "deployment.environment": environment,
                "service.version": service_version
            }
        )

        provider = TracerProvider(resource=resource, sampler=_build_sampler(sampler_ratio))

        if protocol.lower() == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCExporter
            exporter = GRPCExporter(endpoint=endpoint, insecure=insecure)
        else:
            exporter = HTTPExporter(endpoint=endpoint)

        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _trace_provider = provider

def shutdown_telemetry() -> None:
    global _trace_provider
    if _trace_provider is not None:
        _trace_provider.shutdown()
        _trace_provider = None