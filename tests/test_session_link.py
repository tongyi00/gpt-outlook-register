import time
import unittest
from unittest.mock import patch

from session_link_gen import core as session_link_core
from webui import app as web_app
from webui.session_link import SessionLinkController, result_error


class TestPaymentLinkCoreStages(unittest.TestCase):
    def fake_checkout(self):
        return {
            "cs_id": "cs_test_123",
            "processor_entity": "openai_llc",
            "stripe_publishable_key": "pk_live_test",
            "billing_country": "US",
            "currency": "USD",
        }

    def fake_init_payload(self):
        return {
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test_123",
            "total_summary": {"due": "0"},
            "currency": "usd",
            "config_id": "cfg_test",
            "init_checksum": "checksum_test",
        }

    def test_paypal_mode_emits_payment_generation_stages_in_order(self):
        stages = []

        def callback(stage, message=""):
            stages.append(stage)

        with patch.object(session_link_core, "opll_create_checkout", return_value=self.fake_checkout()), \
                patch.object(session_link_core, "opll_build_stripe_session", return_value=object()), \
                patch.object(session_link_core, "opll_stripe_init", return_value=self.fake_init_payload()), \
                patch.object(session_link_core, "opll_stripe_create_paypal_method", return_value="pm_test"), \
                patch.object(session_link_core, "opll_stripe_confirm", return_value={}), \
                patch.object(
                    session_link_core,
                    "opll_redirect_url_after_confirm",
                    return_value="https://www.paypal.com/agreements/approve?ba_token=BA-test",
                ):
            result = session_link_core.generate_payment_link(
                "token",
                mode="PayPal 长链接 US/USD",
                stage_callback=callback,
            )

        self.assertTrue(result["success"])
        self.assertEqual(stages, ["create_checkout", "stripe_init", "paypal_approve"])

    def test_hosted_mode_emits_checkout_and_stripe_init_stages_only(self):
        stages = []

        def callback(stage, message=""):
            stages.append(stage)

        with patch.object(session_link_core, "opll_create_checkout", return_value=self.fake_checkout()), \
                patch.object(session_link_core, "opll_stripe_init", return_value=self.fake_init_payload()):
            result = session_link_core.generate_payment_link(
                "token",
                mode="无卡长链接 US/USD",
                stage_callback=callback,
            )

        self.assertTrue(result["success"])
        self.assertEqual(stages, ["create_checkout", "stripe_init"])


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
