"""Accounts: password hashing, validation, roles, rate limits and the secret
key that signs session cookies.

Passwords are stored only as salted scrypt hashes (werkzeug's default:
scrypt, N=2^15, r=8, p=1, 16-character random salt). Plain passwords are never
stored or logged.
"""
import os
import re
import secrets
import threading
import time
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

# Roles are only labels for now; later they'll decide who can do what.
ROLES = ("trainer", "mod", "content_creator", "admin")
DEFAULT_ROLE = "trainer"

USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,30}")
MIN_PASSWORD = 8
MAX_PASSWORD = 128  # bounds the work a single login can cause

# Compared against when a username doesn't exist, so a failed login takes as
# long whether or not the account is real.
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))


def hash_password(password):
    return generate_password_hash(password, method="scrypt")


def verify_password(stored_hash, password):
    """True if password matches. Accounts without a password never match."""
    if not stored_hash:
        check_password_hash(_DUMMY_HASH, password)
        return False
    return check_password_hash(stored_hash, password)


def username_problem(username):
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        return "Usernames are 3-30 letters, digits, dots, dashes or underscores."
    return None


def password_problem(password):
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return f"Passwords must be {MIN_PASSWORD} to {MAX_PASSWORD} characters."
    return None


def load_secret_key(path):
    """The key that signs session cookies, created on first use.

    It lives next to the database (instance/, never committed). Anyone with
    it could forge a login, so it is created readable by its owner only.
    Several processes starting at once agree on one key: only the first
    creation succeeds and the rest read it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    for _ in range(50):  # another process may be halfway through writing it
        key = path.read_text().strip()
        if key:
            return key
        time.sleep(0.02)
    raise RuntimeError(f"secret key file {path} is empty")


class RateLimit:
    """At most `limit` events per key (a visitor's address) within `window`
    seconds; used for failed logins (slowing password guessing) and sign-ups.
    Kept in memory, so it's per server process and resets on restart.
    """

    def __init__(self, limit, window):
        self.limit = limit
        self.window = window
        self.events = {}  # key -> [monotonic times]
        self.lock = threading.Lock()

    def _recent(self, key, now):
        times = [t for t in self.events.get(key, []) if now - t < self.window]
        if times:
            self.events[key] = times
        else:
            self.events.pop(key, None)
        return times

    def retry_after(self, key):
        """Seconds until `key` may go again, or 0 if it may now."""
        with self.lock:
            now = time.monotonic()
            times = self._recent(key, now)
            return int(self.window - (now - times[0])) + 1 if len(times) >= self.limit else 0

    def record(self, key):
        with self.lock:
            now = time.monotonic()
            self._recent(key, now)
            self.events.setdefault(key, []).append(now)

    def clear(self, key):
        with self.lock:
            self.events.pop(key, None)
