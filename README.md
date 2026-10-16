<p align="center">
  <img src="logo.jpeg" alt="VoiceGravity" width="300"/>
</p>

<h1 align="center">🎙️ VoiceGravity</h1>

<p align="center">
  <strong>Внешний голосовой контроллер для Antigravity 2.0.</strong><br>
  Печатай, вставляй и управляй клавишами - голосом.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.4%20Beta-blue" alt="Version"/>
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows-green" alt="Platform"/>
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License"/>
</p>

---

> **Важно:** это **отдельный** проект от [uuuugi/VoiceGravity](https://github.com/uuuugi/VoiceGravity) (расширение для IDE).
>
> **VoiceGravity** (этот репозиторий) — **внешний** голосовой контроллер для **Antigravity 2.0** (GUI-приложение).

---

## ✨ Возможности

- 🎤 **Распознавание русской речи** - оффлайн, через Vosk
- 🐧 **Linux** - CachyOS, Hyprland, Wayland
- 🪟 **Windows** - Windows 10/11
- 🔊 **Синтез речи** - Festival (Linux) / pyttsx3 (Windows), с возможностью смены голосов (женский / мужской)
- ⌨️ **Ввод текста** - через `wtype` (Linux) / `keyboard` (Windows)
- 📋 **Вставка из буфера** - `wl-clipboard` (Linux) / `pyperclip` (Windows)
- 🪟 **Автофокус на окно Antigravity** - через `hyprctl` (Linux) / `pygetwindow` (Windows)
- ⚡ **Push-to-Talk (PTT)** - активация распознавания по удержанию клавиши `F9` (или режим `--always-on`)
- 📊 **Статистика сессии** - подсчёт распознанных фраз, команд, ошибок, времени работы и скорости (CPM)
- 📝 **История команд** - запись истории действий в лог-файл `history.log`

---

## 📦 Установка

### 🐧 Linux (CachyOS / Arch)

**1. Системные зависимости:**

```bash
sudo pacman -S python python-pip portaudio ydotool wtype wl-clipboard festival
```

**2. Python-зависимости:**

```bash
python -m venv ~/antigravity-env
source ~/antigravity-env/bin/activate.fish
pip install vosk sounddevice keyboard
```

**3. Модель Vosk (русский язык):**

```bash
mkdir -p ~/vosk-models
cd ~/vosk-models
wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
unzip vosk-model-small-ru-0.22.zip
```

**4. Запуск:**

```bash
# Push-to-Talk режим (по умолчанию, активация по F9):
python antigravity_control.py

# Непрерывный режим прослушивания:
python antigravity_control.py --always-on
```

---

### 🪟 Windows 10/11

**1. Python-зависимости:**

```powershell
pip install vosk sounddevice pyttsx3 pyperclip keyboard pygetwindow pywin32
```

**2. Модель Vosk:**

Скачай [vosk-model-small-ru-0.22.zip](https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip) и распакуй в `C:\vosk-models\vosk-model-small-ru-0.22\`.

**3. Запуск:**

```powershell
# Push-to-Talk режим (по умолчанию, активация по F9):
python antigravity_control_windows.py

# Непрерывный режим прослушивания:
python antigravity_control_windows.py --always-on
```

---

## 📋 Команды

| Команда | Действие |
|---|---|
| **Напиши [текст]** | Печатает текст в Antigravity |
| **Напиши [текст] и отправь** | Печатает текст и нажимает Enter |
| **Вставь** | Вставляет содержимое буфера обмена |
| **Вставь и отправь** | Вставляет из буфера и нажимает Enter |
| **Отправь** | Нажимает Enter |
| **Нажми один / два / три** | Нажимает соответствующую цифру 1-9 (выбор варианта) |
| **Нажми энтер** | Нажимает Enter |
| **Нажми эскейп** | Нажимает Escape |
| **Нажми таб** | Нажимает Tab |
| **Статистика** | Показывает подробную статистику сессии (команды, CPM, время) |
| **История** | Показывает последние 10 выполненных команд |
| **Смени голос** | Переключает голос озвучки (женский / мужской) |
| **Справка** | Показывает список команд |
| **Стоп** / **Выход** | Завершает работу |

---

## 🛠️ Как это работает

1. **Vosk** слушает микрофон и распознаёт русскую речь (оффлайн).
2. **Парсер** определяет команду: печать, вставка, нажатие клавиши, справка, статистика.
3. **Контроллер** переключает фокус на окно Antigravity 2.0.
4. **wtype / keyboard** вводит текст, **ydotool / keyboard** нажимает клавиши.
5. **Festival / pyttsx3** озвучивает подтверждения.

---

## 🚀 Версия

**v0.4 (Beta)** - публичная бета-версия с исправлениями после QA-аудита.

- ✅ Работает на Linux (CachyOS, Hyprland)
- ✅ Работает на Windows (10/11)
- ⚡ Поддержка Push-to-Talk (F9) и Continuous режима
- 📊 Подсчёт статистики и история команд
- 🔊 Переключение мужского и женского голосов
- 🐛 Исправлено 7 багов после QA-аудита

---

## 📄 Лицензия

MIT License - используй, изменяй, распространяй свободно.

---

## 👤 Автор и репозиторий

**VoiceGravity**

Репозиторий проекта: [https://github.com/VoiceGravity/VoiceGravity](https://github.com/VoiceGravity/VoiceGravity)

Если проект полезен - поставь ⭐ на [GitHub](https://github.com/VoiceGravity/VoiceGravity)!
