import tempfile, unittest
from pathlib import Path
from synapse.auth import AuthStore, AuthError

class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.auth=AuthStore(Path(self.tmp.name)/"auth.sqlite3")
    def tearDown(self): self.tmp.cleanup()
    def test_signup_creates_session_without_plaintext_token_storage(self):
        s=self.auth.signup("test@example.com","a-very-long-password-123","Test User")
        self.assertTrue(s["token"]);self.assertTrue(s["csrf"])
        self.assertEqual(self.auth.current(s["token"])["user"]["email"],"test@example.com")
        with self.auth.db() as c:
            row=c.execute("SELECT token_hash FROM sessions").fetchone()
            self.assertNotEqual(row["token_hash"],s["token"])
    def test_duplicate_email_rejected(self):
        self.auth.signup("test@example.com","a-very-long-password-123","Test")
        with self.assertRaises(AuthError):self.auth.signup("test@example.com","a-very-long-password-123","Test")
    def test_password_login(self):
        self.auth.signup("test@example.com","a-very-long-password-123","Test")
        s=self.auth.login("test@example.com","a-very-long-password-123","127.0.0.1")
        self.assertEqual(self.auth.current(s["token"])["user"]["email"],"test@example.com")
    def test_wrong_password_rejected(self):
        self.auth.signup("test@example.com","a-very-long-password-123","Test")
        with self.assertRaises(AuthError):self.auth.login("test@example.com","wrong-password","127.0.0.1")
    def test_short_password_rejected(self):
        with self.assertRaises(AuthError):self.auth.signup("test@example.com","short","Test")
    def test_logout_revokes_session(self):
        s=self.auth.signup("test@example.com","a-very-long-password-123","Test")
        self.auth.logout(s["token"])
        self.assertIsNone(self.auth.current(s["token"]))
if __name__=="__main__":unittest.main()
