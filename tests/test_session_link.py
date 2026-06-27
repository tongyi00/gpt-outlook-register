import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from session_link_gen import core as session_link_core
from webui import app as web_app
from webui import db
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


class SessionLinkControllerAccountTests(unittest.TestCase):
    def with_db(self, callback):
        with tempfile.TemporaryDirectory() as td:
            test_db = Path(td) / "webui.db"
            connections = []

            def open_conn():
                con = sqlite3.connect(str(test_db), check_same_thread=False, timeout=30)
                con.row_factory = sqlite3.Row
                connections.append(con)
                return con

            try:
                with patch.object(db, "_conn", side_effect=open_conn):
                    db.init_db()
                    callback()
            finally:
                for con in connections:
                    con.close()

    def wait_for_account(self, email, predicate, timeout=3):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = db.get_session_link_account(email)
            if last and predicate(last):
                return last
            time.sleep(0.02)
        self.fail(f"account {email} did not reach expected state; last={last}")

    def wait_for_batch(self, controller, timeout=3):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with controller._lock:
                running = controller._account_state.get("running")
            if not running:
                return
            time.sleep(0.02)
        self.fail(f"batch did not stop; state={controller._account_state}")

    def save_registered_and_import(self, email="a@example.com", token="token-a"):
        db.save_registered({"email": email, "access_token": token})
        db.import_session_link_accounts([email])

    def success_result(self, url="https://www.paypal.com/agreements/approve?ba_token=BA-ok"):
        return {
            "long_url": url,
            "stripe_amount": "0",
            "stripe_amount_source": "total_summary.due",
            "target_amount": "0",
            "amount_matched": True,
        }

    def test_import_registered_imports_accounts_without_exposing_tokens(self):
        def run():
            controller = SessionLinkController()
            db.save_registered({"email": "a@example.com", "access_token": "secret-token"})

            result = controller.import_registered([" A@example.com "])
            accounts = controller.accounts()["items"]

            self.assertTrue(result["ok"])
            self.assertEqual(result["imported"], 1)
            self.assertNotIn("secret-token", str(result))
            self.assertNotIn("access_token", accounts[0])
            self.assertNotIn("secret-token", str(accounts))
            self.assertEqual(accounts[0]["email"], "a@example.com")
            self.assertEqual(accounts[0]["status"], "pending")

        self.with_db(run)

    def test_accounts_masks_proxy_passwords_in_public_fields(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            db.update_session_link_account(
                "a@example.com",
                status="retry_wait",
                proxy_url="http://user:secretpw@proxy.example:8080",
                error="failed via http://user:secretpw@proxy.example:8080",
            )

            accounts = controller.accounts()["items"]

            self.assertEqual(accounts[0]["proxy_url"], "http://user:***@proxy.example:8080")
            self.assertNotIn("secretpw", str(accounts))

        self.with_db(run)

    def test_run_selected_starts_background_job_and_returns_running_status(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            entered = threading.Event()
            release = threading.Event()

            def fake_generate(access_token, mode, proxy_url="", target_amount="0", stage_callback=None):
                entered.set()
                release.wait(2)
                return self.success_result()

            with patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })

                self.assertTrue(result["ok"])
                self.assertTrue(result["running"])
                self.assertEqual(result["status"], "running")
                self.assertTrue(entered.wait(1))
                release.set()
                self.wait_for_account("a@example.com", lambda row: row["status"] == "done")
                self.wait_for_batch(controller)

        self.with_db(run)

    def test_status_reflects_running_account_batch(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            entered = threading.Event()
            release = threading.Event()

            def fake_generate(access_token, mode, proxy_url="", target_amount="0", stage_callback=None):
                entered.set()
                release.wait(2)
                return self.success_result()

            with patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                self.assertTrue(result["ok"])
                self.assertTrue(entered.wait(1))
                try:
                    state = controller.status()
                    self.assertTrue(state["running"])
                    self.assertEqual(state["status"], "running")
                finally:
                    release.set()
                    self.wait_for_batch(controller)

        self.with_db(run)

    def test_reset_is_rejected_while_account_batch_is_running(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            entered = threading.Event()
            release = threading.Event()

            def fake_generate(access_token, mode, proxy_url="", target_amount="0", stage_callback=None):
                entered.set()
                release.wait(2)
                return self.success_result()

            with patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                self.assertTrue(result["ok"])
                self.assertTrue(entered.wait(1))
                try:
                    reset = controller.reset(["a@example.com"])
                    row = db.get_session_link_account("a@example.com")
                    self.assertFalse(reset["ok"])
                    self.assertIn("运行", reset["error"])
                    self.assertEqual(row["status"], "create_checkout")
                    self.assertEqual(row["collision_count"], 1)
                finally:
                    release.set()
                    self.wait_for_batch(controller)

        self.with_db(run)

    def test_delete_is_rejected_while_account_batch_is_running(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            entered = threading.Event()
            release = threading.Event()

            def fake_generate(access_token, mode, proxy_url="", target_amount="0", stage_callback=None):
                entered.set()
                release.wait(2)
                return self.success_result()

            with patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                self.assertTrue(result["ok"])
                self.assertTrue(entered.wait(1))
                try:
                    deleted = controller.delete(["a@example.com"])
                    row = db.get_session_link_account("a@example.com")
                    self.assertFalse(deleted["ok"])
                    self.assertIn("运行", deleted["error"])
                    self.assertIsNotNone(row)
                    self.assertEqual(row["status"], "create_checkout")
                finally:
                    release.set()
                    self.wait_for_batch(controller)

        self.with_db(run)

    def test_reset_does_not_interleave_with_run_selected_after_guard(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            reset_entered = threading.Event()
            release_reset = threading.Event()
            run_returned = threading.Event()
            results = {}

            def fake_reset(_emails):
                reset_entered.set()
                release_reset.wait(2)
                return 1

            def do_reset():
                results["reset"] = controller.reset(["a@example.com"])

            def do_run():
                results["run"] = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                run_returned.set()

            with patch.object(db, "reset_session_link_accounts", side_effect=fake_reset), \
                    patch("webui.session_link.generate_payment_link", return_value=self.success_result()):
                reset_thread = threading.Thread(target=do_reset)
                reset_thread.start()
                self.assertTrue(reset_entered.wait(1))
                run_thread = threading.Thread(target=do_run)
                run_thread.start()
                try:
                    self.assertFalse(run_returned.wait(0.1))
                finally:
                    release_reset.set()
                    reset_thread.join(1)
                    run_thread.join(1)
                    if run_returned.is_set():
                        self.wait_for_batch(controller)

            self.assertFalse(reset_thread.is_alive())
            self.assertFalse(run_thread.is_alive())
            self.assertTrue(results["reset"]["ok"])
            self.assertTrue(results["run"]["ok"])

        self.with_db(run)

    def test_delete_does_not_interleave_with_run_selected_after_guard(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            delete_entered = threading.Event()
            release_delete = threading.Event()
            run_returned = threading.Event()
            results = {}

            def fake_delete(_emails):
                delete_entered.set()
                release_delete.wait(2)
                return 1

            def do_delete():
                results["delete"] = controller.delete(["a@example.com"])

            def do_run():
                results["run"] = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                run_returned.set()

            with patch.object(db, "delete_session_link_accounts", side_effect=fake_delete), \
                    patch("webui.session_link.generate_payment_link", return_value=self.success_result()):
                delete_thread = threading.Thread(target=do_delete)
                delete_thread.start()
                self.assertTrue(delete_entered.wait(1))
                run_thread = threading.Thread(target=do_run)
                run_thread.start()
                try:
                    self.assertFalse(run_returned.wait(0.1))
                finally:
                    release_delete.set()
                    delete_thread.join(1)
                    run_thread.join(1)
                    if run_returned.is_set():
                        self.wait_for_batch(controller)

            self.assertFalse(delete_thread.is_alive())
            self.assertFalse(run_thread.is_alive())
            self.assertTrue(results["delete"]["ok"])
            self.assertTrue(results["run"]["ok"])

        self.with_db(run)

    def test_unhandled_account_worker_exception_marks_batch_failed(self):
        controller = SessionLinkController()

        with patch.object(controller, "_run_account_loop", side_effect=RuntimeError("worker exploded")):
            result = controller.run_selected({
                "emails": ["a@example.com"],
                "payment_mode": "PayPal 长链接 US/USD",
                "delay_seconds": 0,
            })
            self.assertTrue(result["ok"])
            self.wait_for_batch(controller)

        with controller._lock:
            state = dict(controller._account_state)
        self.assertFalse(state["running"])
        self.assertEqual(state["status"], "failed")
        self.assertIn("worker exploded", state["last_error"])
        public_state = controller.status()
        self.assertFalse(public_state["running"])
        self.assertEqual(public_state["status"], "failed")
        self.assertIn("worker exploded", public_state["last_error"])

    def test_run_selected_marks_missing_token_account(self):
        def run():
            controller = SessionLinkController()
            db.save_registered({"email": "missing@example.com", "access_token": ""})
            db.import_session_link_accounts(["missing@example.com"])

            with patch("webui.session_link.generate_payment_link") as mocked:
                result = controller.run_selected({
                    "emails": ["missing@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                self.assertTrue(result["ok"])
                row = self.wait_for_account("missing@example.com", lambda item: item["status"] == "missing_token")
                self.wait_for_batch(controller)

            mocked.assert_not_called()
            self.assertEqual(row["collision_count"], 0)

        self.with_db(run)

    def test_unusable_proxy_pool_retries_without_increasing_collision_count(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()

            with patch("webui.session_link.pick_random_usable_proxy", return_value="") as choose, \
                    patch("webui.session_link.generate_payment_link") as mocked:
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "proxy_pool": "http://user:pass@proxy.example:8080",
                    "delay_seconds": 1,
                })
                self.assertTrue(result["ok"])
                row = self.wait_for_account("a@example.com", lambda item: item["status"] == "retry_wait")
                controller.stop()
                self.wait_for_account("a@example.com", lambda item: item["status"] == "stopped")
                self.wait_for_batch(controller)

            choose.assert_called()
            mocked.assert_not_called()
            self.assertEqual(row["collision_count"], 0)

        self.with_db(run)

    def test_create_checkout_stage_increments_collision_count(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            entered = threading.Event()
            release = threading.Event()

            def fake_generate(access_token, mode, proxy_url="", target_amount="0", stage_callback=None):
                stage_callback("create_checkout")
                entered.set()
                release.wait(2)
                return self.success_result()

            with patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                self.assertTrue(result["ok"])
                self.assertTrue(entered.wait(1))
                row = db.get_session_link_account("a@example.com")
                self.assertEqual(row["status"], "create_checkout")
                self.assertEqual(row["collision_count"], 1)
                release.set()
                self.wait_for_account("a@example.com", lambda item: item["status"] == "done")
                self.wait_for_batch(controller)

        self.with_db(run)

    def test_stop_after_two_failed_collisions_marks_account_failed(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            calls = 0

            def fake_generate(access_token, mode, proxy_url="", target_amount="0", stage_callback=None):
                nonlocal calls
                calls += 1
                raise RuntimeError("collision")

            with patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                    "stop_after": 2,
                })
                self.assertTrue(result["ok"])
                row = self.wait_for_account("a@example.com", lambda item: item["status"] == "failed")
                self.wait_for_batch(controller)

            self.assertEqual(calls, 2)
            self.assertEqual(row["collision_count"], 2)
            self.assertIn("达到停止次数", row["error"])

        self.with_db(run)

    def test_success_writes_account_long_url_and_registered_payment_link(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            long_url = "https://www.paypal.com/agreements/approve?ba_token=BA-success"

            with patch("webui.session_link.generate_payment_link", return_value=self.success_result(long_url)):
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                self.assertTrue(result["ok"])
                row = self.wait_for_account("a@example.com", lambda item: item["status"] == "done")
                self.wait_for_batch(controller)

            registered = db.get_registered("a@example.com")
            self.assertEqual(row["long_url"], long_url)
            self.assertEqual(registered["payment_link"], long_url)

        self.with_db(run)

    def test_stop_prevents_retry_after_current_step(self):
        def run():
            controller = SessionLinkController()
            self.save_registered_and_import()
            calls = 0

            def fake_generate(access_token, mode, proxy_url="", target_amount="0", stage_callback=None):
                nonlocal calls
                calls += 1
                controller.stop()
                raise RuntimeError("temporary failure")

            with patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
                result = controller.run_selected({
                    "emails": ["a@example.com"],
                    "payment_mode": "PayPal 长链接 US/USD",
                    "delay_seconds": 0,
                })
                self.assertTrue(result["ok"])
                row = self.wait_for_account("a@example.com", lambda item: item["status"] == "stopped")
                self.wait_for_batch(controller)

            self.assertEqual(calls, 1)
            self.assertEqual(row["collision_count"], 1)
            self.assertNotEqual(row["status"], "retry_wait")

        self.with_db(run)


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
