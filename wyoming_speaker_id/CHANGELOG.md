# Changelog

## 0.1.1

- Fix start-up: run the service from its source directory ("No module named speaker_id").
- CI: bump GitHub Actions.

## 0.1.0

- First release: Wyoming STT proxy with local speaker identification.
- Models: ReDimNet2-B2 (bundled), CAM++, ERes2Net, ERes2NetV2, WeSpeaker ResNet34 (downloaded on demand).
- Ingress web UI: people, WAV upload, enrollment from recent utterances, scores log, threshold sliders, cohort upload.
- `sensor.voice_last_speaker` via the Supervisor API, Wyoming discovery.
