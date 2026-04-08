"""ASGI middleware that rejects requests with Content-Length over a configured limit."""

import json


class BodySizeLimitMiddleware:
    """Reject requests whose Content-Length header exceeds max_bytes.

    Defends against memory abuse on large POST bodies (e.g. POST /v1/users/register
    with a multi-megabyte payload).

    Note: this only checks Content-Length — it does not buffer the body.
    Chunked-encoded requests without a Content-Length header are not rejected
    here; that is handled at the reverse proxy layer in production.
    """

    def __init__(self, app, max_bytes: int = 65536) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            for name, value in scope.get("headers", []):
                if name.lower() == b"content-length":
                    try:
                        length = int(value)
                    except ValueError:
                        length = 0
                    if length > self._max_bytes:
                        body = json.dumps(
                            {
                                "detail": (
                                    f"Request body too large. "
                                    f"Maximum allowed: {self._max_bytes} bytes."
                                )
                            }
                        ).encode()
                        await send(
                            {
                                "type": "http.response.start",
                                "status": 413,
                                "headers": [
                                    (b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode()),
                                ],
                            }
                        )
                        await send({"type": "http.response.body", "body": body})
                        return
                    break

        await self._app(scope, receive, send)
