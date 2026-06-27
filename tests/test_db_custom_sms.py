import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webui import db


class KeepOpenConnection(sqlite3.Connection):
    def close(self):
        pass

    def real_close(self):
        super().close()


class CustomSmsDbTests(unittest.TestCase):
    def test_list_custom_sms_accounts_returns_imported_phone_pool(self):
        with tempfile.TemporaryDirectory() as td:
            test_db = Path(td) / "webui.db"
            con = sqlite3.connect(
                str(test_db),
                check_same_thread=False,
                timeout=30,
                factory=KeepOpenConnection,
            )
            con.row_factory = sqlite3.Row
            try:
                with patch.object(db, "_conn", return_value=con):
                    db.init_db()
                    db.import_custom_sms_accounts(
                        "+8613800138000----https://api.example.test/a\n"
                        "+8613900139000----https://api.example.test/b"
                    )

                    items = db.list_custom_sms_accounts()

                    by_phone = {item["phone"]: item for item in items}
                    self.assertEqual(set(by_phone), {"+8613800138000", "+8613900139000"})
                    self.assertEqual(by_phone["+8613800138000"]["status"], "available")
                    self.assertEqual(by_phone["+8613800138000"]["api_url"], "https://api.example.test/a")
                    self.assertEqual(by_phone["+8613800138000"]["success_count"], 0)
                    self.assertIn("imported_at", by_phone["+8613800138000"])
            finally:
                con.real_close()

    def test_list_custom_sms_accounts_filters_by_status(self):
        with tempfile.TemporaryDirectory() as td:
            test_db = Path(td) / "webui.db"
            con = sqlite3.connect(
                str(test_db),
                check_same_thread=False,
                timeout=30,
                factory=KeepOpenConnection,
            )
            con.row_factory = sqlite3.Row
            try:
                with patch.object(db, "_conn", return_value=con):
                    db.init_db()
                    db.import_custom_sms_accounts(
                        "+8613800138000----https://api.example.test/a\n"
                        "+8613900139000----https://api.example.test/b"
                    )
                    db.mark_custom_sms_failed("+8613900139000", "no code")

                    items = db.list_custom_sms_accounts(status="failed")

                    self.assertEqual([item["phone"] for item in items], ["+8613900139000"])
                    self.assertEqual(items[0]["fail_reason"], "no code")
            finally:
                con.real_close()

    def test_custom_sms_success_count_only_increments_on_done_and_survives_reset(self):
        with tempfile.TemporaryDirectory() as td:
            test_db = Path(td) / "webui.db"
            con = sqlite3.connect(
                str(test_db),
                check_same_thread=False,
                timeout=30,
                factory=KeepOpenConnection,
            )
            con.row_factory = sqlite3.Row
            try:
                with patch.object(db, "_conn", return_value=con):
                    db.init_db()
                    db.import_custom_sms_accounts("+8613800138000----https://api.example.test/a")

                    db.mark_custom_sms_failed("+8613800138000", "send failed")
                    self.assertEqual(db.get_custom_sms_account("+8613800138000")["success_count"], 0)

                    db.reset_custom_sms_to_available("+8613800138000")
                    db.mark_custom_sms_done("+8613800138000")
                    row = db.get_custom_sms_account("+8613800138000")
                    self.assertEqual(row["status"], "done")
                    self.assertEqual(row["success_count"], 1)

                    db.reset_custom_sms_to_available("+8613800138000")
                    row = db.get_custom_sms_account("+8613800138000")
                    self.assertEqual(row["status"], "available")
                    self.assertEqual(row["success_count"], 1)
            finally:
                con.real_close()

    def test_delete_custom_sms_account_removes_phone(self):
        with tempfile.TemporaryDirectory() as td:
            test_db = Path(td) / "webui.db"
            con = sqlite3.connect(
                str(test_db),
                check_same_thread=False,
                timeout=30,
                factory=KeepOpenConnection,
            )
            con.row_factory = sqlite3.Row
            try:
                with patch.object(db, "_conn", return_value=con):
                    db.init_db()
                    db.import_custom_sms_accounts("+8613800138000----https://api.example.test/a")

                    self.assertTrue(db.delete_custom_sms_account("+8613800138000"))
                    self.assertIsNone(db.get_custom_sms_account("+8613800138000"))
                    self.assertFalse(db.delete_custom_sms_account("+8613800138000"))
            finally:
                con.real_close()

    def test_reset_all_custom_sms_to_available_resets_statuses_and_keeps_success_count(self):
        with tempfile.TemporaryDirectory() as td:
            test_db = Path(td) / "webui.db"
            con = sqlite3.connect(
                str(test_db),
                check_same_thread=False,
                timeout=30,
                factory=KeepOpenConnection,
            )
            con.row_factory = sqlite3.Row
            try:
                with patch.object(db, "_conn", return_value=con):
                    db.init_db()
                    db.import_custom_sms_accounts(
                        "+8613800138000----https://api.example.test/a\n"
                        "+8613900139000----https://api.example.test/b\n"
                        "+8615000150000----https://api.example.test/c"
                    )
                    db.mark_custom_sms_failed("+8613800138000", "send failed")
                    db.mark_custom_sms_done("+8613900139000")
                    claimed = db.claim_custom_sms_phone()
                    self.assertEqual(claimed["phone"], "+8615000150000")

                    reset = db.reset_all_custom_sms_to_available()

                    self.assertEqual(reset, 3)
                    rows = {
                        item["phone"]: item
                        for item in db.list_custom_sms_accounts()
                    }
                    self.assertEqual({row["status"] for row in rows.values()}, {"available"})
                    self.assertEqual(rows["+8613900139000"]["success_count"], 1)
                    for row in rows.values():
                        self.assertIsNone(row["fail_reason"])
                        self.assertIsNone(row["claimed_at"])
                        self.assertIsNone(row["finished_at"])
            finally:
                con.real_close()


if __name__ == "__main__":
    unittest.main()
