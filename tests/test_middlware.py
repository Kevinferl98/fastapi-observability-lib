import uuid
import pytest
from types import SimpleNamespace
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from my_observability import middleware

class RecordingLogger:
    def __init__(self):
        self.calls = []

    def info(self, event, **payload):
        self.calls.append(("info", event, payload))

    def warning(self, event, **payload):
        self.calls.append(("warning", event, payload))

    def error(self, event, **payload):
        self.calls.append(("error", event, payload))

    def exception(self, event, **payload):
        self.calls.append(("exception", event, payload))

@pytest.fixture
def recording_logger(monkeypatch):
    logger = RecordingLogger()
    monkeypatch.setattr(middleware, "logger", logger)
    return logger

@pytest.fixture
def contextvars_spy(monkeypatch):
    calls = {"clear": 0, "bind": []}

    def clear_contextvars():
        calls["clear"] += 1

    def bind_contextvars(**kwargs):
        calls["bind"].append(kwargs)

    monkeypatch.setattr(
        middleware.structlog.contextvars,
        "clear_contextvars",
        clear_contextvars,
    )
    monkeypatch.setattr(
        middleware.structlog.contextvars,
        "bind_contextvars",
        bind_contextvars,
    )
    return calls

@pytest.fixture
def app():
    test_app = FastAPI()

    @test_app.get("/ok")
    async def ok(request: Request):
        return {"request_id": request.state.request_id}

    @test_app.get("/client-error")
    async def client_error():
        return Response(status_code=404)

    @test_app.get("/server-error")
    async def server_error():
        return Response(status_code=500)

    @test_app.get("/runtime-error")
    async def runtime_error():
        raise RuntimeError("runtime-error")

    middleware.setup_http_logging(test_app)
    return test_app

def test_sanitize_headers_redacts_sensitive_values_case_insensitively():
    assert middleware._sanitize_headers(
        {
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
            "Set-Cookie": "session=secret",
            "X-Api-Key": "secret-api-key",
            "TOKEN": "secret-token",
            "X-Correlation-Id": "public-value",
        }
    ) == {
        "authorization": "[REDACTED]",
        "cookie": "[REDACTED]",
        "set-cookie": "[REDACTED]",
        "x-api-key": "[REDACTED]",
        "token": "[REDACTED]",
        "x-correlation-id": "public-value",
    }

def test_successful_request_logs_sanitized_payload_and_propagates_request_id(
    app,
    contextvars_spy,
    monkeypatch,
    recording_logger,
):
    perf_counter_values = [10.0, 10.12345]

    def perf_counter():
        if len(perf_counter_values) > 1:
            return perf_counter_values.pop(0)
        return perf_counter_values[0]

    monkeypatch.setattr(middleware, "time", SimpleNamespace(perf_counter=perf_counter))

    response = TestClient(app).get(
        "/ok?search=value",
        headers={
            "X-Request-Id": "req-123",
            "Authorization": "Bearer secret",
            "X-Api-Key": "secret-api-key",
            "X-Correlation-Id": "public-value",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"request_id": "req-123"}
    assert response.headers["x-request-id"] == "req-123"
    assert contextvars_spy == {
        "clear": 1,
        "bind": [{"request_id": "req-123", "method": "GET", "path": "/ok"}],
    }
    assert len(recording_logger.calls) == 1
    level, event, payload = recording_logger.calls[0]
    assert level == "info"
    assert event == "http_request_completed"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 123.45
    assert payload["client_ip"] == "testclient"
    assert payload["query_string"] == "search=value"
    assert {
        "authorization": "[REDACTED]",
        "x-api-key": "[REDACTED]",
        "x-correlation-id": "public-value",
        "x-request-id": "req-123",
    }.items() <= payload["request_headers"].items()

@pytest.mark.parametrize(
    ("path", "expected_level", "expected_status_code"),
    [
        ("/ok", "info", 200),
        ("/client-error", "warning", 404),
        ("/server-error", "error", 500),
    ],
)
def test_completed_request_log_level_depends_on_status_code(
    app,
    recording_logger,
    path,
    expected_level,
    expected_status_code,
):
    response = TestClient(app).get(path, headers={"X-Request-Id": "req-status"})

    assert response.status_code == expected_status_code
    assert recording_logger.calls[-1][0] == expected_level
    assert recording_logger.calls[-1][1] == "http_request_completed"
    assert recording_logger.calls[-1][2]["status_code"] == expected_status_code

def test_missing_request_id_generates_uuid(monkeypatch, recording_logger):
    generated_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(middleware.uuid, "uuid4", lambda: generated_uuid)

    test_app = FastAPI()

    @test_app.get("/generated")
    async def generated(request: Request):
        return {"request_id": request.state.request_id}

    test_app.add_middleware(middleware.StructuredLoggingMiddleware)

    response = TestClient(test_app).get("/generated")

    assert response.status_code == 200
    assert response.json() == {"request_id": str(generated_uuid)}
    assert response.headers["x-request-id"] == str(generated_uuid)
    assert recording_logger.calls[0][2]["request_headers"].get("x-request-id") is None

def test_failed_request_logs_exception_payload_and_reraises(
    app,
    recording_logger,
):
    with pytest.raises(RuntimeError, match="runtime-error"):
        TestClient(app).get(
            "/runtime-error",
            headers={
                "X-Request-Id": "req-failed",
                "Authorization": "Bearer secret",
            },
        )

    assert len(recording_logger.calls) == 1
    level, event, payload = recording_logger.calls[0]
    assert level == "exception"
    assert event == "http_request_failed"
    assert payload["duration_ms"] >= 0
    assert payload["client_ip"] == "testclient"
    assert payload["exception_message"] == "runtime-error"
    assert {
        "x-request-id": "req-failed",
        "authorization": "[REDACTED]",
    }.items() <= payload["request_headers"].items()

def test_setup_http_logging_registers_structured_logging_middleware():
    test_app = FastAPI()

    middleware.setup_http_logging(test_app)

    assert len(test_app.user_middleware) == 1
    assert test_app.user_middleware[0].cls is middleware.StructuredLoggingMiddleware