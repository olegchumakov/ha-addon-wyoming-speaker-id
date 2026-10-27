# Wyoming Speaker ID — репозиторий дополнений Home Assistant

[English](README.md) | Русский

[![Lint](https://github.com/olegchumakov/ha-addon-wyoming-speaker-id/actions/workflows/lint.yaml/badge.svg)](https://github.com/olegchumakov/ha-addon-wyoming-speaker-id/actions/workflows/lint.yaml)
[![Build](https://github.com/olegchumakov/ha-addon-wyoming-speaker-id/actions/workflows/build.yaml/badge.svg)](https://github.com/olegchumakov/ha-addon-wyoming-speaker-id/actions/workflows/build.yaml)

**Узнайте, кто говорит с вашим голосовым ассистентом.** Wyoming-прокси распознавания речи,
которое локально (CPU, без облака) определяет говорящего, пока ваш обычный STT делает
транскрипцию, и добавляет метку для агента: `[speaker: Анна] включи свет`.

[![Добавить репозиторий в Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Folegchumakov%2Fha-addon-wyoming-speaker-id)

## Дополнения

### [Wyoming Speaker ID](wyoming_speaker_id)

- Работает с любым Wyoming STT (по умолчанию — официальное дополнение Whisper) и любым языком
- Без лишней задержки: определение идёт параллельно с распознаванием
- Современные модели голоса: ReDimNet2-B2 (по умолчанию), CAM++, ERes2Net(V2), WeSpeaker
- Веб-интерфейс: люди, запись образцов из WAV или из недавних реальных команд, оценки,
  ползунки порогов
- `sensor.voice_last_speaker` для автоматизаций; автообнаружение Wyoming
- По желанию общий пароль: отметка «кто сказал» и список людей для доступа голосом
  ([SPEC.md](SPEC.md))
- amd64 и aarch64

Документация: [DOCS.ru.md](wyoming_speaker_id/DOCS.ru.md)

## Лицензия

MIT, см. [LICENSE](LICENSE). Встроенные модели распространяются по своим лицензиям, см.
[wyoming_speaker_id/models/NOTICE.md](wyoming_speaker_id/models/NOTICE.md).
