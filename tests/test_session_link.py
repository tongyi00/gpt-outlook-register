import time
import unittest
from unittest.mock import patch

from webui import app as web_app
from webui.session_link import SessionLinkController, result_error


class SessionLinkControllerTests(unittest.TestCase):
    def test_loop_retries_until_payment_link_is_generated(self):
        controller = SessionLinkController()
        calls = 0

        def fake_generate(access_token, mode, proxy_url="", target_amount="0"):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary failure")
            return {
                "long_url": "https://www.paypal.com/agreements/approve?ba_token=BA-1",
                "stripe_amount": "0",
                "stripe_amount_source": "total_summary.due",
                "target_amount": target_amount,
                "amount_matched": True,
            }

        with patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
            started = controller.start({
                "access_tokens": ["token"],
                "payment_mode": "PayPal 长链接 US/USD",
                "target_amount": "0",
                "thread_count": 1,
                "delay_seconds": 0,
            })
            self.assertTrue(started["ok"])

            for _ in range(50):
                state = controller.status()
                if not state["running"]:
                    break
                time.sleep(0.02)

        state = controller.status()
        self.assertFalse(state["running"])
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["attempt"], 2)
        self.assertEqual(state["success_count"], 1)
        self.assertEqual(state["pending_count"], 0)
        self.assertEqual(calls, 2)
        self.assertEqual(state["results"][0]["long_url"], "https://www.paypal.com/agreements/approve?ba_token=BA-1")

    def test_paypal_mode_requires_ba_approve_url(self):
        err = result_error({
            "ok": True,
            "long_url": "https://checkout.stripe.com/c/pay/cs_test",
            "amount_matched": True,
        }, "PayPal 长链接 US/USD")

        self.assertIn("PayPal BA approve", err)


class SessionLinkApiTests(unittest.TestCase):
    def test_start_api_uses_session_link_controller(self):
        req = web_app.SessionLinkReq(session_text="Bearer token")
        with patch.object(web_app.session_link.CONTROLLER, "start", return_value={"ok": True, "running": True}) as mocked:
            result = web_app.api_session_link_start(req)

        self.assertEqual(result, {"ok": True, "running": True})
        mocked.assert_called_once()

    def test_payment_modes_api_returns_modes(self):
        result = web_app.api_session_link_payment_modes()

        self.assertTrue(result["ok"])
        self.assertIn("PayPal 长链接 US/USD", result["modes"])


if __name__ == "__main__":
    unittest.main()
