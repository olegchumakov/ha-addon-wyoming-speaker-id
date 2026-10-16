"""People, enrollment samples (WAV on disk) and cached embeddings per model."""
from __future__ import annotations

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
    if not name or len(name) > 64 or name.startswith(".") or not re.fullmatch(r"[\w .\-']+", name):
        raise ValueError("Name may contain letters, digits, spaces, '.', '-', '_' and \"'\" (max 64)")
    return name


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
                out.append({"name": name, "samples": files, "usable": self.counts.get(name, 0)})
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

    def add_sample(self, name: str, x: np.ndarray, tag: str = "upload") -> str:
        name = self.add_person(name)
        fn = f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.wav"
        with open(os.path.join(self.people_dir, name, fn), "wb") as f:
            f.write(encode_wav(x))
        self.rebuild()
        return fn

    def sample_path(self, name: str, fn: str) -> str:
        name = safe_name(name)
        if "/" in fn or fn.startswith(".") or not fn.lower().endswith(".wav"):
            raise ValueError("bad file name")
        return os.path.join(self.people_dir, name, fn)

    def delete_sample(self, name: str, fn: str) -> None:
        p = self.sample_path(name, fn)
        with self._lock:
            if os.path.exists(p):
                os.remove(p)
            c = os.path.join(self.cache_dir, safe_name(name), fn + ".npy")
            if os.path.exists(c):
                os.remove(c)
            self.rebuild()

    def add_cohort(self, x: np.ndarray) -> None:
        fn = f"cohort_{int(time.time() * 1000)}.wav"
        with open(os.path.join(self.cohort_dir, fn), "wb") as f:
            f.write(encode_wav(x))
        self.rebuild()

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
