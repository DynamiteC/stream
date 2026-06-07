"""Generate nginx ``secure_link`` tokens for stream playback URLs.

The edge (``src/nginx/nginx.conf``) protects playback with the nginx
``secure_link`` module:

    secure_link $arg_token,$arg_expires;
    secure_link_md5 "$secure_link_expires REPLACE_WITH_SECRET_KEY";

The hash is intentionally bound only to ``$secure_link_expires`` (and the
shared secret) -- not to ``$uri`` or ``$remote_addr``. This matters for
segmented media: an HLS/DASH player reads segment URIs from the manifest and
does not carry the manifest's per-URI signature onto them, so a single
``{token, expires}`` pair has to authorise every file of a session until it
expires. Dropping ``$remote_addr`` also keeps tokens valid behind a CDN and
across a client's IP changes (e.g. mobile networks).

This module has no Frappe dependency on purpose, so the signing logic can be
unit-tested in isolation.
"""

import base64
import hashlib
import os
import time

# Must match the SECRET_KEY handed to the nginx edge (docker-compose). The weak
# default mirrors .env.example and is only a fallback for local/dev.
DEFAULT_SECRET = "supersecretkey123"

# Default link lifetime, in seconds.
DEFAULT_TTL = 3600


def get_secret():
    return os.getenv("SECRET_KEY", DEFAULT_SECRET)


def generate_token(expires, secret=None):
    """Return the nginx-compatible token for a given ``expires`` timestamp.

    nginx computes ``base64url(md5(<message>))`` with padding stripped, where
    ``<message>`` is ``"<expires> <secret>"`` for the config above.
    """
    if secret is None:
        secret = get_secret()
    message = f"{expires} {secret}".encode()
    digest = hashlib.md5(message).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def sign(ttl_seconds=DEFAULT_TTL, secret=None, now=None):
    """Return ``(token, expires)`` for a link valid for ``ttl_seconds``.

    ``now`` is injectable for deterministic tests.
    """
    base = int(time.time() if now is None else now)
    expires = base + int(ttl_seconds)
    return generate_token(expires, secret=secret), expires


def append_token(url, token, expires):
    """Append ``token``/``expires`` query params to ``url``."""
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}token={token}&expires={expires}"
