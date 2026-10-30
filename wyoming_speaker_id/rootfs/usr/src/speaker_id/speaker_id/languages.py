"""Which languages the add-on tells Home Assistant it supports.

Home Assistant asks for them once, when the Wyoming integration is set up, and keeps the answer. If the upstream STT
(e.g. Whisper) is still starting at that moment, an empty or wrong list would stay there until the integration is
reloaded, and every voice command would fail with "language not supported". So the list comes from, in this order:

1. the upstream STT itself (``live``);
2. the last list the same upstream reported, saved in ``/data`` (``saved``), so a restart does not need the upstream;
3. the optional ``fallback_languages`` option (``setting``).

If none of them is known, the add-on does not answer at all (Home Assistant then retries later) instead of
advertising an empty list.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

_LOG = logging.getLogger("speaker_id")
FILE_NAME = "upstream_languages.json"
_CODE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8})*$")


def collect(info) -> list[str]:
    """Sorted unique languages of installed speech-to-text models in a Wyoming Info (empty if none)."""
    langs = set()
    for prog in getattr(info, "asr", None) or []:
        if getattr(prog, "installed", True) is False:
            continue
        for model in getattr(prog, "models", None) or []:
            if getattr(model, "installed", True) is False:
                continue
            langs.update(str(lang) for lang in (getattr(model, "languages", None) or []) if lang)
    return sorted(langs)


def parse(value) -> list[str]:
    """Parse the ``fallback_languages`` option: language codes separated by commas or spaces ("ru, en")."""
    if not value:
        return []
    out = []
    for part in re.split(r"[\s,;]+", str(value)):
        part = part.strip()
        if not part:
            continue
        if not _CODE.match(part):
            _LOG.warning("Ignoring %r in fallback languages: not a language code like 'en' or 'pt-BR'", part)
            continue
        if part not in out:
            out.append(part)
    return out


class Languages:
    """Language list advertised to Home Assistant, with its source."""

    def __init__(self, data_dir: str, upstream_uri: str, fallback: str | None = None):
        self.path = os.path.join(data_dir, FILE_NAME)
        self.upstream_uri = upstream_uri
        self.live: list[str] = []
        self.saved: list[str] = self._load()
        self.fallback: list[str] = parse(fallback)

    def _load(self) -> list[str]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            _LOG.warning("Cannot read saved upstream languages: %s", e)
            return []
        if not isinstance(data, dict) or data.get("upstream_uri") != self.upstream_uri:
            return []  # saved for another upstream STT: not trustworthy for this one
        langs = data.get("languages")
        if not isinstance(langs, list):
            return []
        return [str(x) for x in langs if isinstance(x, str) and x]

    def set_live(self, langs: list[str]) -> bool:
        """Remember a list reported by the upstream right now. Empty lists are ignored. Returns True if stored."""
        langs = sorted({str(x) for x in langs if x})
        if not langs:
            return False
        self.live = langs
        if langs != self.saved:
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"upstream_uri": self.upstream_uri, "languages": langs, "time": int(time.time())}, f)
                os.replace(tmp, self.path)
                self.saved = langs
            except OSError as e:
                _LOG.warning("Cannot save upstream languages: %s", e)
        return True

    @property
    def source(self) -> str | None:
        if self.live:
            return "live"
        if self.saved:
            return "saved"
        if self.fallback:
            return "setting"
        return None

    @property
    def current(self) -> list[str]:
        """Best known list; empty only if nothing is known yet (then do not answer Home Assistant)."""
        return list(self.live or self.saved or self.fallback)
