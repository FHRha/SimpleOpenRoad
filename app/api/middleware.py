"""HTTP middleware for request tracing and logging context."""

from __future__ import annotations

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.observability.logging import get_logger


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.logger = get_logger("gateway.http")

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000
        response.headers["x-request-id"] = request_id
        container = getattr(request.app.state, "container", None)
        request_log_enabled = True
        if container is not None:
            request_log_enabled = container.runtime_config.get().observability.request_log
        if request_log_enabled:
            self.logger.info(
                "http request",
                extra={
                    "request_id": request_id,
                    "route_alias": request.url.path,
                    "model": request.method,
                },
            )
        response.headers["x-latency-ms"] = f"{latency_ms:.2f}"
        return response
