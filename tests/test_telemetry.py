import pytest
from unittest.mock import MagicMock, patch
from opentelemetry import trace
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from src.my_observability import telemetry

@pytest.fixture(autouse=True)
def reset_opentelemetry_global_state():
    trace._TRACER_PROVIDER = None
    telemetry._provider = None

    yield

    trace._TRACER_PROVIDER = None
    telemetry._provider = None

@pytest.mark.parametrize(
    "sampler_type, sampler_arg, expected_type, expected_inner_type",
    [
        ("parentbased_traceidratio", 0.5, ParentBased, TraceIdRatioBased),
        ("traceidratio", 0.2, TraceIdRatioBased, None),
        ("unknown_fallback", 1.0, ParentBased, TraceIdRatioBased),
    ],
)
def test_build_sampler_variants(sampler_type, sampler_arg, expected_type, expected_inner_type):
    sampler = telemetry._build_sampler(sampler_type, sampler_arg)
    assert isinstance(sampler, expected_type)
    if expected_inner_type:
        assert isinstance(sampler._root, expected_inner_type)

def test_setup_telemetry_disabled():
    mock_app = MagicMock()

    with patch("src.my_observability.telemetry.Resource") as mock_resource, \
            patch("src.my_observability.telemetry.TracerProvider") as mock_provider:
        telemetry.setup_telemetry(
            app=mock_app,
            enabled=False,
            service_name="test-service",
            environment="production",
            endpoint="localhost:4317"
        )

        mock_resource.create.assert_not_called()
        mock_provider.assert_not_called()
        assert telemetry._provider is None

@patch("src.my_observability.telemetry.FastAPIInstrumentor")
@patch("src.my_observability.telemetry.BatchSpanProcessor")
@patch("src.my_observability.telemetry.OTLPSpanExporter")
@patch("src.my_observability.telemetry.TracerProvider")
@patch("src.my_observability.telemetry.Resource")
def test_setup_telemetry_enabled_success(
        mock_resource,
        mock_tracer_provider,
        mock_exporter,
        mock_processor,
        mock_instrumentor
):
    mock_app = MagicMock()
    mock_resource_instance = MagicMock()
    mock_resource.create.return_value = mock_resource_instance

    mock_provider_instance = MagicMock()
    mock_tracer_provider.return_value = mock_provider_instance

    mock_exporter_instance = MagicMock()
    mock_exporter.return_value = mock_exporter_instance

    mock_processor_instance = MagicMock()
    mock_processor.return_value = mock_processor_instance

    telemetry.setup_telemetry(
        app=mock_app,
        enabled=True,
        service_name="my-service",
        environment="staging",
        endpoint="http://otlp-collector:4317"
    )

    mock_resource.create.assert_called_once_with({
        "service.name": "my-service",
        "deployment.environment": "staging",
        "service.version": "1.0.0",
    })

    mock_tracer_provider.assert_called_once()
    kwargs = mock_tracer_provider.call_args[1]
    assert kwargs["resource"] == mock_resource_instance
    assert isinstance(kwargs["sampler"], ParentBased)

    mock_exporter.assert_called_once_with(endpoint="http://otlp-collector:4317", insecure=True)
    mock_processor.assert_called_once_with(mock_exporter_instance)
    mock_provider_instance.add_span_processor.assert_called_once_with(mock_processor_instance)

    assert trace.get_tracer_provider() == mock_provider_instance
    assert telemetry._provider == mock_provider_instance
    mock_instrumentor.instrument_app.assert_called_once_with(mock_app)

def test_shutdown_telemetry_when_not_initialized():
    try:
        telemetry.shutdown_telemetry()
    except Exception as e:
        pytest.fail(f"shutdown_telemetry raised an exception: {e}")

def test_shutdown_telemetry_success():
    mock_provider = MagicMock()
    telemetry._provider = mock_provider

    telemetry.shutdown_telemetry()

    mock_provider.shutdown.assert_called_once()