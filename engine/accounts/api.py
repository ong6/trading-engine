"""Private bearer-token handling for the loopback account API."""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

TOKEN_ENV = "TRADING_ENGINE_ACCOUNTS_TOKEN_FILE"


def token_path() -> Path:
    override = os.environ.get(TOKEN_ENV)
    return Path(override) if override else Path.home() / ".config/trading-engine/accounts-api.token"


def generate_token(*, path: Path | None = None, force: bool = False) -> Path:
    """Create a 256-bit token file with owner-read/write permissions."""
    target = path or token_path()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    descriptor = os.open(target, flags, 0o600)
    try:
        os.write(descriptor, (secrets.token_urlsafe(32) + "\n").encode("ascii"))
    finally:
        os.close(descriptor)
    os.chmod(target, 0o600)
    return target


def read_token(*, path: Path | None = None) -> str:
    target = path or token_path()
    mode = stat.S_IMODE(target.stat().st_mode)
    if mode != 0o600:
        raise PermissionError(f"account API token must have mode 0600, found {mode:04o}")
    value = target.read_text(encoding="ascii").strip()
    if len(value) < 32:
        raise ValueError("account API token is invalid")
    return value


def presented_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, value = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not value:
        return ""
    return value


def authenticated(authorization: str | None, *, path: Path | None = None) -> bool:
    presented = presented_token(authorization)
    if presented is None:
        return False
    try:
        expected = read_token(path=path)
    except (OSError, ValueError):
        return False
    return secrets.compare_digest(presented, expected)
