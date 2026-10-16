"""Catalog of supported speaker-embedding models."""
from __future__ import annotations

import logging
import os
import urllib.request

_LOG = logging.getLogger(__name__)
BUNDLED = os.environ.get("SPEAKER_ID_BUNDLED", "/usr/share/speaker_id/models")
_SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"

# key -> (filename, download url or None if bundled, kind)
MODELS = {
    "redimnet2_b2": ("redimnet2_b2_vox2_lm.onnx", None, "raw"),
    "campplus_zh_en_advanced": ("3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx", _SHERPA, "sherpa"),
    "campplus_en_voxceleb": ("3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx", _SHERPA, "sherpa"),
    "eres2net_en_voxceleb": ("3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx", _SHERPA, "sherpa"),
    "eres2netv2_zh_cn": ("3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx", _SHERPA, "sherpa"),
    "wespeaker_resnet34_en": ("wespeaker_en_voxceleb_resnet34_LM.onnx", _SHERPA, "sherpa"),
}
VAD_FILE = "silero_vad.onnx"


def resolve(key: str, data_dir: str) -> tuple[str, str]:
    """Return (path, kind); downloads non-bundled models into <data_dir>/models."""
    fn, url, kind = MODELS[key]
    bundled = os.path.join(BUNDLED, fn)
    if os.path.exists(bundled):
        return bundled, kind
    dst_dir = os.path.join(data_dir, "models")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, fn)
    if not os.path.exists(dst):
        if not url:
            raise FileNotFoundError(bundled)
        _LOG.info("Downloading model %s", fn)
        tmp = dst + ".part"
        urllib.request.urlretrieve(url + fn, tmp)
        os.replace(tmp, dst)
    return dst, kind


def vad_path() -> str:
    return os.path.join(BUNDLED, VAD_FILE)
