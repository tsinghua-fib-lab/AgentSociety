"""Local cache signing keys, published only after all random bytes are written."""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=64)
def _fallback_secret(path: str) -> bytes:
    # A read-only home or malformed key disables cross-process cache reuse.
    # Keep a random process-local key; never accept an empty/short on-disk key.
    return os.urandom(32)


def cache_secret(path: str) -> bytes:
    """Read a 32-byte key or atomically publish one with mode 0600.

    Hard-link publication is exclusive and atomic: concurrent readers see the
    complete key, including when the winning process dies during creation.
    """
    target = Path(path)
    temporary: str | None = None
    try:
        try:
            secret = target.read_bytes()
        except FileNotFoundError:
            fd, temporary = tempfile.mkstemp(
                prefix=f".{target.name}.", dir=target.parent
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
            secret = target.read_bytes()
        if len(secret) != 32:
            return _fallback_secret(str(target))
        return secret
    except OSError:
        return _fallback_secret(str(target))
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
