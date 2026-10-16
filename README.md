<p align="center">
  <img src="logo.jpeg" alt="VoiceGravity" width="300"/>
</p>

<h1 align="center">🎙️ VoiceGravity</h1>

<p align="center">
  <strong>Внешний голосовой контроллер для Antigravity 2.0.</strong><br>
  Печатай, вставляй и управляй клавишами - голосом.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.5%20Beta-blue" alt="Version"/>
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Ubuntu%20%7C%20Windows-green" alt="Platform"/>
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License"/>
</p>

---

> **Важно:** это **отдельный** проект от [uuuugi/VoiceGravity](https://github.com/uuuugi/VoiceGravity) (расширение для IDE).
>
> **VoiceGravity** (этот репозиторий) - **внешний** голосовой контроллер для **Antigravity 2.0** (GUI-приложение).

---

## ✨ Возможности

- 🎤 **Распознавание русской речи** - оффлайн, через Vosk
- 🐧 **Linux** - CachyOS, Arch, Hyprland, Wayland
- 🟠 **Ubuntu** - 22.04 / 24.04 LTS (X11 + Wayland, автоопределение)
- 🪟 **Windows** - Windows 10/11
- 🔊 **Синтез речи** - Festival (Linux/Ubuntu) / pyttsx3 (Windows), смена голосов (М/Ж)
- ⌨️ **Ввод текста** - `wtype` / `xdotool` / `keyboard`
- 📋 **Вставка из буфера** - `wl-clipboard` / `xclip` / `pyperclip`
- 🪟 **Автофокус на окно Antigravity** - `hyprctl` (Linux) / `wmctrl` (Ubuntu) / `pygetwindow` (Windows)
- ⚡ **Push-to-Talk (F9)** - активация по удержанию клавиши (или `--always-on`)
- 📊 **Статистика сессии** - команды, ошибки, время, скорость (CPM)
- 📝 **История команд** - лог в `history.log`
- 🔄 **Ресемплинг аудио** - автоопределение частоты (44100 -> 16000 через scipy)

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
pip install vosk sounddevice keyboard scipy
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
# Push-to-Talk (по умолчанию, активация по F9):
python antigravity_control.py

# Непрерывный режим:
python antigravity_control.py --always-on
```

---

### 🟠 Ubuntu 22.04 / 24.04 LTS

**1. Системные зависимости:**

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv portaudio19-dev xdotool xclip wmctrl festival
```

**2. Python-зависимости:**

```bash
python3 -m venv ~/antigravity-env
source ~/antigravity-env/bin/activate
pip install vosk sounddevice keyboard scipy
```

**3. Модель Vosk:**

```bash
mkdir -p ~/vosk-models
cd ~/vosk-models
wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
unzip vosk-model-small-ru-0.22.zip
```

**4. Запуск:**

```bash
# Push-to-Talk (по умолчанию, активация по F9):
python antigravity_control_ubuntu.py

# Непрерывный режим:
python antigravity_control_ubuntu.py --always-on

# Принудительный выбор сессии:
python antigravity_control_ubuntu.py --session x11
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
| **Нажми один / два / три** | Нажимает цифру 1-9 |
| **Нажми энтер** | Нажимает Enter |
| **Нажми эскейп** | Нажимает Escape |
| **Нажми таб** | Нажимает Tab |
| **Статистика** | Показывает статистику сессии (команды, CPM, время) |
| **История** | Показывает последние 10 команд |
| **Смени голос** | Переключает голос озвучки (М/Ж) |
| **Справка** | Показывает список команд |
| **Стоп** / **Выход** | Завершает работу |

---

## 🛠️ Как это работает

1. **Vosk** слушает микрофон и распознаёт русскую речь (оффлайн).
2. **Парсер** определяет команду: печать, вставка, нажатие клавиши.
3. **Контроллер** переключает фокус на окно Antigravity 2.0.
4. **wtype / xdotool / keyboard** вводит текст, **ydotool / xdotool / keyboard** нажимает клавиши.
5. **Festival / pyttsx3** озвучивает подтверждения.

---

## 🚀 Версия

**v0.5 (Beta)** - публичная бета-версия.

- ✅ Работает на Arch / CachyOS (Hyprland, Wayland)
- ✅ Работает на Ubuntu 22.04 / 24.04 LTS (X11 + Wayland)
- ✅ Работает на Windows (10/11)
- 🟠 Отдельный скрипт `antigravity_control_ubuntu.py` с автоопределением сессии
- ⌨️ Эмуляция ввода через `xdotool` (X11) и `wtype` / `ydotool` (Wayland)
- 📋 Буфер обмена через `xclip` (X11) и `wl-clipboard` (Wayland)
- 🪟 Фокус окна через `wmctrl` (X11)
- ⚡ Push-to-Talk (F9) и Continuous режим
- 📊 Статистика сессии и история команд
- 🔊 Переключение мужского и женского голосов
- 🎙️ Ресемплинг аудио (44100 -> 16000 через scipy)

---

## 📄 Лицензия

MIT License - используй, изменяй, распространяй свободно.

---

## 👤 Автор и репозиторий

**VoiceGravity**

Репозиторий проекта: [https://github.com/VoiceGravity/VoiceGravity](https://github.com/VoiceGravity/VoiceGravity)

Если проект полезен - поставь ⭐ на [GitHub](https://github.com/VoiceGravity/VoiceGravity)!
