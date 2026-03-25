import json
import logging
import os
import sys
from datetime import datetime, timezone

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.trace import Span
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def current_trace_fields() -> dict:
    span = trace.get_current_span()
    return span_context_fields(span)


def span_context_fields(span: Span | None) -> dict:
    if span is None:
        return {}

    context = span.get_span_context()
    if not context.is_valid:
        return {}

    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
    }


def emit_event(logger: logging.Logger, service: str, event: str, **fields) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": fields.pop("level", "info"),
        "service": service,
        "event": event,
    }
    payload.update(current_trace_fields())
    payload.update(fields)
    logger.info(json.dumps(payload, sort_keys=True))


def request_trace_fields(request) -> dict:
    trace_context = getattr(request.state, "trace_context", None)
    if trace_context:
        return trace_context

    trace_id = request.scope.get("otel_trace_id")
    span_id = request.scope.get("otel_span_id")
    if trace_id and span_id:
        return {"trace_id": trace_id, "span_id": span_id}
    return current_trace_fields()


def capture_request_trace(request) -> dict:
    fields = request_trace_fields(request)
    if fields:
        request.state.trace_context = fields
    return fields


def configure_tracing(app: FastAPI, service_name: str, engine) -> bool:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not endpoint:
        return False

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name})
    )
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    def server_request_hook(span: Span, scope: dict) -> None:
        scope.update(span_context_fields(span))

    FastAPIInstrumentor.instrument_app(
        app,
        server_request_hook=server_request_hook,
    )
    SQLAlchemyInstrumentor().instrument(engine=engine)
    return True
