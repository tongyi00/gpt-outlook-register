import unittest

from webui.registrar import classify_error


class RegistrarErrorClassificationTests(unittest.TestCase):
    def test_cf_temp_otp_timeout_is_account_like(self):
        self.assertEqual(
            classify_error("CFTempEmail OTP timeout 180s for tmp@example.com"),
            "account",
        )

    def test_sentinel_challenge_failure_is_network_like(self):
        self.assertEqual(
            classify_error("Sentinel challenge 获取失败：本轮 token 无服务端 challenge"),
            "network",
        )


if __name__ == "__main__":
    unittest.main()
