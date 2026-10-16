"""Wyoming Speaker ID: Wyoming STT proxy with speaker identification and an ingress web UI."""
from __future__ import annotations

import asyncio
import collections
import contextlib
import itertools
import json
import logging
import os
import time
from functools import partial

import numpy as np
from aiohttp import ClientSession, ClientTimeout, web
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.client import AsyncClient
from wyoming.event import Event
from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info
from wyoming.server import AsyncEventHandler, AsyncServer

from . import __version__, models
from .embed import SR, Embedder, Vad, decode_audio, encode_wav, pcm16_to_float
from .store import Decision, Store, decide

_LOG = logging.getLogger("speaker_id")
DATA = os.environ.get("SPEAKER_ID_DATA", "/data")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
TUNABLE = {"threshold_high": (-1.0, 50.0), "threshold_low": (-1.0, 50.0), "margin": (0.0, 10.0),
           "min_speech_seconds": (0.0, 10.0)}
DEFAULTS = {
    "upstream_uri": "tcp://core-whisper:10300", "model": "redimnet2_b2", "threshold_high": 0.45,
    "threshold_low": 0.30, "margin": 0.08, "min_speech_seconds": 0.6, "tag_template": "[speaker: {name}] {text}",
    "guest_label": "guest", "unknown_label": "unknown", "tag_unknown": True, "cohort_norm": False,
    "publish_sensor": True, "sensor_entity": "sensor.voice_last_speaker", "recent_buffer_size": 30,
    "log_level": "info", "wyoming_uri": "tcp://0.0.0.0:10310", "web_port": 8099, "max_speech_seconds": 8.0,
}
MAX_KEEP_S = 15.0


class App:
    def __init__(self):
        self.opts = dict(DEFAULTS)
        p = os.path.join(DATA, "options.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                self.opts.update(json.load(f))
        self.settings_path = os.path.join(DATA, "settings.json")
        if os.path.exists(self.settings_path):
            with open(self.settings_path, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if k in TUNABLE:
                        self.opts[k] = v
        logging.basicConfig(level=getattr(logging, str(self.opts["log_level"]).upper(), logging.INFO),
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        path, kind = models.resolve(self.opts["model"], DATA)
        self.model_name = os.path.basename(path)
        self.emb = Embedder(path, kind)
        self.vad = Vad(models.vad_path())
        self.store = Store(DATA, self.opts["model"], self.emb, self.vad)
        self.store.rebuild()
        self.recent: collections.deque = collections.deque(maxlen=max(1, int(self.opts["recent_buffer_size"])))
        self._ids = itertools.count(1)
        self.languages = ["en"]
        self.token = os.environ.get("SUPERVISOR_TOKEN")

    # -- identification ------------------------------------------------------
    def identify(self, x: np.ndarray) -> tuple[Decision, float]:
        t0 = time.perf_counter()
        o = self.opts
        sp = self.vad.trim(x)
        speech = len(sp) / SR
        if speech < o["min_speech_seconds"]:
            d = Decision("short", speech_s=speech)
        else:
            mx = o["max_speech_seconds"]
            if mx and len(sp) > mx * SR:
                sp = sp[: int(mx * SR)]
            scores = self.store.score(self.emb(sp), bool(o["cohort_norm"]))
            d = decide(scores, speech, o["threshold_high"], o["threshold_low"], o["margin"], o["min_speech_seconds"])
        return d, (time.perf_counter() - t0) * 1000

    def label(self, d: Decision) -> str:
        if d.label == "speaker":
            return d.name or ""
        return self.opts["guest_label"] if d.label == "guest" else self.opts["unknown_label"]

    def tag(self, d: Decision, text: str) -> str:
        if not text.strip():
            return text
        if d.label in ("short", "uncertain") and not self.opts["tag_unknown"]:
            return text
        who = self.label(d)
        if not who:
            return text
        try:
            return self.opts["tag_template"].format(name=who, text=text)
        except (KeyError, IndexError, ValueError):
            return f"[{who}] {text}"

    def remember(self, x: np.ndarray, d: Decision, text: str, ms: float) -> dict:
        item = {"id": next(self._ids), "time": time.time(), "text": text, "decision": d.label, "name": d.name,
                "label": self.label(d), "score": None if d.score is None else round(d.score, 3),
                "scores": {k: round(v, 3) for k, v in d.scores.items()}, "speech_s": round(d.speech_s, 2),
                "ms": round(ms), "_audio": x[: int(MAX_KEEP_S * SR)].copy()}
        if self.opts["recent_buffer_size"]:
            self.recent.appendleft(item)
        return item

    async def publish(self, item: dict) -> None:
        if not (self.opts["publish_sensor"] and self.token):
            return
        body = {"state": item["label"] or "unknown", "attributes": {
            "friendly_name": "Voice last speaker", "icon": "mdi:account-voice", "decision": item["decision"],
            "person": item["name"], "score": item["score"], "scores": item["scores"],
            "speech_seconds": item["speech_s"], "text": item["text"]}}
        try:
            url = f"http://supervisor/core/api/states/{self.opts['sensor_entity']}"
            hdr = {"Authorization": f"Bearer {self.token}"}
            async with ClientSession(timeout=ClientTimeout(total=5)) as s, s.post(url, json=body, headers=hdr) as r:
                if r.status >= 300:
                    _LOG.warning("Sensor update failed: %s", r.status)
        except Exception as e:  # noqa: BLE001
            _LOG.warning("Sensor update error: %s", e)

    def save_settings(self, new: dict) -> None:
        cur = {}
        for k, v in new.items():
            if k in TUNABLE:
                lo, hi = TUNABLE[k]
                self.opts[k] = cur[k] = min(hi, max(lo, float(v)))
        old = {}
        if os.path.exists(self.settings_path):
            with open(self.settings_path, encoding="utf-8") as f:
                old = json.load(f)
        old.update(cur)
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(old, f)

    def info(self) -> Info:
        att = Attribution(name="Wyoming Speaker ID", url="https://github.com/olegchumakov/ha-addon-wyoming-speaker-id")
        return Info(asr=[AsrProgram(
            name="speaker-id", description=f"Speaker ID ({self.model_name}) via {self.opts['upstream_uri']}",
            attribution=att, installed=True, version=__version__,
            models=[AsrModel(name="speaker-id", description="Upstream STT with speaker tag", attribution=att,
                             installed=True, languages=self.languages, version=__version__)])])

    async def describe_upstream(self) -> None:
        for attempt in range(30):
            try:
                c = AsyncClient.from_uri(self.opts["upstream_uri"])
                await c.connect()
                await c.write_event(Describe().event())
                while True:
                    ev = await asyncio.wait_for(c.read_event(), timeout=10)
                    if ev is None:
                        break
                    if Info.is_type(ev.type):
                        info = Info.from_event(ev)
                        langs = sorted({lang for p in info.asr for m in p.models for lang in m.languages})
                        if langs:
                            self.languages = langs
                        break
                await c.disconnect()
                _LOG.info("Upstream %s: %d languages", self.opts["upstream_uri"], len(self.languages))
                return
            except Exception as e:  # noqa: BLE001
                _LOG.warning("Upstream %s not reachable (%s), retry %d", self.opts["upstream_uri"], e, attempt + 1)
                await asyncio.sleep(10)


class Handler(AsyncEventHandler):
    def __init__(self, app: App, *a, **kw):
        super().__init__(*a, **kw)
        self.app = app
        self.up: AsyncClient | None = None
        self.buf = bytearray()
        self.conv = AudioChunkConverter(rate=SR, width=2, channels=1)
        self.transcribe: Event | None = None

    async def _connect(self):
        if self.up is None:
            self.up = AsyncClient.from_uri(self.app.opts["upstream_uri"])
            await self.up.connect()
            if self.transcribe is not None:
                await self.up.write_event(self.transcribe)

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(self.app.info().event())
            return True
        if Transcribe.is_type(event.type):
            self.transcribe = event
            if self.up is not None:
                await self.up.write_event(event)
            return True
        if AudioStart.is_type(event.type):
            self.buf.clear()
            await self._connect()
            await self.up.write_event(event)
            return True
        if AudioChunk.is_type(event.type):
            await self._connect()
            await self.up.write_event(event)
            self.buf.extend(self.conv.convert(AudioChunk.from_event(event)).audio)
            return True
        if AudioStop.is_type(event.type):
            await self._finish(event)
            return False
        return True

    async def _finish(self, stop: Event) -> None:
        loop = asyncio.get_running_loop()
        x = pcm16_to_float(bytes(self.buf))
        task = loop.run_in_executor(None, self.app.identify, x)
        text = ""
        try:
            if self.up is None:
                await self._connect()
            await self.up.write_event(stop)
            while True:
                ev = await asyncio.wait_for(self.up.read_event(), timeout=120)
                if ev is None:
                    break
                if Transcript.is_type(ev.type):
                    text = Transcript.from_event(ev).text
                    break
        except Exception as e:  # noqa: BLE001
            _LOG.error("Upstream STT error: %s", e)
        finally:
            if self.up is not None:
                with contextlib.suppress(Exception):
                    await self.up.disconnect()
                self.up = None
        try:
            d, ms = await task
        except Exception:  # noqa: BLE001
            _LOG.exception("Identification failed")
            d, ms = Decision("short"), 0.0
        out = self.app.tag(d, text)
        _LOG.info("%s name=%s score=%s speech=%.2fs (%.0f ms): %r", d.label, d.name,
                  None if d.score is None else round(d.score, 3), d.speech_s, ms, out)
        await self.write_event(Transcript(text=out).event())
        item = self.app.remember(x, d, text, ms)
        asyncio.create_task(self.app.publish(item))


# -- web UI ---------------------------------------------------------------------
def build_web(app: App) -> web.Application:
    r = web.RouteTableDef()

    def err(e: Exception, code: int = 400):
        return web.json_response({"error": str(e)}, status=code)

    @r.get("/")
    async def index(_):
        return web.FileResponse(os.path.join(WEB_DIR, "index.html"))

    @r.get("/api/status")
    async def status(_):
        o = app.opts
        return web.json_response({
            "version": __version__, "model": o["model"], "model_file": app.model_name,
            "upstream": o["upstream_uri"], "languages": len(app.languages),
            "settings": {k: o[k] for k in TUNABLE}, "cohort_norm": o["cohort_norm"],
            "cohort_size": app.store.cohort_size(), "people": app.store.people()})

    @r.post("/api/settings")
    async def settings(req):
        try:
            app.save_settings(await req.json())
        except Exception as e:  # noqa: BLE001
            return err(e)
        return web.json_response({k: app.opts[k] for k in TUNABLE})

    @r.get("/api/recent")
    async def recent(_):
        return web.json_response([{k: v for k, v in i.items() if not k.startswith("_")} for i in app.recent])

    def find(rid: str):
        for i in app.recent:
            if str(i["id"]) == rid:
                return i
        raise web.HTTPNotFound()

    @r.get("/api/recent/{rid}/audio")
    async def recent_audio(req):
        return web.Response(body=encode_wav(find(req.match_info["rid"])["_audio"]), content_type="audio/wav")

    @r.post("/api/recent/{rid}/assign")
    async def assign(req):
        item = find(req.match_info["rid"])
        body = await req.json()
        try:
            if body.get("cohort"):
                await asyncio.get_running_loop().run_in_executor(None, app.store.add_cohort, item["_audio"])
                return web.json_response({"ok": True})
            fn = await asyncio.get_running_loop().run_in_executor(
                None, app.store.add_sample, body.get("name", ""), item["_audio"], "utterance")
        except ValueError as e:
            return err(e)
        return web.json_response({"ok": True, "file": fn})

    @r.post("/api/people")
    async def add_person(req):
        try:
            return web.json_response({"name": app.store.add_person((await req.json()).get("name", ""))})
        except ValueError as e:
            return err(e)

    @r.delete("/api/people/{name}")
    async def del_person(req):
        try:
            await asyncio.get_running_loop().run_in_executor(None, app.store.delete_person, req.match_info["name"])
        except ValueError as e:
            return err(e)
        return web.json_response({"ok": True})

    @r.post("/api/people/{name}/upload")
    async def upload(req):
        name = req.match_info["name"]
        saved, failed = [], []
        reader = await req.multipart()
        while True:
            part = await reader.next()
            if part is None:
                break
            data = await part.read(decode=False)
            try:
                x = decode_audio(bytes(data))
                fn = await asyncio.get_running_loop().run_in_executor(None, app.store.add_sample, name, x, "upload")
                saved.append(fn)
            except Exception as e:  # noqa: BLE001
                failed.append(f"{part.filename}: {e}")
        return web.json_response({"saved": saved, "failed": failed})

    @r.post("/api/cohort/upload")
    async def cohort_upload(req):
        n = 0
        reader = await req.multipart()
        while True:
            part = await reader.next()
            if part is None:
                break
            try:
                x = decode_audio(bytes(await part.read(decode=False)))
                await asyncio.get_running_loop().run_in_executor(None, app.store.add_cohort, x)
                n += 1
            except Exception as e:  # noqa: BLE001
                _LOG.warning("Cohort file %s rejected: %s", part.filename, e)
        return web.json_response({"added": n, "cohort_size": app.store.cohort_size()})

    @r.get("/api/people/{name}/samples/{fn}")
    async def sample(req):
        try:
            p = app.store.sample_path(req.match_info["name"], req.match_info["fn"])
        except ValueError as e:
            return err(e)
        if not os.path.exists(p):
            raise web.HTTPNotFound()
        return web.FileResponse(p)

    @r.delete("/api/people/{name}/samples/{fn}")
    async def del_sample(req):
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, app.store.delete_sample, req.match_info["name"], req.match_info["fn"])
        except ValueError as e:
            return err(e)
        return web.json_response({"ok": True})

    w = web.Application(client_max_size=64 * 1024 * 1024)
    w.add_routes(r)
    return w


async def amain() -> None:
    app = App()
    _LOG.info("Model %s; people: %s", app.model_name, list(app.store.centroids))
    app.emb(np.full(SR, 1e-3, np.float32))
    upstream_task = asyncio.create_task(app.describe_upstream())  # noqa: F841
    runner = web.AppRunner(build_web(app), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(app.opts["web_port"])).start()
    server = AsyncServer.from_uri(app.opts["wyoming_uri"])
    _LOG.info("Wyoming STT on %s -> %s; web UI on :%s", app.opts["wyoming_uri"], app.opts["upstream_uri"],
              app.opts["web_port"])
    await server.run(partial(Handler, app))


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
