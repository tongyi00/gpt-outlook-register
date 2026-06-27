import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from webui import db


class KeepOpenConnection(sqlite3.Connection):
    def close(self):
        pass

    def real_close(self):
        super().close()


class MailConfigTests(unittest.TestCase):
    def test_cf_enable_prefix_is_saved_and_loaded(self):
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
                    self.assertEqual(db.get_mail_config()["cf_enable_prefix"], "1")

                    db.save_mail_config({"cf_enable_prefix": "0"})

                    self.assertEqual(db.get_mail_config()["cf_enable_prefix"], "0")
            finally:
                con.real_close()


if __name__ == "__main__":
    unittest.main()
