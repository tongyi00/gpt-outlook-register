import json
import unittest
from unittest.mock import Mock, patch

from auth_flow import AuthFlow
from config import Config


class AuthFlowSentinelTests(unittest.TestCase):
    def test_get_sentinel_token_rejects_no_challenge_fallback(self):
        flow = AuthFlow(Config())
        flow.session = Mock()
        fallback = json.dumps({
            "p": "gAAAAACdummy",
            "t": "",
            "c": "",
            "id": "device-id",
            "flow": "authorize_continue",
        })

        with patch("sentinel.get_sentinel_token", return_value=fallback), \
                patch("auth_flow.time.sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Sentinel challenge 获取失败"):
                flow.get_sentinel_token("device-id")

    def test_get_sentinel_token_retries_transient_fallback(self):
        flow = AuthFlow(Config())
        flow.session = Mock()
        fallback = json.dumps({
            "p": "gAAAAACdummy",
            "t": "",
            "c": "",
            "id": "device-id",
            "flow": "authorize_continue",
        })
        valid = json.dumps({
            "p": "gAAAAABdummy",
            "t": "1",
            "c": "server-challenge",
            "id": "device-id",
            "flow": "authorize_continue",
        })

        with patch("sentinel.get_sentinel_token", side_effect=[fallback, valid]) as get_token, \
                patch("auth_flow.time.sleep", return_value=None):
            self.assertEqual(flow.get_sentinel_token("device-id"), valid)

        self.assertEqual(get_token.call_count, 2)


if __name__ == "__main__":
    unittest.main()
