"""Local-first account/session service for SYNAPSE EARTH.

Passwords use scrypt; opaque session tokens are stored only as SHA-256 hashes.
This prototype intentionally does not claim email verification or production
identity assurance. Deploy behind HTTPS and add a verified email provider before
public production use.
"""
import hashlib, hmac, secrets, sqlite3, time, os, re
from pathlib import Path

class AuthError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message); self.status=status

class AuthStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,
              display_name TEXT NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions(
              token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
              csrf TEXT NOT NULL, expires_at INTEGER NOT NULL,
              FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS login_attempts(
              id INTEGER PRIMARY KEY, identity TEXT NOT NULL, attempted_at INTEGER NOT NULL
            );
            """)
    def db(self):
        c=sqlite3.connect(self.db_path, timeout=10)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c
    @staticmethod
    def _hash(password, salt):
        return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=64)
    def signup(self, email, password, display_name):
        email=(email or "").strip().lower()
        display_name=(display_name or "").strip()[:80]
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise AuthError("Enter a valid email address.")
        if len(password or "") < 12 or len(password) > 256:
            raise AuthError("Use a password with at least 12 characters.")
        if not display_name:
            raise AuthError("Enter your name.")
        salt=secrets.token_bytes(16); ph=self._hash(password,salt)
        try:
            with self.db() as c:
                cur=c.execute("INSERT INTO users(email,display_name,salt,password_hash,created_at) VALUES(?,?,?,?,?)",
                              (email,display_name,salt,ph,int(time.time())))
                uid=cur.lastrowid
        except sqlite3.IntegrityError:
            raise AuthError("An account with this email already exists.",409)
        return self.create_session(uid)
    def _throttle(self, identity):
        now=int(time.time())
        with self.db() as c:
            c.execute("DELETE FROM login_attempts WHERE attempted_at < ?",(now-900,))
            count=c.execute("SELECT COUNT(*) FROM login_attempts WHERE identity=? AND attempted_at>?",
                            (identity,now-900)).fetchone()[0]
            if count >= 8: raise AuthError("Too many login attempts. Try again in 15 minutes.",429)
            c.execute("INSERT INTO login_attempts(identity,attempted_at) VALUES(?,?)",(identity,now))
    def login(self,email,password,identity):
        email=(email or "").strip().lower()
        self._throttle(identity+"|"+email)
        with self.db() as c:
            u=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        # Do a dummy scrypt for unknown users to reduce account-enumeration timing differences.
        if not u:
            self._hash(password or "invalid-password", b"synapse-dummy-salt")
            raise AuthError("Email or password is incorrect.",401)
        if not hmac.compare_digest(self._hash(password or "",u["salt"]),u["password_hash"]):
            raise AuthError("Email or password is incorrect.",401)
        return self.create_session(u["id"])
    def create_session(self,uid):
        token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
        expires=int(time.time())+12*60*60
        with self.db() as c:
            c.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)",
                      (hashlib.sha256(token.encode()).hexdigest(),uid,csrf,expires))
            u=c.execute("SELECT id,email,display_name FROM users WHERE id=?",(uid,)).fetchone()
        return {"token":token,"csrf":csrf,"expires_at":expires,
                "user":{"id":u["id"],"email":u["email"],"display_name":u["display_name"]}}
    def current(self,token):
        if not token:return None
        th=hashlib.sha256(token.encode()).hexdigest()
        with self.db() as c:
            row=c.execute("""SELECT s.csrf,s.expires_at,u.id,u.email,u.display_name
              FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""",(th,)).fetchone()
            if not row:return None
            if row["expires_at"]<int(time.time()):
                c.execute("DELETE FROM sessions WHERE token_hash=?",(th,));return None
        return {"csrf":row["csrf"],"expires_at":row["expires_at"],
                "user":{"id":row["id"],"email":row["email"],"display_name":row["display_name"]}}
    def logout(self,token):
        if token:
            with self.db() as c:c.execute("DELETE FROM sessions WHERE token_hash=?",
              (hashlib.sha256(token.encode()).hexdigest(),))
