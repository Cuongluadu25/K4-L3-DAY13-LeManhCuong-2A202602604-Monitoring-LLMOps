from __future__ import annotations

import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

# Correlation ID hợp lệ theo contract: req-<8 ký tự hex>
REQUEST_ID_PATTERN = re.compile(r"^req-[0-9a-f]{8}$")


def _new_correlation_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Xóa context cũ để không rò rỉ correlation ID giữa các request
        clear_contextvars()

        # Nhận x-request-id nếu đúng format, ngược lại sinh ID mới
        incoming = request.headers.get("x-request-id")
        if incoming and REQUEST_ID_PATTERN.match(incoming):
            correlation_id = incoming
        else:
            correlation_id = _new_correlation_id()

        # Bind vào structlog contextvars để mọi log trong request dùng chung ID
        bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)

        response.headers["x-request-id"] = correlation_id
        response.headers["x-response-time-ms"] = str(int((time.perf_counter() - start) * 1000))

        return response
