import unittest
from unittest.mock import patch

from webui import app as web_app


class CustomSmsApiTests(unittest.TestCase):
    def test_custom_sms_accounts_api_returns_pool_items(self):
        rows = [{
            "phone": "+8613800138000",
            "api_url": "https://api.example.test/a",
            "status": "available",
            "imported_at": 1782460000.0,
        }]
        with patch.object(web_app.db, "list_custom_sms_accounts", return_value=rows) as mocked:
            result = web_app.api_custom_sms_accounts(status="available", limit=25)

        self.assertEqual(result, {"ok": True, "items": rows})
        mocked.assert_called_once_with(status="available", limit=25)

    def test_custom_sms_reset_api_resets_phone(self):
        with patch.object(web_app.db, "reset_custom_sms_to_available", return_value=True) as mocked:
            result = web_app.api_custom_sms_reset("+8613800138000")

        self.assertEqual(result, {"ok": True, "phone": "+8613800138000"})
        mocked.assert_called_once_with("+8613800138000")

    def test_custom_sms_delete_api_deletes_phone(self):
        with patch.object(web_app.db, "delete_custom_sms_account", return_value=True) as mocked:
            result = web_app.api_custom_sms_delete("+8613800138000")

        self.assertEqual(result, {"ok": True, "phone": "+8613800138000"})
        mocked.assert_called_once_with("+8613800138000")

    def test_custom_sms_reset_all_api_resets_every_phone(self):
        with patch.object(web_app.db, "reset_all_custom_sms_to_available", return_value=3) as mocked:
            result = web_app.api_custom_sms_reset_all()

        self.assertEqual(result, {"ok": True, "reset": 3})
        mocked.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
