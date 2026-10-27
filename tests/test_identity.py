"""Known-vector tests for the signed speaker mark and the people list.

Vectors are copied in SPEC.md and wyoming_speaker_id/README.md so the verifier
(mcp_assist_se) can reuse them. Expected HMAC values are literals, not recomputed.
"""
from __future__ import annotations

import re
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from speaker_id.identity import (
    apply_tag,
    encode_name,
    format_confidence,
    keys_match,
    signed_transcript,
)
from speaker_id.people_api import add_people_route

SECRET = "test-secret"
NOW = 1700000000
NONCE = "0123456789abcdef"

# Canonical vector (openssl dgst -sha256 -hmac test-secret).
ASCII_TEXT = "turn on the light"
ASCII_TAG = (
    "⟦spk1;n=Anna;c=0.73;t=1700000000;r=0123456789abcdef;"
    "s=4e3854eaed0f699014eead3a73f1a358618a699bb372d76d6715658adad72386⟧ "
    "turn on the light"
)

# Cyrillic name, uppercase percent-encoding.
CYRILLIC_TEXT = "включи свет"
CYRILLIC_TAG = (
    "⟦spk1;n=%D0%90%D0%BD%D0%BD%D0%B0;c=0.81;t=1700000000;r=0123456789abcdef;"
    "s=a3a00a8802e8b162bf01114baa3debc0d1b8da4df5c49382d0f0e70a90ca5318⟧ "
    "включи свет"
)

# Unknown voice: empty name, best score 0.20.
UNKNOWN_TAG = (
    "⟦spk1;n=;c=0.20;t=1700000000;r=0123456789abcdef;"
    "s=cfbddbb902625d1c94fa99e6bfcc2e298f624f0ab858b76fe207d0ed85628d45⟧ "
    "hello"
)

LEGACY = {
    "tag_unknown": True,
    "tag_template": "[speaker: {name}] {text}",
    "guest_label": "guest",
    "unknown_label": "unknown",
}


def _tag(text, **kw):
    opts = dict(LEGACY)
    opts.update(kw)
    return apply_tag(text, secret=opts.pop("secret", ""), now=NOW, nonce=NONCE, **opts)


class TagTests(unittest.TestCase):
    def test_known_vector(self):
        got = signed_transcript(SECRET, "Anna", 0.73, ASCII_TEXT, now=NOW, nonce=NONCE)
        self.assertEqual(got, ASCII_TAG)
        self.assertNotIn(SECRET, got)

    def test_cyrillic_name_is_percent_encoded(self):
        self.assertEqual(encode_name("Анна"), "%D0%90%D0%BD%D0%BD%D0%B0")
        self.assertEqual(encode_name("Az09-._~"), "Az09-._~")
        self.assertEqual(encode_name("Анна Мария"), "%D0%90%D0%BD%D0%BD%D0%B0%20%D0%9C%D0%B0%D1%80%D0%B8%D1%8F")
        got = _tag(CYRILLIC_TEXT, secret=SECRET, label="speaker", name="Анна", score=0.81)
        self.assertEqual(got, CYRILLIC_TAG)
        self.assertNotIn("Анна", got.split("⟧", 1)[0])

    def test_unknown_speaker_has_empty_name(self):
        for label, score in (("guest", 0.2), ("uncertain", 0.2), ("short", 0.2)):
            got = _tag("hello", secret=SECRET, label=label, name="Анна", score=score)
            self.assertEqual(got, UNKNOWN_TAG, label)
        no_score = _tag("hello", secret=SECRET, label="short", name=None, score=None)
        self.assertIn("n=;c=0.00;", no_score)
        self.assertNotIn("guest", no_score)
        self.assertNotIn("unknown", no_score)

    def test_empty_secret_keeps_the_name_label(self):
        self.assertEqual(
            _tag("turn on the light", secret="", label="speaker", name="Anna", score=0.73),
            "[speaker: Anna] turn on the light",
        )
        self.assertEqual(
            _tag("hello", secret="", label="guest", name=None, score=0.2),
            "[speaker: guest] hello",
        )
        self.assertEqual(
            _tag("hello", secret="", label="uncertain", name=None, score=0.4, tag_unknown=False),
            "hello",
        )
        self.assertEqual(
            _tag("hello", secret="", label="short", name=None, score=None),
            "[speaker: unknown] hello",
        )
        self.assertEqual(_tag("hello", secret="", label="speaker", name="", score=0.9), "hello")
        self.assertEqual(_tag("   ", secret=SECRET, label="speaker", name="Anna", score=0.9), "   ")
        self.assertEqual(
            _tag("hi", secret="", label="speaker", name="Ann", score=0.5, tag_template="{missing}"),
            "[Ann] hi",
        )

    def test_signed_mark_replaces_the_label_even_when_uncertain_tags_are_off(self):
        got = _tag("hello", secret=SECRET, label="guest", name=None, score=0.2, tag_unknown=False)
        self.assertEqual(got, UNKNOWN_TAG)

    def test_confidence_is_clamped_and_two_decimals(self):
        self.assertEqual(format_confidence(None), "0.00")
        self.assertEqual(format_confidence(1.4), "1.00")
        self.assertEqual(format_confidence(-0.2), "0.00")
        self.assertEqual(format_confidence(float("nan")), "0.00")

    def test_generated_nonce_is_16_hex_chars(self):
        got = signed_transcript(SECRET, "Ada", 0.5, "hi")
        self.assertRegex(got, re.compile(r"^⟦spk1;n=Ada;c=0\.50;t=\d+;r=[0-9a-f]{16};s=[0-9a-f]{64}⟧ hi$"))

    def test_keys_match_rejects_empty_and_mismatch(self):
        self.assertTrue(keys_match(SECRET, SECRET))
        self.assertFalse(keys_match("wrong", SECRET))
        self.assertFalse(keys_match(SECRET + "x", SECRET))
        self.assertFalse(keys_match("", ""))
        self.assertFalse(keys_match(SECRET, ""))
        self.assertFalse(keys_match(None, SECRET))
        self.assertFalse(keys_match(SECRET, None))


class PeopleApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.secret = SECRET
        self.names = ["Анна", "Boris"]
        app = web.Application()
        routes = web.RouteTableDef()
        add_people_route(routes, lambda: self.secret, lambda: list(self.names))
        app.add_routes(routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def _get(self, headers=None):
        async with self.client.get("/api/people", headers=headers) as resp:
            body = await resp.json()
            return resp.status, body

    async def test_requires_matching_header(self):
        status, body = await self._get()
        self.assertEqual(status, 401)
        self.assertEqual(body, {"error": "unauthorized"})

        status, body = await self._get({"X-Speaker-Key": "wrong"})
        self.assertEqual(status, 401)
        self.assertEqual(body, {"error": "unauthorized"})
        self.assertNotIn("wrong", str(body))

        status, body = await self._get({"X-Speaker-Key": SECRET})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"people": [{"name": "Boris"}, {"name": "Анна"}]})

        status, _body = await self._get({"x-speaker-key": SECRET})
        self.assertEqual(status, 200)

    async def test_empty_secret_always_rejects(self):
        self.secret = ""
        status, _body = await self._get({"X-Speaker-Key": ""})
        self.assertEqual(status, 401)
        status, _body = await self._get({"X-Speaker-Key": SECRET})
        self.assertEqual(status, 401)

    async def test_post_is_not_this_route(self):
        async with self.client.post("/api/people", headers={"X-Speaker-Key": SECRET}) as resp:
            self.assertEqual(resp.status, 405)

    async def test_get_lives_beside_the_existing_post(self):
        app = web.Application()
        routes = web.RouteTableDef()

        @routes.post("/api/people")
        async def add_person(_req):
            return web.json_response({"added": True})

        add_people_route(routes, lambda: SECRET, lambda: ["Ada"])
        app.add_routes(routes)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            async with client.get("/api/people", headers={"X-Speaker-Key": SECRET}) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(await resp.json(), {"people": [{"name": "Ada"}]})
            async with client.post("/api/people") as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(await resp.json(), {"added": True})
            async with client.get("/api/people") as resp:
                self.assertEqual(resp.status, 401)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
