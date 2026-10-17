"""Limit real received bytes before FastAPI materializes JSON, including chunked bodies."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int, max_admissions: int = 36) -> None:
        self.app, self.max_bytes = app, max_bytes
        self.max_admissions = max_admissions
        self.active_admissions = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        admission = scope["type"] == "http" and scope.get("method") in (
            "POST",
            "PUT",
            "PATCH",
        )
        if admission and self.active_admissions >= self.max_admissions:
            await JSONResponse(
                {"detail": "Admission capacity full"}, 503, headers={"Retry-After": "5"}
            )(scope, receive, send)
            return
        if admission:
            self.active_admissions += 1
        try:
            await self._bounded(scope, receive, send)
        finally:
            if admission:
                self.active_admissions -= 1

    async def _bounded(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if b"content-length" in headers:
            try:
                length = int(headers[b"content-length"])
                if length < 0:
                    raise ValueError
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length"}, 400)(
                    scope, receive, send
                )
                return
            if length > self.max_bytes:
                await JSONResponse({"detail": "Request body too large"}, 413)(
                    scope, receive, send
                )
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await JSONResponse({"detail": "Request body too large"}, 413)(
                    scope, receive, send
                )
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def limited_receive() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, limited_receive, send)
