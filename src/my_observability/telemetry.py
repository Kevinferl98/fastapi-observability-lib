from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

_provider = None

def _build_sampler(sampler_type: str = "parentbased_traceidratio", sampler_arg: float = 1.0):
    # Keep parent sampling decisions across service boundaries to avoid
    # partial traces when requests span multiple services.
    if sampler_type == "parentbased_traceidratio":
        return ParentBased(TraceIdRatioBased(sampler_arg))
    if sampler_type == "traceidratio":
        return TraceIdRatioBased(sampler_arg)
    return ParentBased(TraceIdRatioBased(1.0))


def setup_telemetry(app, enabled: bool, service_name: str, environment: str, endpoint: str) -> None:
    global _provider
    if not enabled:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
            "service.version": "1.0.0",
        }
    )

    provider = TracerProvider(resource=resource, sampler=_build_sampler())
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    _provider = provider


def shutdown_telemetry() -> None:
    if _provider is not None:
        # Flush pending spans before process shutdown to avoid trace loss.
        _provider.shutdown()