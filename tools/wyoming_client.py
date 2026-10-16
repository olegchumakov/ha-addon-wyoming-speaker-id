"""Send audio files to a Wyoming ASR server and print the transcript (for testing).

    python tools/wyoming_client.py tcp://HOST:10310 file1.wav [file2.wav ...]
"""
import asyncio
import sys
import time

import numpy as np
import soundfile as sf
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient


async def one(uri: str, path: str, language: str | None) -> None:
    x, rate = sf.read(path, dtype="float32", always_2d=True)
    x = x[:, 0] / max(1.0, float(np.abs(x).max()))
    data = (x * 32767).astype("<i2").tobytes()
    c = AsyncClient.from_uri(uri)
    await c.connect()
    await c.write_event(Transcribe(language=language).event())
    await c.write_event(AudioStart(rate=rate, width=2, channels=1).event())
    step = rate * 2 // 10
    for i in range(0, len(data), step):
        await c.write_event(AudioChunk(rate=rate, width=2, channels=1, audio=data[i:i + step]).event())
    t = time.perf_counter()
    await c.write_event(AudioStop().event())
    while True:
        ev = await c.read_event()
        if ev is None:
            break
        if Transcript.is_type(ev.type):
            print(f"{(time.perf_counter() - t) * 1000:6.0f} ms  {path}: {Transcript.from_event(ev).text}")
            break
    await c.disconnect()


async def main() -> None:
    lang = None
    args = sys.argv[2:]
    if args and args[0].startswith("--lang="):
        lang = args.pop(0).split("=", 1)[1]
    for p in args:
        await one(sys.argv[1], p, lang)


asyncio.run(main())
