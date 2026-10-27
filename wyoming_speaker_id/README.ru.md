# Дополнение Home Assistant: Wyoming Speaker ID

[English](README.md) | Русский

Прокси распознавания речи, которое сообщает ассистенту, **кто говорит**. Стоит между
Assist и вашим Wyoming STT (Whisper и т. п.), локально определяет говорящего и
добавляет метку к тексту, например `[speaker: Анна] включи свет`.

Если **Общий пароль** пустой, всё остаётся как раньше. Если указать тот же пароль, что
и там, где решается, кому что можно голосом, вместо имени ставится отметка для этой
программы. Список людей она берёт по адресу `http://<имя дополнения>:8099/api/people`
(точный адрес пишется в журнале). Порт в домашнюю сеть не открывается. Формат и
проверочные примеры — в [SPEC.md](../SPEC.md).

![Supports aarch64 Architecture][aarch64-shield] ![Supports amd64 Architecture][amd64-shield]

Установка и настройка — в [DOCS.ru.md](DOCS.ru.md).

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
