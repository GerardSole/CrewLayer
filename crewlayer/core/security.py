import bcrypt as _bcrypt


def hash_key(plain: str) -> str:
    """Return a bcrypt hash of an API key."""
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_key(plain: str, hashed: str) -> bool:
    """Constant-time verify of an API key against its bcrypt hash."""
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False
