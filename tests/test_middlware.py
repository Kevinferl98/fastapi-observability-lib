import logging
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import Response, StreamingResponse
from src.my_observability import middleware

LOGGER_NAME = "my_observability.middleware"

def test_sanitize_headers():
    raw_headers = {
        "Authorization": "Bearer secret_token",
        "Cookie": "session=xyz",
        "Content-Type": "application/json",
        "X-Custom-Header": "not-in-visible-set",
    }
    visible_set = {"content-type"}

    sanitized = middleware._sanitize_headers(raw_headers, visible_set)

    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["cookie"] == "[REDACTED]"
    assert sanitized["content-type"] == "application/json"
    assert "x-custom-header" not in sanitized

@pytest.mark.parametrize(
    "text, max_bytes, expected_text, expected_truncated",
    [
        ("hello", 10, "hello", False),
        ("hello world", 5, "hello", True),
        ("⚡⚡", 3, "⚡", True),
    ],
)
def test_truncate_text(text, max_bytes, expected_text, expected_truncated):
    res_text, truncated = middleware._truncate_text(text, max_bytes)
    assert res_text == expected_text
    assert truncated == expected_truncated

@pytest.mark.parametrize(
    "content_type, expected",
    [
        ("application/json", True),
        ("application/problem+json", True),
        ("text/html", True),
        ("image/jpeg", False),
        (None, False),
    ],
)
def test_is_text_payload(content_type, expected):
    assert middleware._is_text_payload(content_type) == expected

def test_decode_body_binary_payload():
    binary_data = b"\x00\x01\x02\x03"
    text, truncated = middleware._decode_body(binary_data, "application/octet-stream", 100)
    assert text == "[BINARY:4 bytes]"
    assert truncated is False

@pytest.fixture
def app():
    return FastAPI()

def test_middleware_logs_basic_request_without_bodies(app, caplog):
    middleware.setup_http_logging(app, log_bodies=False)

    @app.get("/health")
    def health_check():
        return {"status": "healthy"}

    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = client.get("/health", headers={"X-Request-ID": "external-uuid-123"})

    assert response.status_code == 200

    middleware_logs = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(middleware_logs) == 1

    log_record = middleware_logs[0]
    assert log_record.message == "http_request"

    extra = log_record.__dict__.get("extra", log_record.__dict__)
    assert extra["request_id"] == "external-uuid-123"
    assert extra["path"] == "/health"
    assert extra["status_code"] == 200
    assert "request_body" not in extra

def test_middleware_logs_and_parses_valid_json_bodies(app, caplog):
    middleware.setup_http_logging(app, log_bodies=True, max_body_bytes=512)

    @app.post("/api/v1/data")
    async def process_data(request: Request):
        return {"status": "processed"}

    client = TestClient(app)
    req_payload = {"user_id": 42, "action": "click"}

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.post("/api/v1/data", json=req_payload)

    middleware_logs = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(middleware_logs) == 1

    extra = middleware_logs[0].__dict__
    assert extra["request_body"] == req_payload
    assert extra["response_body"] == {"status": "processed"}
    assert extra["request_body_truncated"] is False
    assert extra["response_body_truncated"] is False

def test_middleware_truncates_payloads_exceeding_max_bytes(app, caplog):
    middleware.setup_http_logging(app, log_bodies=True, max_body_bytes=5)

    @app.post("/echo")
    def echo_text():
        return "test-long-response"

    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.post("/echo", content="test-long-request", headers={"content-type": "text/plain"})

    middleware_logs = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(middleware_logs) == 1
    extra = middleware_logs[0].__dict__

    assert extra["request_body_truncated"] is True
    assert extra["response_body_truncated"] is True

    assert len(extra["request_body"].encode("utf-8")) <= 5
    assert len(extra["response_body"].encode("utf-8")) <= 5

def test_middleware_logs_exception_on_endpoint_crash(app, caplog):
    middleware.setup_http_logging(app, log_bodies=False)

    @app.get("/unhandled-crash")
    def crash():
        raise RuntimeError("Database connection lost")

    client = TestClient(app)

    with pytest.raises(RuntimeError, match="Database connection lost"):
        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            client.get("/unhandled-crash")

    middleware_logs = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(middleware_logs) == 1

    log_record = middleware_logs[0]
    assert log_record.message == "http_request_failed"
    assert log_record.levelname == "ERROR"
    assert log_record.exc_info is not None

def test_middleware_logs_error_level_for_5xx_responses(app, caplog):
    middleware.setup_http_logging(app, log_bodies=False)

    @app.get("/bad-gateway")
    def gateway_error():
        return Response(status_code=502, content="Bad Gateway")

    client = TestClient(app)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        client.get("/bad-gateway")

    middleware_logs = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(middleware_logs) == 1
    assert middleware_logs[0].message == "http_request"
    assert middleware_logs[0].levelname == "ERROR"

def test_middleware_preserves_streaming_responses(app, caplog):
    middleware.setup_http_logging(app, log_bodies=True, max_body_bytes=1024)

    @app.get("/stream")
    def stream_endpoint():
        def chunks():
            yield b"part1 "
            yield b"part2"

        return StreamingResponse(chunks(), media_type="text/plain")

    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = client.get("/stream")

    assert response.status_code == 200
    assert response.text == "part1 part2"

    middleware_logs = [r for r in caplog.records if r.name == LOGGER_NAME]
    extra = middleware_logs[0].__dict__
    assert extra["response_body"] == "part1 part2"