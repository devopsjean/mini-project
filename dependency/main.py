import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from observability import (
    build_logger,
    capture_request_trace,
    configure_tracing,
    emit_event,
    request_trace_fields,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://mini_project:mini_project@db:5432/mini_project",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    log_event("service_started", title=app.title)
    yield
    engine.dispose()


app = FastAPI(title="mini-project-dependency", lifespan=lifespan)
configure_tracing(app, service_name="dependency", engine=engine)
app_logger = build_logger("mini_project.dependency")


def log_event(event: str, **fields) -> None:
    emit_event(app_logger, service="dependency", event=event, **fields)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
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

    elapsed_ms = round((time.time() - start) * 1000, 2)
    log_event(
        "request_complete",
        **request_trace_fields(request),
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=elapsed_ms,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
def health(request: Request):
    capture_request_trace(request)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}


@app.get("/item")
def item(request: Request, item_id: int = 1):
    capture_request_trace(request)
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT id, name, category
                    FROM trace_demo_items
                    WHERE id = :item_id
                    """
                ),
                {"item_id": item_id},
            )
            .mappings()
            .first()
        )

    if not row:
        raise HTTPException(status_code=404, detail="item not found")

    log_event(
        "db_item_lookup_completed",
        request_id=request.state.request_id,
        item_id=item_id,
    )
    return dict(row)


@app.get("/slow")
def slow(request: Request, ms: int = 300):
    capture_request_trace(request)
    if ms < 0:
        ms = 0

    delay_seconds = ms / 1000.0
    log_event(
        "db_latency_injection_requested",
        request_id=request.state.request_id,
        delay_ms=ms,
    )

    with engine.connect() as connection:
        connection.execute(
            text("SELECT pg_sleep(:delay_seconds)"),
            {"delay_seconds": delay_seconds},
        )
        item_count = connection.execute(
            text("SELECT COUNT(*) FROM trace_demo_items")
        ).scalar_one()

    return {
        "status": "ok",
        "delay_ms": ms,
        "item_count": item_count,
        "source": "dependency-db",
    }


@app.get("/error")
def error(request: Request, code: int = 500):
    capture_request_trace(request)
    if code < 500 or code > 599:
        code = 500

    log_event(
        "db_failure_injection_requested",
        request_id=request.state.request_id,
        status_code=code,
    )

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT * FROM trace_demo_missing_table"))
    except SQLAlchemyError as exc:
        log_event(
            "dependency_error_raised",
            level="error",
            request_id=request.state.request_id,
            status_code=code,
            error_type=type(exc).__name__,
            failure_mode="db_query",
        )
        raise HTTPException(
            status_code=code,
            detail="downstream dependency failure triggered by db query error",
        ) from exc

    raise HTTPException(status_code=code, detail=f"intentional {code} error")
