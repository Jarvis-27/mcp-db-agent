"""ASGI middleware that mints or propagates a request ID on every request."""

import re
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

# Allow only safe characters in a client-supplied X-Request-ID (max 64 chars)
_SAFE_PATTERN = re.compile(r"^[a-zA-Z0-9\-_.]{1,64}$")


def _sanitise_request_id(raw: str) -> str:
    """Return raw if it matches the safe pattern, otherwise mint a new UUID4."""
    if _SAFE_PATTERN.match(raw):
        return raw
    return str(uuid.uuid4())


class RequestIDMiddleware:
    """Read X-Request-ID from incoming headers (sanitised) or mint a UUID4.

    Stores the ID in request_id_var (ContextVar) for structured logging.
    Passes the ID back in the X-Request-ID response header.
    """

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        # Extract X-Request-ID from headers
        request_id = str(uuid.uuid4())
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                request_id = _sanitise_request_id(value.decode("utf-8", errors="replace"))
                break

        token = request_id_var.set(request_id)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_header)
        finally:
            request_id_var.reset(token)
