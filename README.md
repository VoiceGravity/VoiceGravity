<p align="center">
  <img src="logo.jpeg" alt="VoiceGravity" width="300"/>
</p>

<h1 align="center">🎙️ VoiceGravity</h1>

<p align="center">
  <strong>Голосовой контроллер для Antigravity 2.0.</strong><br>
  Печатай, вставляй и управляй клавишами — голосом.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1%20Beta-blue" alt="Version"/>
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows-green" alt="Platform"/>
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License"/>
</p>

---

## ✨ Возможности

- 🎤 **Распознавание русской речи** — оффлайн, через Vosk
- 🐧 **Linux** — CachyOS, Hyprland, Wayland
- 🪟 **Windows** — Beta-версия
- 🔊 **Синтез речи** — Festival (Linux) / pyttsx3 (Windows)
- ⌨️ **Ввод текста** — через `wtype` (Linux) / `keyboard` (Windows)
- 📋 **Вставка из буфера** — `wl-clipboard` (Linux) / `pyperclip` (Windows)
- 🪟 **Автофокус на окно Antigravity** — через `hyprctl` (Linux) / `pygetwindow` (Windows)

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
pip install vosk sounddevice
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
python antigravity_control.py
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
python antigravity_control_windows.py
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
| **Нажми энтер** | Нажимает Enter |
| **Нажми эскейп** | Нажимает Escape |
| **Нажми таб** | Нажимает Tab |
| **Справка** | Показывает список команд |
| **Стоп** / **Выход** | Завершает работу |

---

## 🛠️ Как это работает

1. **Vosk** слушает микрофон и распознаёт русскую речь (оффлайн).
2. **Парсер** определяет команду: печать, вставка, нажатие клавиши.
3. **Контроллер** переключает фокус на окно Antigravity.
4. **wtype / keyboard** вводит текст, **ydotool / keyboard** нажимает клавиши.
5. **Festival / pyttsx3** озвучивает подтверждения.

---

## 🚀 Версия

**v0.1 (Beta)** — первая публичная версия.

- ✅ Работает на Linux (CachyOS, Hyprland)
- ✅ Работает на Windows (Beta)
- ⚠️ Возможны баги, присылайте отзывы

---

## 📄 Лицензия

MIT License — используй, изменяй, распространяй свободно.

---

## 👤 Автор

**VoiceGravity**

Если проект полезен — поставь ⭐ на GitHub!
