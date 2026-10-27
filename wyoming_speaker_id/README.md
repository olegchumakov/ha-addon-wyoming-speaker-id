# Home Assistant Add-on: Wyoming Speaker ID

English | [Русский](README.ru.md)

Speech-to-text proxy that tells your assistant **who is speaking**. It sits between
Assist and your existing Wyoming STT (Whisper, etc.), identifies the speaker locally
and tags the transcript, e.g. `[speaker: Anna] turn on the light`.

Leave **Shared password** empty and that label stays as it is. Set the same password
as in the voice-access integration and the label is replaced by a signed mark that
integration checks. The people list for it is `GET http://<add-on hostname>:8099/api/people`
with header `X-Speaker-Key` (401 otherwise). The log prints the URL. Port 8099 is not
published to the network. Contract and vectors: [SPEC.md](../SPEC.md).

![Supports aarch64 Architecture][aarch64-shield] ![Supports amd64 Architecture][amd64-shield]

See [DOCS.md](DOCS.md) for setup and tuning.

## Signed-mark test vector

Secret `test-secret`, time `1700000000`, nonce `0123456789abcdef`.
Message: `spk1|Anna|0.73|1700000000|0123456789abcdef|turn on the light`
HMAC-SHA256: `4e3854eaed0f699014eead3a73f1a358618a699bb372d76d6715658adad72386`

```
⟦spk1;n=Anna;c=0.73;t=1700000000;r=0123456789abcdef;s=4e3854eaed0f699014eead3a73f1a358618a699bb372d76d6715658adad72386⟧ turn on the light
```

Cyrillic name `Анна` is encoded `%D0%90%D0%BD%D0%BD%D0%B0` (uppercase hex). Full vectors,
including an unknown voice with an empty name, are in [SPEC.md](../SPEC.md).

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
