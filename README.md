# 🎙️ VoiceGravity

**Голосовой контроллер для Antigravity 2.0.** Печатай, вставляй и управляй клавишами — голосом.

![Version](https://img.shields.io/badge/version-0.1%20Beta-blue)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-green)
![License](https://img.shields.io/badge/license-MIT-orange)

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
sudo pacman -S python python-pip portaudio ydotool wtype wl-clipboard espeak-ng
