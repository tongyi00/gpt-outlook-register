import io
import unittest
import urllib.error
from unittest.mock import patch

from mail_outlook import OutlookMailProvider, OutlookOAuthError, get_outlook_access_token


class OutlookOAuthTests(unittest.TestCase):
    def test_token_http_400_raises_non_retryable_error_with_body(self):
        body = b'{"error":"invalid_grant","error_description":"refresh token expired"}'
        err = urllib.error.HTTPError(
            url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(body),
        )

        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(OutlookOAuthError) as cm:
                get_outlook_access_token("rt", "cid")

        msg = str(cm.exception)
        self.assertIn("invalid_grant", msg)
        self.assertIn("refresh token expired", msg)
        self.assertTrue(cm.exception.non_retryable)

    def test_wait_for_otp_marks_outlook_dead_on_oauth_error(self):
        provider = OutlookMailProvider(
            email="bad@example.com",
            password="p",
            client_id="cid",
            refresh_token="rt",
        )

        with patch(
            "mail_outlook.fetch_otp_via_imap",
            side_effect=OutlookOAuthError("invalid_grant", status=400),
        ):
            with self.assertRaisesRegex(RuntimeError, "Outlook OAuth"):
                provider.wait_for_otp("bad@example.com", timeout=90)

        self.assertTrue(provider.outlook_exhausted)


if __name__ == "__main__":
    unittest.main()
