# Changelog

## 0.1.4

- Option names and descriptions, web UI texts and docs are back to the 0.1.2 wording. Only "Compare with
  other voices" (`cohort_norm`) keeps a plain description, and texts describe the 0.1.3 features (recent
  utterances survive restarts, connection test, automatic thresholds for the cohort mode).

## 0.1.3

- Fix: after updating, a browser could keep showing the previous version of the web UI (it was cached), so
  sample names showed as "[object Object]" and the new lists were missing. The page is now never cached,
  API answers are not cached either, a page from an older version reloads itself once, and an outdated page
  shows a notice.
- Recent utterances (text, result, audio, assignment) are stored in `/data/recent/` and survive restarts;
  only the configured number is kept, older ones are deleted automatically. They can be deleted one by one
  or in bulk (voice samples already assigned stay). Disk usage is shown.
- Web UI: "Test connection" for the speech-to-text service (Whisper) with its name, version and languages.
- "Compare with other voices" (formerly "cohort normalization") now uses its own sensitivity values that are
  switched automatically, so nothing has to be re-tuned when it is turned on or off.
- All option names and descriptions, web UI texts and docs rewritten in plain language (en/ru).
- CI: web UI render test (jsdom) against sample API answers.

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
