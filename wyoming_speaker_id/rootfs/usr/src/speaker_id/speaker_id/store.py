"""People, enrollment samples (WAV on disk) and cached embeddings per model."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from .embed import SR, Embedder, Vad, decode_audio, encode_wav

MIN_ENROLL_SPEECH = 0.4


def safe_name(name: str) -> str:
    name = unicodedata.normalize("NFC", (name or "").strip())
    if not name or len(name) > 64 or name.startswith((".", "_")) or not re.fullmatch(r"[\w .\-']+", name):
        raise ValueError("Name may contain letters, digits, spaces, '.', '-', '_' and \"'\" (max 64)")
    return name


def _check_fn(fn: str) -> str:
    if not fn or "/" in fn or "\\" in fn or fn.startswith(".") or not fn.lower().endswith(".wav"):
        raise ValueError("bad file name")
    return fn


def read_meta(wav_path: str) -> dict:
    """Metadata of a stored sample: sidecar <file>.json (text, source, original, ...) plus duration/date."""
    meta: dict = {}
    side = wav_path + ".json"
    if os.path.exists(side):
        try:
            with open(side, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
    try:
        import soundfile as sf

        info = sf.info(wav_path)
        meta["duration"] = round(info.frames / float(info.samplerate), 2)
    except Exception:  # noqa: BLE001
        meta["duration"] = None
    meta.setdefault("created", os.path.getmtime(wav_path))
    meta.setdefault("text", None)
    meta.setdefault("source", "upload")
    meta["file"] = os.path.basename(wav_path)
    return meta


def write_meta(wav_path: str, **fields) -> dict:
    side = wav_path + ".json"
    meta = {}
    if os.path.exists(side):
        try:
            with open(side, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
    meta.update({k: v for k, v in fields.items() if k not in ("file", "duration")})
    tmp = side + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp, side)
    return meta


def _new_name(tag: str) -> str:
    return f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.wav"


@dataclass
class Decision:
    label: str  # speaker | uncertain | guest | short
    name: str | None = None
    score: float | None = None
    scores: dict = field(default_factory=dict)
    speech_s: float = 0.0


class Store:
    def __init__(self, data_dir: str, model_key: str, emb: Embedder, vad: Vad):
        self.people_dir = os.path.join(data_dir, "people")
        self.cohort_dir = os.path.join(data_dir, "cohort")
        self.cache_dir = os.path.join(data_dir, "embeddings", model_key)
        self.emb, self.vad = emb, vad
        self._lock = threading.RLock()
        self.centroids: dict[str, np.ndarray] = {}
        self.counts: dict[str, int] = {}
        self.cohort: np.ndarray | None = None
        for d in (self.people_dir, self.cohort_dir, self.cache_dir):
            os.makedirs(d, exist_ok=True)

    # -- embeddings -------------------------------------------------------
    def _embed_file(self, wav_path: str, cache_path: str, max_s: float | None = None) -> np.ndarray | None:
        if os.path.exists(cache_path) and os.path.getmtime(cache_path) >= os.path.getmtime(wav_path):
            return np.load(cache_path)
        with open(wav_path, "rb") as f:
            x = self.vad.trim(decode_audio(f.read()))
        if len(x) < MIN_ENROLL_SPEECH * SR:
            return None
        if max_s and len(x) > max_s * SR:
            x = x[: int(max_s * SR)]
        e = self.emb(x)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        np.save(cache_path, e)
        return e

    def rebuild(self) -> None:
        with self._lock:
            cents, counts = {}, {}
            for name in sorted(os.listdir(self.people_dir)):
                pdir = os.path.join(self.people_dir, name)
                if not os.path.isdir(pdir):
                    continue
                embs = []
                for fn in sorted(os.listdir(pdir)):
                    if fn.lower().endswith(".wav"):
                        e = self._embed_file(os.path.join(pdir, fn), os.path.join(self.cache_dir, name, fn + ".npy"))
                        if e is not None:
                            embs.append(e)
                counts[name] = len(embs)
                if embs:
                    c = np.mean(embs, axis=0)
                    cents[name] = c / (np.linalg.norm(c) + 1e-9)
            co = []
            for fn in sorted(os.listdir(self.cohort_dir)):
                if fn.lower().endswith(".wav"):
                    e = self._embed_file(os.path.join(self.cohort_dir, fn),
                                         os.path.join(self.cache_dir, "_cohort", fn + ".npy"), max_s=4.0)
                    if e is not None:
                        co.append(e)
            self.centroids, self.counts = cents, counts
            self.cohort = np.stack(co) if co else None

    # -- people -----------------------------------------------------------
    def people(self) -> list[dict]:
        out = []
        for name in sorted(os.listdir(self.people_dir)):
            pdir = os.path.join(self.people_dir, name)
            if os.path.isdir(pdir):
                files = sorted(f for f in os.listdir(pdir) if f.lower().endswith(".wav"))
                out.append({"name": name, "samples": [read_meta(os.path.join(pdir, f)) for f in files],
                            "usable": self.counts.get(name, 0)})
        return out

    def add_person(self, name: str) -> str:
        name = safe_name(name)
        os.makedirs(os.path.join(self.people_dir, name), exist_ok=True)
        return name

    def delete_person(self, name: str) -> None:
        name = safe_name(name)
        with self._lock:
            shutil.rmtree(os.path.join(self.people_dir, name), ignore_errors=True)
            shutil.rmtree(os.path.join(self.cache_dir, name), ignore_errors=True)
            self.rebuild()

    def add_sample(self, name: str, x: np.ndarray, tag: str = "upload", **meta) -> str:
        name = self.add_person(name)
        fn = _new_name(tag)
        p = os.path.join(self.people_dir, name, fn)
        with open(p, "wb") as f:
            f.write(encode_wav(x))
        write_meta(p, source=tag, created=time.time(), **meta)
        self.rebuild()
        return fn

    def sample_path(self, name: str, fn: str) -> str:
        return os.path.join(self.people_dir, safe_name(name), _check_fn(fn))

    def cohort_path(self, fn: str) -> str:
        return os.path.join(self.cohort_dir, _check_fn(fn))

    def _remove(self, wav_path: str, cache_path: str) -> bool:
        found = os.path.exists(wav_path)
        for p in (wav_path, wav_path + ".json", cache_path):
            if os.path.exists(p):
                os.remove(p)
        return found

    def delete_samples(self, name: str, files: list[str]) -> int:
        with self._lock:
            n = sum(self._remove(self.sample_path(name, fn), os.path.join(self.cache_dir, safe_name(name), fn + ".npy"))
                    for fn in files)
            self.rebuild()
        return n

    def delete_sample(self, name: str, fn: str) -> None:
        self.delete_samples(name, [fn])

    def add_cohort(self, x: np.ndarray, tag: str = "upload", **meta) -> str:
        fn = _new_name(f"cohort_{tag}")
        p = os.path.join(self.cohort_dir, fn)
        with open(p, "wb") as f:
            f.write(encode_wav(x))
        write_meta(p, source=tag, created=time.time(), **meta)
        self.rebuild()
        return fn

    def cohort_list(self) -> list[dict]:
        return [read_meta(os.path.join(self.cohort_dir, f))
                for f in sorted(os.listdir(self.cohort_dir)) if f.lower().endswith(".wav")]

    def delete_cohort(self, files: list[str]) -> int:
        with self._lock:
            n = sum(self._remove(self.cohort_path(fn), os.path.join(self.cache_dir, "_cohort", fn + ".npy"))
                    for fn in files)
            self.rebuild()
        return n

    def cohort_size(self) -> int:
        return 0 if self.cohort is None else len(self.cohort)

    # -- scoring ----------------------------------------------------------
    def score(self, e: np.ndarray, cohort_norm: bool, topk: int = 100) -> dict[str, float]:
        cents = self.centroids
        co = self.cohort
        if cohort_norm and co is not None and len(co) >= 10:
            k = min(topk, len(co))
            ce = np.sort(co @ e)[-k:]
            out = {}
            for n, c in cents.items():
                cc = np.sort(co @ c)[-k:]
                s = float(c @ e)
                out[n] = 0.5 * ((s - ce.mean()) / (ce.std() + 1e-6) + (s - cc.mean()) / (cc.std() + 1e-6))
            return out
        return {n: float(c @ e) for n, c in cents.items()}


def decide(scores: dict, speech_s: float, high: float, low: float, margin: float, min_speech: float) -> Decision:
    if speech_s < min_speech:
        return Decision("short", None, None, scores, speech_s)
    if not scores:
        return Decision("guest", None, None, scores, speech_s)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_n, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else float("-inf")
    if best >= high and best - second >= margin:
        return Decision("speaker", best_n, best, scores, speech_s)
    if best >= low:
        return Decision("uncertain", None, best, scores, speech_s)
    return Decision("guest", None, best, scores, speech_s)
