import unittest
from unittest.mock import Mock

from auth_flow import AuthFlow
from config import Config


class AuthFlowCreateAccountTests(unittest.TestCase):
    def test_auth_context_summary_does_not_leak_cookie_values(self):
        flow = AuthFlow(Config())
        flow._existing_page_type = "email_otp_verification"
        flow._existing_email_verification_mode = "passwordless_signup"
        flow._client_auth_session_dump = {
            "client_auth_session": {
                "email": "cf@example.test",
                "signup_mode": "email_signup",
                "signup_source": "",
                "email_verified": True,
            }
        }

        cookie = Mock()
        cookie.name = "oai-client-auth-session"
        cookie.value = "secret-cookie-value"
        cookie.domain = ".auth.openai.com"
        flow.session = Mock()
        flow.session.cookies = Mock()
        flow.session.cookies.jar = [cookie]

        summary = flow._auth_context_summary()

        self.assertIn("email=cf@example.test", summary)
        self.assertIn("signup_mode=email_signup", summary)
        self.assertIn("oai-client-auth-session=Y(len=19,domains=.auth.openai.com)", summary)
        self.assertNotIn("secret-cookie-value", summary)

    def test_create_account_runs_about_you_preflight_before_post(self):
        flow = AuthFlow(Config())
        flow.result.device_id = ""
        flow._last_sentinel_token = "sentinel"
        flow._trace_http = Mock()

        preflight = Mock()
        preflight.status_code = 200
        preflight.headers = {}
        preflight.url = "https://auth.openai.com/about-you"

        post_resp = Mock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"continue_url": "https://chatgpt.com/callback"}
        post_resp.headers = {}

        flow.session = Mock()
        flow.session.get.return_value = preflight
        flow.session.post.return_value = post_resp
        flow.session.cookies = {}

        self.assertEqual(flow.create_account(), "https://chatgpt.com/callback")

        flow.session.get.assert_called_once()
        flow.session.post.assert_called_once()
        method_names = [c[0] for c in flow.session.method_calls]
        self.assertLess(method_names.index("get"), method_names.index("post"))


if __name__ == "__main__":
    unittest.main()
