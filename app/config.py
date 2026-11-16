"""Small shared configuration accessors (read from the environment at call
time, so tests and a restarted process always see the current value)."""

import os


def maps_api_key() -> str | None:
    """The server-side Google Maps Platform key (Directions, Places,
    Geocoding) — never sent to a client.

    GOOGLE_MAPS_API_KEY is the documented name (.env.example, README).
    GOOGLE_MAPS_KEY is an older alias some environments still set; it is
    still honoured, and wins when both are present, exactly as before this
    helper existed. Three modules used to each read the environment their
    own way, and one of them only knew the newer name.
    """
    return os.environ.get("GOOGLE_MAPS_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY")
