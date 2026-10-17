import asyncio

import pytest
from starlette.responses import Response

from app.core.body_limit import BodyLimitMiddleware


@pytest.mark.asyncio
async def test_concurrent_admission_is_bounded_before_body_receive():
    entered, released = asyncio.Event(), asyncio.Event()

    async def slow_receive():
        entered.set()
        await released.wait()
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def application(scope, receive, send):
        await receive()
        await Response(status_code=202)(scope, receive, send)

    middleware = BodyLimitMiddleware(application, max_bytes=100, max_admissions=1)
    scope = {"type": "http", "method": "POST", "headers": []}
    first_messages, second_messages = [], []

    async def first_send(message):
        first_messages.append(message)

    async def second_send(message):
        second_messages.append(message)

    first = asyncio.create_task(middleware(scope, slow_receive, first_send))
    await entered.wait()
    # The second request must be rejected without waiting for or reading body.
    await asyncio.wait_for(middleware(scope, slow_receive, second_send), 1)
    assert second_messages[0]["status"] == 503
    released.set()
    await first
    assert first_messages[0]["status"] == 202
    assert middleware.active_admissions == 0
