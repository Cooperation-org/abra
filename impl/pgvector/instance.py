"""Instance configuration: impl/.env, who is calling, which scope by default."""
from __future__ import annotations

import getpass
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from sources import load_sources

IMPL_DIR = Path(__file__).resolve().parent.parent

# Service identities may carry their settings in the environment and be unable
# to read a developer's .env; an unreadable .env must not stop the caller.
try:
    load_dotenv(IMPL_DIR / ".env")
except OSError:
    pass


def calling_user() -> str:
    """Login name of the process owner."""
    try:
        return getpass.getuser()
    except OSError:
        return "unknown"


def default_scope() -> str:
    """$ABRA_SCOPE, else `scope:` in ~/.abra/sources.yaml, else the calling user."""
    configured = load_sources().get("scope")
    return (os.getenv("ABRA_SCOPE")
            or (str(configured).strip() if configured else "")
            or calling_user())


def default_writer_uri() -> str:
    """Provenance URI for writes: $ABRA_WRITER_URI, else urn:abra:local:<user>."""
    return os.getenv("ABRA_WRITER_URI") or f"urn:abra:local:{calling_user()}"


def writer_uri(writer: str | None = None) -> str:
    """Provenance URI for a named writer (e.g. 'droid' → urn:abra:droid).
    A value containing ':' is taken as a full URI; None gives the default."""
    if not writer:
        return default_writer_uri()
    writer = writer.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*|[A-Za-z][A-Za-z0-9+.-]*:\S+", writer):
        raise ValueError(f"invalid writer {writer!r}: use a short name like 'droid' or a full URI")
    return writer if ":" in writer else f"urn:abra:{writer}"
