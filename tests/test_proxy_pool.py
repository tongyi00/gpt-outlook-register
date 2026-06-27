import unittest
from unittest.mock import patch

from fastapi import HTTPException

from webui import app as web_app
from webui.auto_loop import AutoLoopController
from webui.proxy_pool import pick_random_usable_proxy


class ProxyPoolSelectionTests(unittest.TestCase):
    def test_pick_random_usable_proxy_skips_unusable_proxies(self):
        checked = []

        def fake_tester(proxy):
            checked.append(proxy)
            return proxy == "http://proxy-good"

        proxies = ["http://proxy-bad-1", "http://proxy-good", "http://proxy-bad-2"]
        with patch("webui.proxy_pool.random.shuffle", side_effect=lambda items: items.reverse()):
            proxy = pick_random_usable_proxy(proxies, tester=fake_tester)

        self.assertEqual(proxy, "http://proxy-good")
        self.assertEqual(checked, ["http://proxy-bad-2", "http://proxy-good"])

    def test_single_register_picks_random_usable_proxy_from_pool(self):
        pool = """
        # comment
        socks5://127.0.0.1:1001

        socks5://127.0.0.1:1002
        """
        proxy = web_app._pick_proxy_from_pool(
            pool,
            tester=lambda p: p == "socks5://127.0.0.1:1002",
        )

        self.assertEqual(proxy, "socks5://127.0.0.1:1002")

    def test_single_register_rejects_unusable_proxy_pool_before_claiming_account(self):
        req = web_app.RegisterReq(proxy_pool="http://proxy-bad")

        with patch.object(web_app.db, "get_setting", return_value="outlook"), \
                patch.object(web_app, "_pick_proxy_from_pool", return_value="") as choose, \
                patch.object(web_app.db, "claim_next") as claim_next, \
                patch.object(web_app.registrar, "start_registration") as start_registration:
            with self.assertRaises(HTTPException) as ctx:
                web_app.api_register(req)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("代理池没有可用代理", str(ctx.exception.detail))
        choose.assert_called_once()
        claim_next.assert_not_called()
        start_registration.assert_not_called()

    def test_auto_loop_picks_random_proxy_for_each_account_run(self):
        ctrl = AutoLoopController()
        ctrl._proxy_pool = ["http://proxy-a", "http://proxy-b"]
        ctrl._options = {"cool_down_seconds": 0}
        accounts = [
            {"email": "a@example.test", "password": "", "client_id": "", "refresh_token": ""},
            {"email": "b@example.test", "password": "", "client_id": "", "refresh_token": ""},
        ]
        started_options = []

        def fake_start(_account, options):
            started_options.append(dict(options))
            return f"run-{len(started_options)}"

        def fake_wait(_run_id):
            if len(started_options) >= 2:
                ctrl._stop_event.set()
            return True, ""

        with patch("webui.auto_loop.pick_random_usable_proxy", side_effect=["http://proxy-b", "http://proxy-a"]) as choose, \
                patch("webui.auto_loop.db.get_setting", return_value="outlook"), \
                patch("webui.auto_loop.db.claim_next", side_effect=accounts), \
                patch("webui.auto_loop.db.stats", return_value={}), \
                patch("webui.auto_loop.registrar.start_registration", side_effect=fake_start), \
                patch.object(ctrl, "_wait_run_finish", side_effect=fake_wait):
            ctrl._worker_loop(0)

        self.assertEqual([opts.get("proxy") for opts in started_options], ["http://proxy-b", "http://proxy-a"])
        self.assertEqual(choose.call_count, 2)

    def test_auto_loop_proxy_helper_skips_unusable_pool_entries(self):
        ctrl = AutoLoopController()
        ctrl._proxy_pool = ["http://proxy-bad", "http://proxy-good"]
        ctrl._options = {}

        proxy = ctrl._proxy_for_worker(
            0,
            tester=lambda p: p == "http://proxy-good",
        )

        self.assertEqual(proxy, "http://proxy-good")

    def test_auto_loop_manual_proxy_bypasses_proxy_pool_check(self):
        ctrl = AutoLoopController()
        ctrl._proxy_pool = ["http://proxy-bad"]
        ctrl._options = {"proxy": "http://manual"}

        with patch("webui.auto_loop.pick_random_usable_proxy") as choose:
            proxy = ctrl._proxy_for_worker(0)

        self.assertEqual(proxy, "http://manual")
        choose.assert_not_called()

    def test_auto_loop_does_not_claim_account_when_proxy_pool_has_no_usable_proxy(self):
        ctrl = AutoLoopController()
        ctrl._proxy_pool = ["http://proxy-bad"]
        ctrl._options = {"cool_down_seconds": 0}

        def stop_after_sleep(_seconds):
            ctrl._stop_event.set()

        with patch("webui.auto_loop.pick_random_usable_proxy", return_value="") as choose, \
                patch("webui.auto_loop.db.claim_next") as claim_next, \
                patch("webui.auto_loop.registrar.start_registration") as start_registration, \
                patch("webui.auto_loop.time.sleep", side_effect=stop_after_sleep):
            ctrl._worker_loop(0)

        choose.assert_called_once_with(["http://proxy-bad"], tester=None)
        claim_next.assert_not_called()
        start_registration.assert_not_called()


if __name__ == "__main__":
    unittest.main()
