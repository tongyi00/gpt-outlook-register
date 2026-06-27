import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from mail_cf import CFTempEmailProvider


class FakeCFTempEmailProvider(CFTempEmailProvider):
    def __init__(self, mails):
        self._mails = mails

    def _get_mails(self, email):
        return list(self._mails)


class CFTempEmailOtpTests(unittest.TestCase):
    def test_create_mailbox_can_disable_worker_prefix(self):
        provider = CFTempEmailProvider(
            api_url="https://mail.example.test",
            admin_token="token",
            domain="example.test",
            enable_prefix=False,
        )
        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.text = '{"address":"alice123@example.test","jwt":"jwt-token"}'
        fake_response.json.return_value = {
            "address": "alice123@example.test",
            "jwt": "jwt-token",
        }

        with patch("mail_cf._gen_local_part", return_value="alice123"), \
                patch.object(provider, "_request", return_value=fake_response) as request:
            self.assertEqual(provider.create_mailbox(), "alice123@example.test")

        request.assert_called_once_with(
            "POST",
            "/admin/new_address",
            json={
                "enablePrefix": False,
                "name": "alice123",
                "domain": "example.test",
            },
            timeout=15,
        )

    def test_accepts_same_second_mail_after_issued_after_boundary(self):
        created = datetime(2026, 6, 26, 2, 21, 50, tzinfo=timezone.utc)
        issued_after = created.timestamp() + 0.8
        provider = FakeCFTempEmailProvider([
            {
                "id": 962,
                "created_at": "2026-06-26 02:21:50",
                "raw": "\r\n\r\n<html><span>890228</span></html>",
            }
        ])

        with patch("mail_cf.time.time", side_effect=[issued_after] * 10 + [issued_after + 61]), \
                patch("mail_cf.time.sleep", return_value=None):
            self.assertEqual(
                provider.wait_for_otp("tmp@example.com", timeout=60, issued_after=issued_after),
                "890228",
            )

    def test_ignores_mail_older_than_grace_window(self):
        created = datetime(2026, 6, 26, 2, 21, 30, tzinfo=timezone.utc)
        issued_after = created.timestamp() + 20
        provider = FakeCFTempEmailProvider([
            {
                "id": 961,
                "created_at": "2026-06-26 02:21:30",
                "raw": "\r\n\r\n<html><span>111222</span></html>",
            }
        ])

        with patch("mail_cf.time.time", side_effect=[issued_after] * 20 + [issued_after + 61]), \
                patch("mail_cf.time.sleep", return_value=None):
            with self.assertRaises(TimeoutError):
                provider.wait_for_otp("tmp@example.com", timeout=60, issued_after=issued_after)

    def test_request_post_falls_back_to_urllib_when_curl_session_fails(self):
        class FailingSession:
            def post(self, *args, **kwargs):
                raise RuntimeError("curl failed")

        provider = CFTempEmailProvider(
            api_url="https://mail.example.test",
            admin_token="token",
            domain="example.test",
            session=FailingSession(),
        )
        fake_response = Mock()
        fake_response.status = 200
        fake_response.read.return_value = b'{"ok":true}'
        fake_response.__enter__ = Mock(return_value=fake_response)
        fake_response.__exit__ = Mock(return_value=False)

        with patch("mail_cf.urllib.request.urlopen", return_value=fake_response):
            resp = provider._request(
                "POST",
                "/admin/new_address",
                json={"name": "tmp", "domain": "example.test"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})


if __name__ == "__main__":
    unittest.main()
