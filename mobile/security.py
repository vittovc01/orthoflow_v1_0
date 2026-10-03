"""Revocable, opaque sessions. No credentials or roles stored in browser storage."""
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import time

TTL = 12 * 60 * 60


def password_ok(password, salt, expected):
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), str(salt).encode(), 210_000).hex()
    return hmac.compare_digest(value, str(expected))


def fingerprint(row):
    return hashlib.sha256(str(row.get('password_hash', '')).encode()).hexdigest()


class Sessions:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, uid INTEGER, fingerprint TEXT, expires REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER, expires REAL)')
        os.chmod(self.path, 0o600)

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def issue(self, row):
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                       (self.digest(token), row['id'], fingerprint(row), time.time() + TTL))
        return token

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token):
        with self.db() as db:
            return db.execute('SELECT uid,fingerprint FROM sessions WHERE token=? AND expires>?',
                              (self.digest(token), time.time())).fetchone()

    def revoke(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (self.digest(token),))

    def throttle(self, key):
        """Shared across workers; count before authentication, including failed users."""
        key = self.digest(key)
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE expires<?', (now,))
            db.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',
                       (key, now + 900))
            count = db.execute('SELECT count FROM attempts WHERE key=?', (key,)).fetchone()[0]
            return count <= 15
