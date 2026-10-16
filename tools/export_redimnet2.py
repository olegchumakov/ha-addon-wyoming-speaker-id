"""Export ReDimNet2 (PalabraAI/redimnet2, MIT) to ONNX with raw 16 kHz waveform input.

    pip install torch torchaudio scipy onnx onnxruntime numpy
    python tools/export_redimnet2.py b2 wyoming_speaker_id/models/redimnet2_b2_vox2_lm.onnx
"""
import sys

import numpy as np
import onnxruntime as ort
import torch

name = sys.argv[1] if len(sys.argv) > 1 else "b2"
out = sys.argv[2] if len(sys.argv) > 2 else f"redimnet2_{name}_vox2_lm.onnx"
m = torch.hub.load("PalabraAI/redimnet2", "redimnet2", model_name=name, train_type="lm", pretrained=True,
                   trust_repo=True).eval()
torch.onnx.export(m, torch.randn(1, 48000), out, input_names=["wav"], output_names=["emb"],
                  dynamic_axes={"wav": {1: "T"}}, opset_version=17, dynamo=False)
s = ort.InferenceSession(out)
for t in (16000, 48000):
    x = torch.randn(1, t)
    with torch.no_grad():
        r = m(x).numpy()
    o = s.run(None, {"wav": x.numpy()})[0]
    print(t, "cosine vs torch:", float((r * o).sum() / np.linalg.norm(r) / np.linalg.norm(o)))
