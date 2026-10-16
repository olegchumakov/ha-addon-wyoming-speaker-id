# Wyoming Speaker ID – Home Assistant add-on repository

English | [Русский](README.ru.md)

[![Lint](https://github.com/olegchumakov/ha-addon-wyoming-speaker-id/actions/workflows/lint.yaml/badge.svg)](https://github.com/olegchumakov/ha-addon-wyoming-speaker-id/actions/workflows/lint.yaml)
[![Build](https://github.com/olegchumakov/ha-addon-wyoming-speaker-id/actions/workflows/build.yaml/badge.svg)](https://github.com/olegchumakov/ha-addon-wyoming-speaker-id/actions/workflows/build.yaml)

**Know who is talking to your voice assistant.** A Wyoming speech-to-text proxy that
identifies the speaker locally (CPU, no cloud) while your usual STT transcribes, and tags
the text for the conversation agent: `[speaker: Anna] turn on the light`.

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Folegchumakov%2Fha-addon-wyoming-speaker-id)

## Add-ons

### [Wyoming Speaker ID](wyoming_speaker_id)

- Works with any Wyoming STT (default: the official Whisper add-on) and any language
- No extra latency: identification runs in parallel with transcription
- Modern speaker models: ReDimNet2-B2 (default), CAM++, ERes2Net(V2), WeSpeaker
- Web UI: manage people, enroll from uploaded WAVs or from recent real commands,
  see scores, tune thresholds with sliders
- `sensor.voice_last_speaker` for automations; Wyoming auto-discovery
- amd64 and aarch64

Documentation: [DOCS.md](wyoming_speaker_id/DOCS.md)

## License

MIT, see [LICENSE](LICENSE). Bundled models keep their own licenses, see
[wyoming_speaker_id/models/NOTICE.md](wyoming_speaker_id/models/NOTICE.md).
