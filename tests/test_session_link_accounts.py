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


class SessionLinkAccountsDbTests(unittest.TestCase):
    def with_db(self, callback):
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
                    callback()
            finally:
                con.real_close()

    def test_import_session_link_accounts_uses_email_as_unique_id(self):
        def run():
            db.save_registered({"email": "a@example.com", "access_token": "token-a"})

            first = db.import_session_link_accounts(["A@example.com"])
            second = db.import_session_link_accounts([" a@example.com "])
            rows = db.list_session_link_accounts()

            self.assertEqual(first["imported"], 1)
            self.assertEqual(second["updated"], 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["email"], "a@example.com")
            self.assertEqual(rows[0]["status"], "pending")

        self.with_db(run)

    def test_import_marks_missing_token(self):
        def run():
            db.save_registered({"email": "no-token@example.com", "access_token": ""})

            result = db.import_session_link_accounts(["no-token@example.com"])
            row = db.get_session_link_account("no-token@example.com")

            self.assertEqual(result["missing_token"], 1)
            self.assertEqual(row["status"], "missing_token")

        self.with_db(run)

    def test_missing_token_import_returns_to_pending_after_token_exists(self):
        def run():
            db.save_registered({"email": "a@example.com", "access_token": ""})
            db.import_session_link_accounts(["a@example.com"])
            db.save_registered({"email": "a@example.com", "access_token": "token-a"})

            result = db.import_session_link_accounts(["a@example.com"])
            row = db.get_session_link_account("A@example.com")

            self.assertEqual(result["updated"], 1)
            self.assertEqual(row["status"], "pending")

        self.with_db(run)

    def test_import_does_not_clear_existing_long_url(self):
        def run():
            db.save_registered({"email": "a@example.com", "access_token": "token-a"})
            db.import_session_link_accounts(["a@example.com"])
            db.update_session_link_account(
                "a@example.com",
                status="done",
                long_url="https://pay.example/existing",
            )

            db.import_session_link_accounts(["a@example.com"])
            row = db.get_session_link_account("a@example.com")

            self.assertEqual(row["long_url"], "https://pay.example/existing")

        self.with_db(run)

    def test_payment_link_is_written_back_to_registered(self):
        def run():
            db.save_registered({"email": "a@example.com", "access_token": "token-a"})

            self.assertTrue(db.set_registered_payment_link(" A@example.com ", "https://pay.example/link"))
            row = db.list_registered()[0]

            self.assertEqual(row["payment_link"], "https://pay.example/link")

        self.with_db(run)

    def test_session_link_logs_append_and_list(self):
        def run():
            db.append_session_link_log(" A@example.com ", "info", "import", "Imported")
            db.append_session_link_log("a@example.com", "error", "generate", "Failed")

            rows = db.list_session_link_logs("a@example.com")

            self.assertEqual([row["email"] for row in rows], ["a@example.com", "a@example.com"])
            self.assertEqual([row["kind"] for row in rows], ["info", "error"])
            self.assertEqual([row["stage"] for row in rows], ["import", "generate"])
            self.assertEqual([row["message"] for row in rows], ["Imported", "Failed"])

        self.with_db(run)

    def test_reset_session_link_accounts_resets_selected_rows(self):
        def run():
            db.save_registered({"email": "a@example.com", "access_token": "token-a"})
            db.import_session_link_accounts(["a@example.com"])
            db.update_session_link_account(
                "a@example.com",
                status="failed",
                attempts=3,
                collision_count=2,
                error="bad",
                long_url="https://pay.example/old",
            )

            reset = db.reset_session_link_accounts([" A@example.com "])
            row = db.get_session_link_account("a@example.com")

            self.assertEqual(reset, 1)
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["attempts"], 0)
            self.assertEqual(row["collision_count"], 0)
            self.assertIsNone(row["error"])
            self.assertIsNone(row["long_url"])

        self.with_db(run)

    def test_delete_session_link_accounts_removes_selected_rows(self):
        def run():
            db.save_registered({"email": "a@example.com", "access_token": "token-a"})
            db.save_registered({"email": "b@example.com", "access_token": "token-b"})
            db.import_session_link_accounts(["a@example.com", "b@example.com"])

            deleted = db.delete_session_link_accounts([" A@example.com "])

            self.assertEqual(deleted, 1)
            self.assertIsNone(db.get_session_link_account("a@example.com"))
            self.assertIsNotNone(db.get_session_link_account("b@example.com"))

        self.with_db(run)

    def test_update_session_link_account_persists_key_fields(self):
        def run():
            db.save_registered({"email": "a@example.com", "access_token": "token-a"})
            db.import_session_link_accounts(["a@example.com"])

            updated = db.update_session_link_account(
                " A@example.com ",
                attempts=2,
                collision_count=1,
                status="retry_wait",
                error="temporary failure",
                long_url="https://pay.example/link",
                payment_mode="PayPal",
                target_amount="10",
                proxy_url="http://proxy.example:8080",
            )
            row = db.get_session_link_account("a@example.com")

            self.assertTrue(updated)
            self.assertEqual(row["attempts"], 2)
            self.assertEqual(row["collision_count"], 1)
            self.assertEqual(row["status"], "retry_wait")
            self.assertEqual(row["error"], "temporary failure")
            self.assertEqual(row["long_url"], "https://pay.example/link")
            self.assertEqual(row["payment_mode"], "PayPal")
            self.assertEqual(row["target_amount"], "10")
            self.assertEqual(row["proxy_url"], "http://proxy.example:8080")

        self.with_db(run)


if __name__ == "__main__":
    unittest.main()
