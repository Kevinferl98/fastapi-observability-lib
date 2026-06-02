# FastAPI Observability Lib

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)

A lightweight observability library designed to enforce consistent structured logging, trace context propagation, and request correlation across distributed microservices. 

## What It Provides

* **Structured JSON Logging:** Native integration with `structlog` outputting production-ready JSON to `stdout`.
* **Standard Library Integration:** Intercepts and transforms third-party Python standard logs (e.g., Uvicorn, Django, Celery, Kafka, AMQP) into identical structured JSON formats.
* **Log Correlation:** Automatic OpenTelemetry context injection (`trace_id`, `span_id`, `trace_flags`) into active log events for instant jumps from Logs to Traces.
* **FastAPI ASGI Middleware:** High-performance request tracking, automatic `X-Request-ID` generation/propagation, and latency auditing.
* **Message Broker Support:** Dedicated thread-safe Context Manager for RabbitMQ/Message Workers to prevent context leaks across task cycles.
* **Secured by Default:** Automatic PII and credential scrubbing (`[REDACTED]`) for sensitive HTTP and messaging headers.

## Included Modules

- `my_observability.config`: logging setup and logger configuration
- `my_observability.middleware`: ASGI middleware and RabbitMQ trace context helpers
- `my_observability.processor`: OpenTelemetry context injection for `structlog`
- `my_observability.telemetry`: OpenTelemetry tracer provider bootstrap and shutdown

## Quick Start

Initialize structured logging at application startup:

```python
from my_observability import setup_observability

setup_observability(log_level="INFO")
```

Enable request logging in a FastAPI app:

```python
from fastapi import FastAPI
from my_observability import setup_fastapi_logging

app = FastAPI()
setup_fastapi_logging(app)
```

Initialize OpenTelemetry when you want to export traces:

```python
from my_observability import init_telemetry, shutdown_telemetry

init_telemetry(
    service_name="my-service",
    environment="development",
    endpoint="http://localhost:4318/v1/traces",
)

# later, on shutdown
shutdown_telemetry()
```

## Example Usage

With observability enabled, your application logs are emitted as JSON and enriched with request metadata and trace context when available.

```python
from my_observability import get_logger

logger = get_logger("example")
logger.info("service_started", component="api")
```

For RabbitMQ consumers, the helper can be used to bind request and queue context while processing a message:

```python
from my_observability import rabbitmq_trace_context

headers = {
    "x-request-id": "abc-123",
    "correlation-id": "abc-123",
}

with rabbitmq_trace_context(headers, queue_name="jobs"):
    process_message()
```

## Configuration Notes

- `setup_observability()` accepts a `log_level` and optional `extra_loggers` mapping.
- `setup_fastapi_logging()` installs middleware that adds `x-request-id` to responses when missing.
- Sensitive headers such as `authorization`, `cookie`, and `x-api-key` are redacted from request logs.
- `init_telemetry()` supports OTLP over HTTP by default and gRPC when `protocol="grpc"` is specified.

## Package Name

The importable package is `my_observability`.
