import unittest
import asyncio
import logging

from webui import app as web_app


class FakeQueue:
    def __init__(self):
        self.get_called = False
        self.get_nowait_called = False

    def get(self, timeout=None):
        self.get_called = True
        return "blocking-value"

    def get_nowait(self):
        self.get_nowait_called = True
        return "fast-value"


class AppShutdownTests(unittest.TestCase):
    def test_safe_get_uses_nonblocking_get_nowait(self):
        q = FakeQueue()

        value = web_app._safe_get(q)

        self.assertEqual(value, "fast-value")
        self.assertTrue(q.get_nowait_called)
        self.assertFalse(q.get_called)

    def test_quiet_cancelled_middleware_swallows_http_cancelled_error(self):
        async def cancelled_app(scope, receive, send):
            raise asyncio.CancelledError("Task cancelled, timeout graceful shutdown exceeded")

        middleware = web_app.QuietCancelledMiddleware(cancelled_app)

        async def run():
            await middleware({"type": "http", "path": "/api/auto/stream"}, None, None)

        asyncio.run(run())

    def test_shutdown_noise_filter_suppresses_uvicorn_graceful_timeout_message(self):
        record = logging.LogRecord(
            name="uvicorn.error",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Cancel 1 running task(s), timeout graceful shutdown exceeded",
            args=(),
            exc_info=None,
        )

        self.assertFalse(web_app._UvicornShutdownNoiseFilter().filter(record))

    def test_shutdown_noise_filter_suppresses_cancelled_error_traceback(self):
        try:
            raise asyncio.CancelledError("Task cancelled, timeout graceful shutdown exceeded")
        except asyncio.CancelledError as e:
            record = logging.LogRecord(
                name="uvicorn.error",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Exception in ASGI application",
                args=(),
                exc_info=(type(e), e, e.__traceback__),
            )

        self.assertFalse(web_app._UvicornShutdownNoiseFilter().filter(record))


if __name__ == "__main__":
    unittest.main()
