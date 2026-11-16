"""
Shared-secret guard for the admin-only HTTP endpoints.

Two endpoints are meant for a researcher with a key, never for the app:
the venue review queue (VENUE_ADMIN_KEY) and the survey CSV export
(SP_ADMIN_KEY). They keep separate keys on purpose — reviewing venue data
and pulling survey responses are different privileges, and one key leaking
shouldn't open the other.

This is a header check, not a user/role system. The key travels in
X-Admin-Key on every call, so these endpoints must only ever be reached
over HTTPS.
"""

import hmac
import os

from fastapi import HTTPException


def check_admin_key(env_var: str, presented: str | None) -> None:
    """Raise unless `presented` equals the key stored in env var `env_var`.

    Fails closed: with no key configured the endpoint is off (503), and the
    response doesn't say which variable is missing. The comparison is
    constant-time so response timing can't be used to guess the key one
    character at a time.
    """
    expected = os.environ.get(env_var)
    if not expected:
        raise HTTPException(status_code=503, detail="This admin endpoint is not enabled")
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Key")
