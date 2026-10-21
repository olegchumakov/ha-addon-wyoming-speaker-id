# Changelog

## 0.1.2

- Web UI: cohort management – list of cohort clips with file, date, duration and text, playback,
  per-item and bulk (multi-select) delete. Voiceprints/cohort are recomputed after deletion.
- People samples show the same details (text, date, duration) with bulk delete.
- Sample text: kept from the pipeline when a recent utterance is assigned; uploaded files are
  transcribed in the background via the upstream STT; "Transcribe" buttons for older samples.
- Recent utterances keep the original result and show the assignment ("guest → assigned to X"),
  re-score the utterance against the updated profiles, and can be un-assigned (removes the sample).
- Names starting with "_" are reserved.

## 0.1.1

- Fix start-up: run the service from its source directory ("No module named speaker_id").
- CI: bump GitHub Actions.

## 0.1.0

- First release: Wyoming STT proxy with local speaker identification.
- Models: ReDimNet2-B2 (bundled), CAM++, ERes2Net, ERes2NetV2, WeSpeaker ResNet34 (downloaded on demand).
- Ingress web UI: people, WAV upload, enrollment from recent utterances, scores log, threshold sliders, cohort upload.
- `sensor.voice_last_speaker` via the Supervisor API, Wyoming discovery.
