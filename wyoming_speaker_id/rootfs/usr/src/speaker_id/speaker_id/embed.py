"""Speaker embeddings and voice activity trimming."""
from __future__ import annotations

import io
import threading

import numpy as np

SR = 16000


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def decode_audio(data: bytes) -> np.ndarray:
    """Decode WAV/FLAC/OGG bytes to mono float32 at 16 kHz."""
    import soundfile as sf

    x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR and len(x):
        idx = np.arange(0, len(x), sr / SR)
        x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    return x


def encode_wav(x: np.ndarray) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, np.clip(x, -1, 1), SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class Vad:
    """Silero VAD (sherpa-onnx); returns the speech parts with a little padding."""

    def __init__(self, model_path: str, threshold: float = 0.3, min_silence: float = 0.4, pad: float = 0.1):
        import sherpa_onnx

        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = model_path
        cfg.silero_vad.threshold = threshold
        cfg.silero_vad.min_silence_duration = min_silence
        cfg.silero_vad.min_speech_duration = 0.1
        cfg.sample_rate = SR
        cfg.num_threads = 1
        self._cfg = cfg
        self._pad = int(pad * SR)
        self._mod = sherpa_onnx

    def trim(self, x: np.ndarray) -> np.ndarray:
        v = self._mod.VoiceActivityDetector(self._cfg, buffer_size_in_seconds=180)
        w = 512
        for i in range(0, len(x) - w + 1, w):
            v.accept_waveform(x[i : i + w])
        v.flush()
        segs: list[list[int]] = []
        while not v.empty():
            st = max(0, v.front.start - self._pad)
            en = min(len(x), v.front.start + len(v.front.samples) + self._pad)
            if segs and st <= segs[-1][1]:
                segs[-1][1] = en
            else:
                segs.append([st, en])
            v.pop()
        return np.concatenate([x[a:b] for a, b in segs]) if segs else np.zeros(0, np.float32)


class Embedder:
    """kind 'raw': ONNX graph with input 'wav' [1, T] float32 in [-1, 1] (ReDimNet2 export);
    kind 'sherpa': any sherpa-onnx speaker embedding model."""

    def __init__(self, path: str, kind: str, threads: int = 1):
        self._lock = threading.Lock()
        self.kind = kind
        if kind == "raw":
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.intra_op_num_threads = threads
            so.inter_op_num_threads = 1
            self._sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        else:
            import sherpa_onnx

            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=path, num_threads=threads)
            self._sx = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        with self._lock:
            if self.kind == "raw":
                e = self._sess.run(None, {"wav": x[None, :].astype(np.float32)})[0][0]
            else:
                s = self._sx.create_stream()
                s.accept_waveform(SR, x)
                s.input_finished()
                e = np.asarray(self._sx.compute(s), dtype=np.float32)
        return e / (np.linalg.norm(e) + 1e-9)
