"""Request body size cap applied before any route parses the body."""

from app.config import get_settings
from app.errors import ApiError, error_response


class BodySizeLimitMiddleware:
    """Rejects bodies above `max_request_bytes` with 413.

    At the ASGI layer because FastAPI spools multipart forms before any handler
    runs. Plain ASGI for the same reason as `SecurityHeadersMiddleware`."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = get_settings().max_request_bytes
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > limit:
                    response = error_response(413, "request_too_large", "request_too_large")
                    await response(scope, receive, send)
                    return
                break

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise ApiError(413, "request_too_large", "request_too_large")
            return message

        await self.app(scope, limited_receive, send)
