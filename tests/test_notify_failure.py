"""Testy e-mailového upozornenia – lokálny falošný SMTP server, nič sa reálne neodosiela."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notify_failure as nf  # noqa: E402


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


class NotifyTests(unittest.TestCase):
    def setUp(self):
        FakeSMTP.instances = []
        p = mock.patch.object(nf.smtplib, "SMTP_SSL", FakeSMTP)
        p.start()
        self.addCleanup(p.stop)

    def test_missing_credentials_is_noop(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(nf.main(), 0)
        self.assertEqual(FakeSMTP.instances, [])

    def test_sends_mail_with_log_tail_and_run_url(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "run.log"
            log.write_text("\n".join(f"riadok {i}" for i in range(100))
                           + "\nopenai.APIStatusError: Error code: 402", encoding="utf-8")
            env = {
                "GMAIL_USER": "bot@gmail.com",
                "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
                "RUN_URL": "https://github.com/x/y/actions/runs/1",
                "LOG_FILE": str(log),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(nf.main(), 0)

        smtp = FakeSMTP.instances[0]
        self.assertEqual((smtp.host, smtp.port), ("smtp.gmail.com", 465))
        self.assertEqual(smtp.logged_in, ("bot@gmail.com", "abcdefghijklmnop"))
        msg = smtp.sent[0]
        self.assertEqual(msg["To"], "bot@gmail.com")
        self.assertIn("nevygenerovala", msg["Subject"])
        body = msg.get_content()
        self.assertIn("actions/runs/1", body)
        self.assertIn("Error code: 402", body)
        self.assertNotIn("riadok 0\n", body)   # len posledné riadky

    def test_notify_email_overrides_recipient(self):
        env = {"GMAIL_USER": "bot@gmail.com", "GMAIL_APP_PASSWORD": "x",
               "NOTIFY_EMAIL": "ine@gmail.com"}
        with mock.patch.dict(os.environ, env, clear=True):
            nf.main()
        self.assertEqual(FakeSMTP.instances[0].sent[0]["To"], "ine@gmail.com")

    def test_smtp_error_returns_1(self):
        env = {"GMAIL_USER": "bot@gmail.com", "GMAIL_APP_PASSWORD": "x"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(nf.smtplib, "SMTP_SSL", side_effect=OSError("boom")):
            self.assertEqual(nf.main(), 1)


if __name__ == "__main__":
    unittest.main()
