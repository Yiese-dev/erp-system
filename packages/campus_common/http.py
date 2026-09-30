import json
import logging
import logging.handlers
import re
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.campus_common.config import Settings
from packages.campus_common.database import Database
from packages.campus_common.errors import DomainError
from packages.campus_common.schemas import ERROR_RESPONSES

logger = logging.getLogger("campus.requests")
REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict",
         422: "validation", 429: "rate_limited", 503: "unavailable"}


def configure_logging(service: str, log_host: str = "") -> None:
    root = logging.getLogger()
    if getattr(root, "_campus_configured", False):
        return
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stream)
    if log_host:
        host, _, port = log_host.partition(":")
        syslog = logging.handlers.SysLogHandler(address=(host, int(port or 5140)))
        syslog.append_nul = False
        syslog.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(syslog)
    root._campus_configured = True  # type: ignore[attr-defined]


def create_application(settings: Settings, database: Database, lifespan=None) -> FastAPI:
    configure_logging(settings.service, settings.log_host)
    prefix = "/api/v1/auth" if settings.service == "identity" else f"/api/v1/{settings.service}"
    app = FastAPI(title=f"Campus ERP | {settings.service.title()} API", version="1.0.0", lifespan=lifespan,
                  openapi_url=f"{prefix}/openapi.json", docs_url=f"{prefix}/docs", redoc_url=None,
                  responses=ERROR_RESPONSES,
                  description="Versioned under /api/v1. All errors use the documented `error` envelope.")
    app.state.settings = settings
    app.state.database = database
    registry = CollectorRegistry()
    requests = Counter("campus_http_requests_total", "HTTP requests", ["service", "method", "route", "status"], registry=registry)
    duration = Histogram("campus_http_request_seconds", "HTTP duration", ["service", "route"], registry=registry)
    app.state.metrics_registry = registry

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if REQUEST_ID.match(incoming) else str(uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        elapsed = time.perf_counter() - started
        requests.labels(settings.service, request.method, route, response.status_code).inc()
        duration.labels(settings.service, route).observe(elapsed)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.setdefault("Cache-Control", "no-store")
        if not route.endswith(("/health/live", "/health/ready", "/metrics")):
            logger.info(json.dumps({"service": settings.service, "level": "info", "request_id": request.state.request_id,
                                    "method": request.method, "route": route, "status": response.status_code,
                                    "duration_ms": round(elapsed * 1000, 2)}))
        return response

    def error_response(request: Request, status: int, message: str, fields=None, details=None):
        return JSONResponse(status_code=status, content={"error": {
            "code": CODES.get(status, "request_failed"), "message": message, "fields": fields or [],
            "details": details, "request_id": getattr(request.state, "request_id", ""),
        }})

    @app.exception_handler(DomainError)
    async def handle_domain(request: Request, error: DomainError):
        return error_response(request, error.status, error.message, details=error.details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, error: StarletteHTTPException):
        return error_response(request, error.status_code, str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, error: RequestValidationError):
        fields = [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]} for item in error.errors()]
        return error_response(request, 422, "Please check the highlighted fields.", fields)

    @app.exception_handler(IntegrityError)
    async def handle_conflict(request: Request, error: IntegrityError):
        return error_response(request, 409, "This record already exists or is still referenced by another record.")

    def live():
        return {"status": "ok", "service": settings.service}

    def ready():
        try:
            database.ping()
        except SQLAlchemyError as error:
            raise HTTPException(503, "Database is unavailable.") from error
        return {"status": "ready", "service": settings.service}

    for path in ("", prefix):
        app.add_api_route(f"{path}/health/live", live, methods=["GET"], tags=["Health"], include_in_schema=bool(path))
        app.add_api_route(f"{path}/health/ready", ready, methods=["GET"], tags=["Health"], include_in_schema=bool(path))

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return app