import json
import unittest

from sentinel import is_valid_sentinel_token


class SentinelTokenTests(unittest.TestCase):
    def test_rejects_no_challenge_fallback_token(self):
        token = json.dumps({
            "p": "gAAAAACdummy",
            "t": "",
            "c": "",
            "id": "device-id",
            "flow": "authorize_continue",
        })

        self.assertFalse(is_valid_sentinel_token(token))

    def test_accepts_challenge_token_with_t_and_c(self):
        token = json.dumps({
            "p": "gAAAAABdummy",
            "t": "1",
            "c": "server-challenge",
            "id": "device-id",
            "flow": "authorize_continue",
        })

        self.assertTrue(is_valid_sentinel_token(token))


if __name__ == "__main__":
    unittest.main()
