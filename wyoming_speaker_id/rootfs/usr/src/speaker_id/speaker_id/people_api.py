"""GET /api/people — enrolled names for Home Assistant, password in X-Speaker-Key.

The header value is compared and discarded. It is never logged.
"""
from __future__ import annotations

from aiohttp import web

from .identity import keys_match, people_payload


def add_people_route(routes, get_secret, get_names):
    """Register ``GET /api/people``. ``get_secret`` returns the shared password (may be empty)."""

    @routes.get("/api/people")
    async def list_people(request: web.Request) -> web.Response:
        secret = get_secret()
        if not isinstance(secret, str):
            secret = ""
        presented = request.headers.get("X-Speaker-Key", "")
        if not keys_match(presented, secret):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(people_payload(get_names()))

    return list_people
