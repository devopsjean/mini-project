import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from observability import (
    build_logger,
    capture_request_trace,
    configure_tracing,
    emit_event,
    request_trace_fields,
)

DEPENDENCY_BASE_URL = os.getenv("DEPENDENCY_BASE_URL", "http://dependency:8081")
DEPENDENCY_TIMEOUT_SECONDS = float(os.getenv("DEPENDENCY_TIMEOUT_SECONDS", "5"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=DEPENDENCY_TIMEOUT_SECONDS)
    log_event("service_started", title=app.title)
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="mini-project-api", lifespan=lifespan)
configure_tracing(app, service_name="api")
app_logger = build_logger("mini_project.api")


def log_event(event: str, **fields) -> None:
    emit_event(app_logger, service="api", event=event, **fields)


# Metrics (Prometheus)
# - http_requests_total:
#   Counter for traffic + error-rate calculations (SLI candidate: Error Rate / Success Rate)
# - http_request_duration_seconds:
#   Histogram for latency quantiles (SLI candidate: p95 latency)
#
# Label design notes:
# - method/path/status are sufficient for this demo.
# - In production, 'path' can cause high-cardinality issues if it includes dynamic segments.
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


async def call_dependency(request: Request, path: str, params: dict) -> httpx.Response:
    client: httpx.AsyncClient = request.app.state.http_client
    request_id = request.state.request_id

    log_event(
        "dependency_request_started",
        request_id=request_id,
        dependency_service="dependency",
        dependency_path=path,
        dependency_params=params,
    )

    try:
        response = await client.get(
            f"{DEPENDENCY_BASE_URL}{path}",
            params=params,
            headers={"X-Request-ID": request_id},
        )
    except httpx.RequestError as exc:
        log_event(
            "dependency_request_failed",
            level="error",
            request_id=request_id,
            dependency_service="dependency",
            dependency_path=path,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="dependency service unavailable",
        ) from exc

    log_event(
        "dependency_request_completed",
        request_id=request_id,
        dependency_service="dependency",
        dependency_path=path,
        dependency_status=response.status_code,
    )
    return response


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    # Measure end-to-end request handling time within the app
    # (from the moment the request enters FastAPI to the response completion).
    start = time.time()
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id

    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        log_event(
            "request_exception",
            level="error",
            **request_trace_fields(request),
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            duration_ms=elapsed_ms,
            client_ip=request.client.host if request.client else None,
            error_type=type(exc).__name__,
        )
        raise

    elapsed = time.time() - start
    elapsed_ms = round(elapsed * 1000, 2)

    # Export request metrics for Prometheus scraping
    path = request.url.path
    method = request.method
    status = str(response.status_code)

    REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
    REQUEST_LATENCY.labels(method=method, path=path).observe(elapsed)

    if path != "/metrics":
        log_event(
            "request_complete",
            **request_trace_fields(request),
            request_id=request_id,
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=elapsed_ms,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/")
def root(request: Request):
    capture_request_trace(request)
    return {"message": "hello from api"}


@app.get("/health")
def health(request: Request):
    capture_request_trace(request)
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    # Prometheus scrapes this endpoint periodically to collect time-series metrics.
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/item")
async def item(request: Request, item_id: int = 1):
    capture_request_trace(request)
    response = await call_dependency(
        request,
        path="/item",
        params={"item_id": item_id},
    )
    return JSONResponse(status_code=response.status_code, content=response.json())


@app.get("/slow")
async def slow(request: Request, ms: int = 300):
    # Intentional latency injection endpoint.
    # - The actual delay now lives in the downstream dependency service / database.
    capture_request_trace(request)
    log_event(
        "latency_injection_requested",
        request_id=request.state.request_id,
        path="/slow",
        delay_ms=ms,
    )
    response = await call_dependency(
        request,
        path="/slow",
        params={"ms": ms},
    )
    return JSONResponse(status_code=response.status_code, content=response.json())


@app.get("/error")
async def error(request: Request, code: int = 500):
    # Intentional 5xx error injection endpoint.
    # - The downstream dependency raises the failure so the error crosses a service boundary.
    capture_request_trace(request)
    if code < 500 or code > 599:
        code = 500
    log_event(
        "error_injection_requested",
        request_id=request.state.request_id,
        path="/error",
        status_code=code,
    )
    response = await call_dependency(
        request,
        path="/error",
        params={"code": code},
    )
    return JSONResponse(status_code=response.status_code, content=response.json())
