import os
import unittest
from unittest.mock import Mock, patch

from auth_flow import AuthFlow
from config import Config


def build_cf_about_you_flow():
    flow = AuthFlow(Config())
    flow.check_proxy = Mock(return_value=True)
    flow.get_csrf_token = Mock(return_value="csrf")
    flow.get_auth_url = Mock(return_value="https://auth.openai.com/api/accounts/authorize?client_id=x")
    flow.auth_oauth_init = Mock(return_value="device-id")
    flow.get_sentinel_token = Mock(return_value="sentinel")
    flow.signup = Mock(return_value=False)
    flow._existing_email_verification_mode = "passwordless_signup"
    flow._existing_page_type = "email_otp_verification"
    flow.kickoff_otp_delivery = Mock(return_value=True)
    flow.verify_otp = Mock(return_value={"continue_url": "https://auth.openai.com/about-you"})
    flow.fetch_client_auth_session_dump = Mock(return_value={})
    flow._reauthorize_for_session = Mock(return_value="https://chatgpt.com/api/auth/callback/openai?code=c&state=s")
    flow.oauth_codex_rt_exchange = Mock(return_value=False)
    flow.follow_redirect_chain = Mock(return_value=("https://chatgpt.com/api/auth/callback/openai?code=c&state=s", "https://chatgpt.com/"))
    flow._consume_callback_for_session = Mock(return_value=None)
    flow.get_auth_session = Mock(side_effect=lambda: (
        setattr(flow.result, "access_token", "at"),
        setattr(flow.result, "session_token", "st"),
    ))

    provider = Mock()
    provider._outlook_creds = None
    provider.outlook_exhausted = False
    provider.is_cf_temp = True
    provider.create_mailbox.return_value = "cf@example.test"
    provider.wait_for_otp.return_value = "123456"
    return flow, provider


class AuthFlowCfPathTests(unittest.TestCase):
    def test_cf_existing_about_you_defaults_to_create_account(self):
        flow, provider = build_cf_about_you_flow()
        flow.create_account = Mock(return_value="https://chatgpt.com/api/auth/callback/openai?code=c&state=s")

        with patch.dict(os.environ, {}, clear=True):
            result = flow.run_register(provider)

        self.assertEqual(result.access_token, "at")
        self.assertEqual(result.session_token, "st")
        flow.create_account.assert_called_once()

    def test_cf_existing_about_you_can_explicitly_skip_create_account(self):
        flow, provider = build_cf_about_you_flow()
        flow.create_account = Mock(side_effect=AssertionError("CF path should not create account"))

        with patch.dict(os.environ, {"CF_TEMP_REAUTHORIZE_INSTEAD_OF_CREATE": "1"}, clear=False):
            result = flow.run_register(provider)

        self.assertEqual(result.access_token, "at")
        self.assertEqual(result.session_token, "st")
        flow.create_account.assert_not_called()
        flow._reauthorize_for_session.assert_called()


if __name__ == "__main__":
    unittest.main()
