"""Wyoming Speaker ID: Wyoming STT proxy with speaker identification and an ingress web UI."""
from __future__ import annotations

import asyncio
import collections
import contextlib
import itertools
import json
import logging
import os
import shutil
import socket
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
from .identity import apply_tag
from .people_api import add_people_route
from .store import Decision, Store, decide, write_meta

_LOG = logging.getLogger("speaker_id")
DATA = os.environ.get("SPEAKER_ID_DATA", "/data")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
TUNABLE = {"threshold_high": (-1.0, 50.0), "threshold_low": (-1.0, 50.0), "margin": (0.0, 10.0),
           "min_speech_seconds": (0.0, 10.0), "threshold_high_norm": (-5.0, 50.0),
           "threshold_low_norm": (-5.0, 50.0), "margin_norm": (0.0, 10.0)}
# With comparison against other voices ("cohort normalization") scores are on a different scale, so a separate set
# of thresholds is used automatically; the user never has to re-tune when switching it on or off.
PLAIN_KEYS = ("threshold_high", "threshold_low", "margin", "min_speech_seconds")
NORM_KEYS = ("threshold_high_norm", "threshold_low_norm", "margin_norm", "min_speech_seconds")
MIN_COHORT = 10
DEFAULTS = {
    "upstream_uri": "tcp://core-whisper:10300", "model": "redimnet2_b2", "threshold_high": 0.45,
    "threshold_low": 0.30, "margin": 0.08, "min_speech_seconds": 0.6, "tag_template": "[speaker: {name}] {text}",
    "guest_label": "guest", "unknown_label": "unknown", "tag_unknown": True, "shared_secret": "", "cohort_norm": False,
    "publish_sensor": True, "sensor_entity": "sensor.voice_last_speaker", "recent_buffer_size": 30,
    "log_level": "info", "wyoming_uri": "tcp://0.0.0.0:10310", "web_port": 8099, "max_speech_seconds": 8.0,
    "threshold_high_norm": 2.5, "threshold_low_norm": 1.0, "margin_norm": 0.5,
}
MAX_KEEP_S = 15.0
NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


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
        self.recent_dir = os.path.join(DATA, "recent")
        self._ids = itertools.count(self.load_recent() + 1)
        self.languages = ["en"]
        self.token = os.environ.get("SUPERVISOR_TOKEN")
        self._stt_lock = asyncio.Lock()
        self._bg: set = set()

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
            norm = self.norm_active()
            scores = self.store.score(self.emb(sp), norm)
            hi, lo, mg, ms = (o[k] for k in (NORM_KEYS if norm else PLAIN_KEYS))
            d = decide(scores, speech, hi, lo, mg, ms)
        return d, (time.perf_counter() - t0) * 1000

    def norm_active(self) -> bool:
        return bool(self.opts["cohort_norm"]) and self.store.cohort_size() >= MIN_COHORT

    def active_settings(self) -> dict:
        return {k: self.opts[k] for k in (NORM_KEYS if self.norm_active() else PLAIN_KEYS)}

    def label(self, d: Decision) -> str:
        if d.label == "speaker":
            return d.name or ""
        return self.opts["guest_label"] if d.label == "guest" else self.opts["unknown_label"]

    def tag(self, d: Decision, text: str) -> str:
        o = self.opts
        return apply_tag(
            text,
            secret=o.get("shared_secret") or "",
            label=d.label,
            name=d.name,
            score=d.score,
            tag_unknown=o["tag_unknown"],
            tag_template=o["tag_template"],
            guest_label=o["guest_label"],
            unknown_label=o["unknown_label"],
        )

    def remember(self, x: np.ndarray, d: Decision, text: str, ms: float) -> dict:
        item = {"id": next(self._ids), "time": time.time(), "text": text, "decision": d.label, "name": d.name,
                "label": self.label(d), "score": None if d.score is None else round(d.score, 3),
                "scores": {k: round(v, 3) for k, v in d.scores.items()}, "speech_s": round(d.speech_s, 2),
                "ms": round(ms), "assigned": None, "rescore": None}
        if self.opts["recent_buffer_size"]:
            evicted = self.recent[-1] if len(self.recent) == self.recent.maxlen else None
            try:
                os.makedirs(self.recent_dir, exist_ok=True)
                with open(self.recent_wav(item), "wb") as f:
                    f.write(encode_wav(x[: int(MAX_KEEP_S * SR)]))
                self.recent.appendleft(item)
                if evicted is not None:
                    with contextlib.suppress(OSError):
                        os.remove(self.recent_wav(evicted))
                self.save_recent()
            except OSError as e:
                _LOG.warning("Cannot store recent utterance: %s", e)
        return item

    def recent_wav(self, item: dict) -> str:
        return os.path.join(self.recent_dir, f"{int(item['id'])}.wav")

    def recent_audio(self, item: dict) -> np.ndarray:
        return _read_audio(self.recent_wav(item))

    def delete_recent(self, ids: list) -> int:
        """Forget recent utterances (assigned samples are separate copies and stay)."""
        ids = {str(i) for i in ids}
        gone = [i for i in self.recent if str(i["id"]) in ids]
        for i in gone:
            self.recent.remove(i)
            with contextlib.suppress(OSError):
                os.remove(self.recent_wav(i))
        if gone:
            self.save_recent()
        return len(gone)

    def recent_disk(self) -> int:
        try:
            return sum(e.stat().st_size for e in os.scandir(self.recent_dir) if e.is_file())
        except OSError:
            return 0

    def save_recent(self) -> None:
        """Persist recent utterance metadata (audio is stored per item as <id>.wav)."""
        if not self.opts["recent_buffer_size"]:
            return
        os.makedirs(self.recent_dir, exist_ok=True)
        path = os.path.join(self.recent_dir, "recent.json")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump([{k: v for k, v in i.items() if not k.startswith("_")} for i in self.recent], f,
                      ensure_ascii=False)
        os.replace(path + ".tmp", path)

    def load_recent(self) -> int:
        """Load persisted recent utterances; returns the highest id seen."""
        if not os.path.isdir(self.recent_dir):
            return 0
        if not self.opts["recent_buffer_size"]:
            shutil.rmtree(self.recent_dir, ignore_errors=True)
            return 0
        try:
            with open(os.path.join(self.recent_dir, "recent.json"), encoding="utf-8") as f:
                items = json.load(f)
        except (OSError, ValueError):
            items = []
        keep = set()
        for i in items[: self.recent.maxlen]:
            try:
                if not os.path.exists(self.recent_wav(i)):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            self.recent.append(i)
            keep.add(os.path.basename(self.recent_wav(i)))
        for fn in os.listdir(self.recent_dir):
            if fn.endswith(".wav") and fn not in keep:
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(self.recent_dir, fn))
        return max((int(i["id"]) for i in self.recent), default=0)

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

    async def transcribe(self, x: np.ndarray) -> str:
        """Transcribe audio with the upstream STT (used for samples without text)."""
        async with self._stt_lock:
            c = AsyncClient.from_uri(self.opts["upstream_uri"])
            await c.connect()
            try:
                await c.write_event(Transcribe().event())
                await c.write_event(AudioStart(rate=SR, width=2, channels=1).event())
                pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
                for i in range(0, len(pcm), SR // 5 * 2):
                    await c.write_event(AudioChunk(rate=SR, width=2, channels=1, audio=pcm[i:i + SR // 5 * 2]).event())
                await c.write_event(AudioStop().event())
                while True:
                    ev = await asyncio.wait_for(c.read_event(), timeout=120)
                    if ev is None:
                        return ""
                    if Transcript.is_type(ev.type):
                        return Transcript.from_event(ev).text.strip()
            finally:
                with contextlib.suppress(Exception):
                    await c.disconnect()

    async def transcribe_file(self, path: str) -> str:
        x = await asyncio.get_running_loop().run_in_executor(None, _read_audio, path)
        text = await self.transcribe(x)
        write_meta(path, text=text, text_source="upstream_stt")
        return text

    def transcribe_later(self, paths: list[str]) -> None:
        async def run():
            for p in paths:
                try:
                    await self.transcribe_file(p)
                except Exception as e:  # noqa: BLE001
                    _LOG.warning("Transcription of %s failed: %s", os.path.basename(p), e)
        task = asyncio.create_task(run())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def rescore(self, item: dict) -> None:
        d, _ = self.identify(self.recent_audio(item))
        item["rescore"] = {"decision": d.label, "name": d.name, "label": self.label(d),
                           "score": None if d.score is None else round(d.score, 3),
                           "scores": {k: round(v, 3) for k, v in d.scores.items()}}

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

    async def check_upstream(self) -> dict:
        """Connect to the upstream STT and ask for its info (for the web UI)."""
        t0 = time.perf_counter()
        uri = self.opts["upstream_uri"]
        try:
            c = AsyncClient.from_uri(uri)
            await asyncio.wait_for(c.connect(), timeout=5)
            try:
                await c.write_event(Describe().event())
                while True:
                    ev = await asyncio.wait_for(c.read_event(), timeout=5)
                    if ev is None:
                        raise ConnectionError("connection closed")
                    if Info.is_type(ev.type):
                        break
            finally:
                with contextlib.suppress(Exception):
                    await c.disconnect()
            info = Info.from_event(ev)
            progs = [{"name": p.name, "version": p.version, "models": [m.name for m in p.models]} for p in info.asr]
            langs = sorted({lang for p in info.asr for m in p.models for lang in m.languages})
            return {"ok": bool(info.asr), "uri": uri, "ms": round((time.perf_counter() - t0) * 1000),
                    "programs": progs, "languages": len(langs),
                    "error": None if info.asr else "no speech-to-text service found at this address"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "uri": uri, "ms": round((time.perf_counter() - t0) * 1000),
                    "error": f"{type(e).__name__}: {e}" if str(e) else type(e).__name__}

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
def _read_audio(path: str):
    with open(path, "rb") as f:
        return decode_audio(f.read())


def build_web(app: App) -> web.Application:
    r = web.RouteTableDef()

    def loop_run(f, *a):
        return asyncio.get_running_loop().run_in_executor(None, f, *a)

    def err(e: Exception, code: int = 400):
        return web.json_response({"error": str(e)}, status=code)

    def public(i: dict) -> dict:
        return {k: v for k, v in i.items() if not k.startswith("_")}

    async def read_parts(req) -> list[tuple[str, bytes]]:
        out = []
        reader = await req.multipart()
        while True:
            part = await reader.next()
            if part is None:
                break
            out.append((part.filename or "file", bytes(await part.read(decode=False))))
        return out

    async def files_from(req) -> list[str]:
        body = await req.json()
        files = body.get("files") or []
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise ValueError("'files' must be a list of file names")
        return files

    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
        index_html = f.read().replace("__VERSION__", __version__)

    @r.get("/")
    async def index(_):
        return web.Response(text=index_html, content_type="text/html", headers=NO_STORE)

    @r.get("/api/status")
    async def status(req):
        o = app.opts
        people = app.store.people()
        cohort_size: object = app.store.cohort_size()
        if "ui" not in req.query:
            # A pre-0.1.2 page (e.g. kept by a browser cache) is talking to us: give it the old sample format so
            # it still works, and make it load the current page once (that old page renders cohort_size as HTML).
            people = [dict(p, samples=[s["file"] for s in p["samples"]]) for p in people]
            cohort_size = (f"{cohort_size}<img src=\"data:,\" style=\"display:none\" onerror=\"if(!/[?&]v=/"
                           f".test(location.search))location.replace(location.pathname+'?v={__version__}')\">")
        return web.json_response({
            "version": __version__, "model": o["model"], "model_file": app.model_name,
            "upstream": o["upstream_uri"], "languages": len(app.languages),
            "settings": app.active_settings(), "cohort_norm": o["cohort_norm"], "norm_active": app.norm_active(),
            "min_cohort": MIN_COHORT, "recent_count": len(app.recent), "recent_limit": o["recent_buffer_size"],
            "recent_disk_bytes": app.recent_disk(),
            "cohort_size": cohort_size, "people": people})

    @r.get("/api/upstream")
    async def upstream(_):
        return web.json_response(await app.check_upstream())

    @r.post("/api/settings")
    async def settings(req):
        try:
            app.save_settings(await req.json())
        except Exception as e:  # noqa: BLE001
            return err(e)
        return web.json_response(app.active_settings())

    # -- recent utterances ---------------------------------------------------
    @r.get("/api/recent")
    async def recent(_):
        for i in app.recent:  # the assigned sample may have been deleted from the sample lists meanwhile
            a = i.get("assigned")
            if a:
                try:
                    p = app.store.cohort_path(a["file"]) if a["target"] == "cohort" else \
                        app.store.sample_path(a["target"], a["file"])
                    gone = not os.path.exists(p)
                except ValueError:
                    gone = True
                if gone:
                    i["assigned"] = None
        return web.json_response([public(i) for i in app.recent])

    def find(rid: str):
        for i in app.recent:
            if str(i["id"]) == rid:
                return i
        raise web.HTTPNotFound()

    @r.get("/api/recent/{rid}/audio")
    async def recent_audio(req):
        item = find(req.match_info["rid"])
        if not os.path.exists(app.recent_wav(item)):
            raise web.HTTPNotFound()
        return web.FileResponse(app.recent_wav(item), headers={"Content-Type": "audio/wav"})

    @r.delete("/api/recent/{rid}")
    async def recent_delete_one(req):
        return web.json_response({"deleted": await loop_run(app.delete_recent, [req.match_info["rid"]])})

    @r.post("/api/recent/delete")
    async def recent_delete(req):
        ids = (await req.json()).get("ids") or []
        if not isinstance(ids, list):
            return err(ValueError("'ids' must be a list"))
        return web.json_response({"deleted": await loop_run(app.delete_recent, ids)})

    async def _unassign(item: dict) -> None:
        a = item.get("assigned")
        if not a:
            return
        if a["target"] == "cohort":
            await loop_run(app.store.delete_cohort, [a["file"]])
        else:
            await loop_run(app.store.delete_samples, a["target"], [a["file"]])
        item["assigned"] = None

    @r.post("/api/recent/{rid}/assign")
    async def assign(req):
        item = find(req.match_info["rid"])
        body = await req.json()
        meta = {"text": item["text"], "text_source": "pipeline",
                "original": {"decision": item["decision"], "label": item["label"], "score": item["score"],
                             "time": item["time"]}}
        try:
            audio = await loop_run(app.recent_audio, item)
            await _unassign(item)
            if body.get("cohort"):
                fn = await loop_run(partial(app.store.add_cohort, audio, "utterance", **meta))
                item["assigned"] = {"target": "cohort", "file": fn, "time": time.time()}
            else:
                name = body.get("name", "")
                fn = await loop_run(partial(app.store.add_sample, name, audio, "utterance", **meta))
                item["assigned"] = {"target": name, "file": fn, "time": time.time()}
            await loop_run(app.rescore, item)
            await loop_run(app.save_recent)
        except (ValueError, OSError) as e:
            return err(e)
        return web.json_response(public(item))

    @r.post("/api/recent/{rid}/unassign")
    async def unassign(req):
        item = find(req.match_info["rid"])
        try:
            await _unassign(item)
            await loop_run(app.rescore, item)
            await loop_run(app.save_recent)
        except (ValueError, OSError) as e:
            return err(e)
        return web.json_response(public(item))

    # -- people --------------------------------------------------------------
    @r.post("/api/people")
    async def add_person(req):
        try:
            return web.json_response({"name": app.store.add_person((await req.json()).get("name", ""))})
        except ValueError as e:
            return err(e)

    @r.delete("/api/people/{name}")
    async def del_person(req):
        try:
            await loop_run(app.store.delete_person, req.match_info["name"])
        except ValueError as e:
            return err(e)
        return web.json_response({"ok": True})

    @r.post("/api/people/{name}/upload")
    async def upload(req):
        name = req.match_info["name"]
        saved, failed, paths = [], [], []
        for fname, data in await read_parts(req):
            try:
                x = decode_audio(data)
                fn = await loop_run(partial(app.store.add_sample, name, x, "upload", original_name=fname))
                saved.append(fn)
                paths.append(app.store.sample_path(name, fn))
            except Exception as e:  # noqa: BLE001
                failed.append(f"{fname}: {e}")
        app.transcribe_later(paths)
        return web.json_response({"saved": saved, "failed": failed})

    @r.get("/api/people/{name}/samples")
    async def samples(req):
        try:
            name = req.match_info["name"]
            return web.json_response(next((p["samples"] for p in app.store.people() if p["name"] == name), []))
        except ValueError as e:
            return err(e)

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
            n = await loop_run(app.store.delete_samples, req.match_info["name"], [req.match_info["fn"]])
        except ValueError as e:
            return err(e)
        return web.json_response({"deleted": n})

    @r.post("/api/people/{name}/samples/delete")
    async def del_samples(req):
        try:
            n = await loop_run(app.store.delete_samples, req.match_info["name"], await files_from(req))
        except ValueError as e:
            return err(e)
        return web.json_response({"deleted": n})

    @r.post("/api/people/{name}/samples/{fn}/transcribe")
    async def transcribe_sample(req):
        try:
            p = app.store.sample_path(req.match_info["name"], req.match_info["fn"])
            if not os.path.exists(p):
                raise web.HTTPNotFound()
            return web.json_response({"text": await app.transcribe_file(p)})
        except ValueError as e:
            return err(e)
        except OSError as e:
            return err(e, 502)

    # -- cohort --------------------------------------------------------------
    @r.get("/api/cohort")
    async def cohort(_):
        return web.json_response({"cohort_norm": app.opts["cohort_norm"], "usable": app.store.cohort_size(),
                                  "samples": await loop_run(app.store.cohort_list)})

    @r.post("/api/cohort/upload")
    async def cohort_upload(req):
        saved, failed, paths = [], [], []
        for fname, data in await read_parts(req):
            try:
                x = decode_audio(data)
                fn = await loop_run(partial(app.store.add_cohort, x, "upload", original_name=fname))
                saved.append(fn)
                paths.append(app.store.cohort_path(fn))
            except Exception as e:  # noqa: BLE001
                _LOG.warning("Cohort file %s rejected: %s", fname, e)
                failed.append(f"{fname}: {e}")
        app.transcribe_later(paths)
        return web.json_response({"added": len(saved), "saved": saved, "failed": failed,
                                  "cohort_size": app.store.cohort_size()})

    @r.get("/api/cohort/{fn}")
    async def cohort_audio(req):
        try:
            p = app.store.cohort_path(req.match_info["fn"])
        except ValueError as e:
            return err(e)
        if not os.path.exists(p):
            raise web.HTTPNotFound()
        return web.FileResponse(p)

    @r.delete("/api/cohort/{fn}")
    async def cohort_delete_one(req):
        try:
            n = await loop_run(app.store.delete_cohort, [req.match_info["fn"]])
        except ValueError as e:
            return err(e)
        return web.json_response({"deleted": n, "cohort_size": app.store.cohort_size()})

    @r.post("/api/cohort/delete")
    async def cohort_delete(req):
        try:
            n = await loop_run(app.store.delete_cohort, await files_from(req))
        except ValueError as e:
            return err(e)
        return web.json_response({"deleted": n, "cohort_size": app.store.cohort_size()})

    @r.post("/api/cohort/{fn}/transcribe")
    async def cohort_transcribe(req):
        try:
            p = app.store.cohort_path(req.match_info["fn"])
            if not os.path.exists(p):
                raise web.HTTPNotFound()
            return web.json_response({"text": await app.transcribe_file(p)})
        except ValueError as e:
            return err(e)
        except OSError as e:
            return err(e, 502)

    @web.middleware
    async def no_cache(req, handler):
        resp = await handler(req)
        if req.path.startswith("/api/") and resp.content_type == "application/json":
            resp.headers.update(NO_STORE)
        return resp

    add_people_route(
        r,
        lambda: app.opts.get("shared_secret") or "",
        lambda: [p["name"] for p in app.store.people()],
    )
    w = web.Application(client_max_size=64 * 1024 * 1024, middlewares=[no_cache])
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
    # Hostname on the internal network (underscores in the slug become hyphens). The password is not logged.
    _LOG.info("People list: http://%s:%s/api/people", socket.gethostname(), int(app.opts["web_port"]))
    if app.opts.get("shared_secret"):
        _LOG.info("Shared password is set; transcripts carry a signed speaker mark")
    else:
        _LOG.info("Shared password is empty; transcripts keep the name label")
    await server.run(partial(Handler, app))


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
