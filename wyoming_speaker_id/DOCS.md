# Wyoming Speaker ID

English | [Русский](DOCS.ru.md)

This add-on is a Wyoming speech-to-text service that forwards audio to your real STT
(for example the Whisper add-on) and, **in parallel**, identifies the speaker from
the same audio. The transcript is returned with a tag such as
`[speaker: Anna] what's the weather`, so a conversation agent (LLM) knows who asked.
Everything runs locally on the CPU; identification takes ~50–150 ms and finishes
while the STT is still working, so it adds practically no latency.

It works with any language: voiceprints do not depend on what is said.

## How it works

1. Assist streams audio to this add-on (Wyoming, port 10310).
2. The audio is streamed unchanged to the upstream STT.
3. When the command ends, silence is cut (Silero VAD) and a speaker embedding is computed.
4. The embedding is compared (cosine similarity) with the voiceprint of every enrolled person:
   - score ≥ **threshold "known"** and lead over the 2nd person ≥ **margin** → the person's name;
   - score between the thresholds → **unknown label**;
   - score below **threshold "guest"** → **guest label**;
   - less than **minimum speech** → unknown label.
5. The transcript is rewritten with the **tag template** and returned to Assist.
   `sensor.voice_last_speaker` is updated (state = name/label; attributes: `decision`,
   `person`, `score`, `scores`, `speech_seconds`, `text`).

## Installation

1. Add this repository: **Settings → Add-ons → Add-on store → ⋮ → Repositories** →
   `https://github.com/olegchumakov/ha-addon-wyoming-speaker-id`.
2. Install **Wyoming Speaker ID** and start it.
3. Home Assistant discovers it as a new **Wyoming Protocol** integration – click *Configure*.
   (Manual: host = the add-on hostname shown in the log, port 10310.)
4. In **Settings → Voice assistants**, choose *speaker-id* as the speech-to-text engine of
   your pipeline. Keep the language you used before.

The default upstream is `tcp://core-whisper:10300` (official Whisper add-on). Any Wyoming
STT works, also outside Home Assistant (`tcp://192.0.2.10:10300`).

## Enrollment

Open the add-on web UI (**Speaker ID** in the sidebar).

- **Add person**, then either upload WAV/FLAC/OGG files, or
- use the assistant normally and assign items from **Recent utterances** to the right person.
  This is the best source, because the audio comes from your real microphone and room.

Recommendations:

- 20–40 commands per person, recorded by the satellite you use, at different distances,
  volumes and times of day. A few seconds each; the wake word alone is too short.
- Do not enroll TV or other people's audio into a person.
- After enrollment, look at the scores in **Recent utterances**: your own commands vs. TV/guests,
  and put **threshold "known"** between them. Typical values: 0.40–0.50 for ReDimNet2-B2,
  0.35–0.45 for CAM++.
- Commands shorter than ~0.6 s of speech ("stop") cannot be identified reliably.

Every sample shows its date, duration and text. Text comes from the pipeline when you assign a recent
utterance; uploaded files are transcribed in the background with the upstream STT (older samples
have a **Transcribe** button). Samples can be played and deleted one by one or with the checkboxes
(**Delete selected**); the voiceprint is recomputed immediately. In **Recent utterances** the original
result stays visible next to the assignment (e.g. `guest → assigned to Anna`) together with the new
score; **undo** removes the sample again.

Samples are stored in `/data/people/<name>/` (text in `<file>.wav.json`) and backed up with the add-on.
Recent utterances are kept **in memory only** and disappear on restart.

## Models

| Option | Model | Size | License | Notes |
|---|---|---|---|---|
| `redimnet2_b2` (default) | ReDimNet2-B2, VoxCeleb2, large-margin | 16 MB, bundled | MIT | best separation in our tests, ~60 ms / 3 s on one desktop core |
| `campplus_zh_en_advanced` | 3D-Speaker CAM++ (zh+en) | 27 MB | Apache-2.0 | fastest, very good cross-lingual |
| `campplus_en_voxceleb` | 3D-Speaker CAM++ VoxCeleb | 28 MB | Apache-2.0 | |
| `eres2net_en_voxceleb` | 3D-Speaker ERes2Net VoxCeleb | 25 MB | Apache-2.0 | |
| `eres2netv2_zh_cn` | 3D-Speaker ERes2NetV2 | 68 MB | Apache-2.0 | ~5× slower |
| `wespeaker_resnet34_en` | WeSpeaker ResNet34-LM | 25 MB | Apache-2.0 | weaker on far-field audio |

Non-bundled models are downloaded once from the
[sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models)
into `/data/models`. Switching models recomputes the voiceprints from stored samples.
Thresholds are model-specific – re-check them after switching.

## Cohort normalization (optional)

Upload 50+ short clips of *other* people (not household members, preferably recorded by the
same microphone, e.g. TV speech assigned from **Recent utterances → cohort**) and enable
`cohort_norm`. The cohort list shows each clip with its text and can be cleaned up the same way
(play, delete, multi-select). Scores then become z-scores (AS-norm) – raise the thresholds (typical
"known" 3–5, "guest" 1.5–2.5).

## Options

| Option | Default | Description |
|---|---|---|
| `upstream_uri` | `tcp://core-whisper:10300` | Wyoming STT that does the transcription |
| `model` | `redimnet2_b2` | speaker model (table above) |
| `threshold_high` | 0.45 | similarity needed to name a person |
| `threshold_low` | 0.30 | below: guest |
| `margin` | 0.08 | lead over the second person |
| `min_speech_seconds` | 0.6 | shorter speech is not identified |
| `tag_template` | `[speaker: {name}] {text}` | `{name}`, `{text}` placeholders |
| `guest_label` / `unknown_label` | `guest` / `unknown` | labels used in the tag and sensor |
| `tag_unknown` | true | tag uncertain / too short commands |
| `cohort_norm` | false | AS-norm with uploaded cohort |
| `publish_sensor`, `sensor_entity` | true, `sensor.voice_last_speaker` | last-speaker sensor |
| `recent_buffer_size` | 30 | utterances kept in memory for the UI |

Thresholds, margin and minimum speech can also be changed live with the sliders in the
web UI (stored in `/data/settings.json`, they override the options).

## Using the speaker in Home Assistant

- LLM agents read the tag directly. Add to the agent prompt, e.g.: *"The user message may
  start with `[speaker: NAME]`. It is the identified speaker; `guest` means an unknown voice
  – do not perform security-sensitive actions for guests."*
- Automations can use `sensor.voice_last_speaker` (note: the sensor is not restored after
  a Home Assistant restart until the next command).

## Security / anti-spoofing

Speaker identification is a convenience feature, not authentication. A recording of your
voice will be accepted. Do not use it as the only protection for locks or alarms.

## Credits

ReDimNet2 – PalabraAI ([MIT](https://github.com/PalabraAI/redimnet2)); CAM++/ERes2Net –
[3D-Speaker](https://github.com/modelscope/3D-Speaker) (Apache-2.0); WeSpeaker (Apache-2.0);
sherpa-onnx (Apache-2.0); Silero VAD (MIT); Wyoming (MIT).
