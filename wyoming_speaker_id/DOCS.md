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

1. The Home Assistant voice assistant sends the audio of your command to this add-on.
2. The add-on passes the audio straight on to Whisper (or another speech-to-text service), which turns it into text.
3. At the same time the add-on compares the voice with the recorded voice samples of your household and
   computes a **similarity** for each person (0 to 1; higher = more alike).
4. Decision:
   - similarity at least **"Recognize by name from"** and the person is clearly ahead of the next one
     (**"Lead over the next person"**) → the person's name;
   - similarity below **"Guest if similarity is below"** → "guest";
   - in between, or the phrase is too short → "unknown".
5. The name is added to the text (e.g. `[speaker: Anna] what's the weather`), so the assistant knows who asked.
   The `sensor.voice_last_speaker` sensor is updated too.

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
- After enrollment, look at the **similarity** in **Recent utterances**: your own commands vs. TV/guests,
  and put **"Recognize by name from"** between them. Typical values: 0.40–0.50 for ReDimNet2-B2,
  0.35–0.45 for CAM++.
- Commands shorter than ~0.6 s of speech ("stop") cannot be identified reliably.

Every sample shows its date, duration and text. Text comes from the pipeline when you assign a recent
utterance; uploaded files are transcribed in the background with the upstream STT (older samples
have a **Transcribe** button). Samples can be played and deleted one by one or with the checkboxes
(**Delete selected**); the person's voice profile is recalculated immediately. In **Recent utterances** the original
result stays visible next to the assignment (e.g. `guest → assigned to Anna`) together with the new
similarity; **undo** removes the sample again.

Samples are stored in `/data/people/<name>/` (text in `<file>.wav.json`) and backed up with the add-on.
Recent utterances (text, result and audio) are stored in `/data/recent/` so they survive restarts;
only the last `recent_buffer_size` are kept (0 disables the list and stores nothing).

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

## Other voices (for accuracy, optional)

In the **"Other voices"** section of the web UI you can collect recordings of people who do **not** live with
you: guests, TV, radio. Easiest: in **"Recent utterances"** send TV speech "→ other voices". Every recording
can be played, shows its text, and can be deleted (one by one or with the checkboxes).

If you switch on **"Compare with other voices"** in the configuration, a voice is also compared with these
recordings, so household members are confused with strangers less often. You need at least 20–30 recordings
(it starts working from 10; with fewer the normal mode is used). In this mode similarity is on a different
scale, so the sensitivity sliders have **their own values** and the add-on switches them **automatically**
(usually 2–3 for "Recognize by name from" and about 1 for "Guest"). Nothing needs re-tuning when you switch it
on or off. If unsure, leave it off.

## Options

| Option | Default | What it does |
|---|---|---|
| Upstream STT (Whisper) address (`upstream_uri`) | `tcp://core-whisper:10300` | where audio is sent to be turned into text |
| Voice recognition model (`model`) | `redimnet2_b2` | best left as is (table above) |
| Recognize by name from (`threshold_high`) | 0.45 | how similar a voice must be to say the name; higher = fewer mix-ups, more "unknown" |
| Guest if similarity is below (`threshold_low`) | 0.30 | below this = "guest" |
| Lead over the next person (`margin`) | 0.08 | raise it if household members get mixed up |
| Minimum speech, seconds (`min_speech_seconds`) | 0.6 | shorter phrases = "unknown" |
| How to label the text (`tag_template`) | `[speaker: {name}] {text}` | `{name}` = who, `{text}` = what was said |
| Word for a stranger / when not sure | `guest` / `unknown` | |
| Label phrases when not sure (`tag_unknown`) | on | off = such phrases are passed without a label |
| Compare with other voices (`cohort_norm`) | off | see the section above |
| "Who spoke" sensor, sensor name | on, `sensor.voice_last_speaker` | for automations |
| How many recent utterances to keep (`recent_buffer_size`) | 30 | stored on disk, survive restarts; 0 = keep none |

The sensitivity values (first four numbers) are easiest to change with the sliders in the web UI; they are
saved to `/data/settings.json` and take precedence over the configuration.

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
