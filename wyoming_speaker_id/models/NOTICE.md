# Bundled models

## redimnet2_b2_vox2_lm.onnx

ReDimNet2-B2 (large-margin fine-tuned on VoxCeleb2), from
https://github.com/PalabraAI/redimnet2 – exported to ONNX (opset 17, input `wav` [1, T]
float32 16 kHz in [-1, 1], output 192-dim embedding) with `tools/export_redimnet2.py`.

MIT License, Copyright (c) PalabraAI. Paper: "ReDimNet2: Scaling Speaker Verification via
Time-Pooled Dimension Reshaping". Based on ReDimNet by ID R&D (MIT).

## silero_vad.onnx

Silero VAD, https://github.com/snakers4/silero-vad – MIT License, Copyright (c) Silero Team.
Distributed via https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models.

## Downloaded on demand (not in this repository)

3D-Speaker CAM++/ERes2Net/ERes2NetV2 and WeSpeaker ResNet34 – Apache-2.0, from
https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models
