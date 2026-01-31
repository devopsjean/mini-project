from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time

app = FastAPI(title="mini-project-api")

# Metrics
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
    start = time.time()
    response = await call_next(request)

    elapsed = time.time() - start
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
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

import asyncio
from fastapi import HTTPException

@app.get("/slow")
async def slow(ms: int = 300):
    # 의도적 지연(ms)
    await asyncio.sleep(ms / 1000.0)
    return {"status": "ok", "delay_ms": ms}

@app.get("/error")
def error(code: int = 500):
    # 의도적 5xx 오류 (기본 500)
    if code < 500 or code > 599:
        code = 500
    raise HTTPException(status_code=code, detail=f"intentional {code} error")
