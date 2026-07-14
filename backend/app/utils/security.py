"""
JWT token creation / verification and password hashing utilities.
Uses PBKDF2-SHA256 for passwords (avoids passlib/bcrypt version issues).
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from jose import JWTError, jwt

from ..config import settings


# ---------------------------------------------------------------------------
# Password helpers (PBKDF2-SHA256, no external passlib dependency at runtime)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash password using PBKDF2-SHA256."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), 260000)
    return f"pbkdf2:sha256:260000${salt}${dk.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a PBKDF2-SHA256 hashed password."""
    if not hashed.startswith("pbkdf2:sha256:"):
        return False
    try:
        parts = hashed.split("$")
        # parts[0] = "pbkdf2:sha256:260000", parts[1] = salt, parts[2] = hex_hash
        rounds = int(parts[0].split(":")[-1])
        salt = parts[1]
        stored_dk = parts[2]
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode(), rounds)
        return hmac.compare_digest(dk.hex(), stored_dk)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Decode and verify a JWT token. Returns payload dict or None on failure."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None
