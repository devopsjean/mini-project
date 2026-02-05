from fastapi import FastAPI, Request, Response, HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import asyncio
import time

app = FastAPI(title="mini-project-api")

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


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    # Measure end-to-end request handling time within the app
    # (from the moment the request enters FastAPI to the response completion).
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start

    # Export request metrics for Prometheus scraping
    path = request.url.path
    method = request.method
    status = str(response.status_code)

    REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
    REQUEST_LATENCY.labels(method=method, path=path).observe(elapsed)

    return response


@app.get("/")
def root():
    return {"message": "hello from api"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    # Prometheus scrapes this endpoint periodically to collect time-series metrics.
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/slow")
async def slow(ms: int = 300):
    # Intentional latency injection endpoint
    # - Used to validate latency SLI/SLO (e.g., p95) behavior and alerting.
    await asyncio.sleep(ms / 1000.0)
    return {"status": "ok", "delay_ms": ms}


@app.get("/error")
def error(code: int = 500):
    # Intentional 5xx error injection endpoint
    # - Used to validate error-rate SLI behavior and alert firing.
    # - Guardrail: only allow 5xx. If a non-5xx is provided, fallback to 500.
    if code < 500 or code > 599:
        code = 500
    raise HTTPException(status_code=code, detail=f"intentional {code} error")
