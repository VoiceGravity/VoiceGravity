#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
Голосовой контроллер терминала Antigravity v0.3 (Beta) для CachyOS / Wayland
=============================================================================
Архитектура:
  - Распознавание речи: Vosk (оффлайн, модель vosk-model-small-ru-0.22)
  - Захват звука: sounddevice (16 кГц, моно, 16-бит PCM)
  - Синтез речи: Festival (серверный режим, поддержка мужского и женского голоса)
  - Эмуляция ввода: wtype (Wayland-native) + ydotool (/run/ydotoold.socket)
  - Буфер обмена Wayland: wl-clipboard (wl-paste)
  - Push-to-Talk: клавиша F9 (библиотека keyboard, опционально)

Поддерживаемые голосовые команды:
  1. Нажатие клавиш:
     - "нажми три"                  -> ввод '3'
     - "нажми энтер"                -> клавиша Enter
     - "нажми один два три"         -> последовательный ввод '1', '2', '3'
     - Поддержка: 0-9, Enter, Space, Esc, Tab, Стрелки, F1-F5, Backspace, Y/N
  2. Вставка из буфера:
     - "вставь"                     -> чтение через wl-paste + Ctrl+V
     - "вставь и отправь"           -> вставка + Enter
  3. Ввод текста голосом:
     - "напиши [текст]"             -> wtype / ydotool type
     - "напиши [текст] и отправь"   -> ввод текста + Enter
  4. Отправка:
     - "отправь"                    -> Enter
  5. Управление и система:
     - "справка" / "помощь"         -> вывод таблицы команд
     - "статистика"                 -> статистика распознавания и команд
     - "история"                    -> последние 10 выполненных команд
     - "смени голос"                -> переключение голоса TTS (М/Ж)
     - "стоп" / "выход"             -> завершение работы
=============================================================================
"""

import os
import sys
import json
import time
import queue
import socket
import shutil
import signal
import logging
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any

class CustomFormatter(logging.Formatter):
    FORMATS = {
        logging.DEBUG: "🔍 \033[90m%(asctime)s [DEBUG] %(message)s\033[0m",
        logging.INFO: "\033[92m%(message)s\033[0m",
        logging.WARNING: "\033[93m⚠️  %(message)s\033[0m",
        logging.ERROR: "\033[91m❌ %(message)s\033[0m",
        logging.CRITICAL: "\033[1;91m🚨 %(message)s\033[0m",
    }

    def __init__(self):
        super().__init__()
        self._formatters = {
            level: logging.Formatter(fmt, datefmt="%H:%M:%S")
            for level, fmt in self.FORMATS.items()
        }
        self._default_formatter = logging.Formatter("%(message)s")

    def format(self, record):
        formatter = self._formatters.get(record.levelno, self._default_formatter)
        return formatter.format(record)

logger = logging.getLogger("AntigravityVoice")
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(CustomFormatter())
logger.addHandler(console_handler)

class SessionStats:
    def __init__(self):
        self.stats: Dict[str, Any] = {
            "commands": 0,
            "recognized": 0,
            "errors": 0,
            "start_time": time.time(),
        }

    def record_recognized(self) -> None:
        self.stats["recognized"] += 1

    def record_command(self) -> None:
        self.stats["commands"] += 1

    def record_error(self) -> None:
        self.stats["errors"] += 1

    def get_summary(self) -> str:
        elapsed = max(1.0, time.time() - self.stats["start_time"])
        minutes = elapsed / 60.0
        cpm = self.stats["commands"] / minutes
        hours = int(elapsed // 3600)
        mins = int((elapsed % 3600) // 60)
        secs = int(elapsed % 60)
        elapsed_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
        lines = [
            "\n" + "=" * 55,
            " 📊 СТАТИСТИКА СЕССИИ VOICEGRAVITY",
            "=" * 55,
            f" 🗣️  Всего распознано фраз:     {self.stats['recognized']}",
            f" ⚙️  Выполнено команд:          {self.stats['commands']}",
            f" ⚠️  Ошибок / не распознано:    {self.stats['errors']}",
            f" ⏱️  Время работы сессии:       {elapsed_str}",
            f" 📈 Средняя скорость:           {cpm:.1f} команд/мин",
            "=" * 55,
        ]
        return "\n".join(lines)


class CommandHistory:
    def __init__(self, log_path: Optional[Path] = None):
        if log_path is None:
            self.log_path = Path.home() / "VoiceGravity" / "history.log"
        else:
            self.log_path = Path(log_path)
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug(f"Не удалось создать каталог истории: {e}")

    def log(self, phrase: str, cmd_type: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {phrase} -> {cmd_type}\n"
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.debug(f"Ошибка записи в history.log: {e}")

    def get_recent(self, count: int = 10) -> List[str]:
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            return lines[-count:]
        except Exception as e:
            logger.debug(f"Ошибка чтения history.log: {e}")
            return []


class HotkeyManager:
    def __init__(self, key: str = "f9", always_on: bool = False):
        self.key = key
        self.always_on = always_on
        self.keyboard_available = False
        self._last_pressed_time = 0.0

        if not self.always_on:
            try:
                import keyboard
                _ = keyboard.is_pressed(self.key)
                self.keyboard_available = True
                logger.info(f"⚡ Режим Push-to-Talk активен: удерживайте [{self.key.upper()}] во время речи.")
            except (ImportError, Exception) as e:
                logger.warning(
                    f"⚠️  Модуль 'keyboard' недоступен ({e}). "
                    f"Активирован режим постоянного слушания (--always-on)."
                )
                self.always_on = True

    def poll(self) -> None:
        if self.always_on or not self.keyboard_available:
            return
        try:
            import keyboard
            if keyboard.is_pressed(self.key):
                self._last_pressed_time = time.time()
        except Exception:
            pass

    def is_active(self) -> bool:
        if self.always_on or not self.keyboard_available:
            return True
        try:
            import keyboard
            if keyboard.is_pressed(self.key):
                return True
        except Exception as e:
            logger.warning(f"⚠️ Ошибка опроса клавиши {self.key.upper()}: {e}. Активирован режим (--always-on).")
            self.always_on = True
            return True
        return (time.time() - self._last_pressed_time) < 1.5


KEY_ESC       = 1
KEY_1         = 2
KEY_2         = 3
KEY_3         = 4
KEY_4         = 5
KEY_5         = 6
KEY_6         = 7
KEY_7         = 8
KEY_8         = 9
KEY_9         = 10
KEY_0         = 11
KEY_BACKSPACE = 14
KEY_TAB       = 15
KEY_Y         = 21
KEY_ENTER     = 28
KEY_LEFTCTRL  = 29
KEY_V         = 47
KEY_N         = 49
KEY_SPACE     = 57
KEY_F1        = 59
KEY_F2        = 60
KEY_F3        = 61
KEY_F4        = 62
KEY_F5        = 63
KEY_UP        = 103
KEY_LEFT      = 105
KEY_RIGHT     = 106
KEY_DOWN      = 108

MULTI_WORD_KEY_MAP = {
    ("стрелка", "вверх"):   (KEY_UP, "Стрелка вверх"),
    ("стрелку", "вверх"):   (KEY_UP, "Стрелка вверх"),
    ("стрелка", "вниз"):    (KEY_DOWN, "Стрелка вниз"),
    ("стрелку", "вниз"):    (KEY_DOWN, "Стрелка вниз"),
    ("стрелка", "влево"):   (KEY_LEFT, "Стрелка влево"),
    ("стрелку", "влево"):   (KEY_LEFT, "Стрелка влево"),
    ("стрелка", "вправо"):  (KEY_RIGHT, "Стрелка вправо"),
    ("стрелку", "вправо"):  (KEY_RIGHT, "Стрелка вправо"),
    ("ф", "один"):          (KEY_F1, "F1"),
    ("эф", "один"):         (KEY_F1, "F1"),
    ("f", "один"):          (KEY_F1, "F1"),
    ("ф", "два"):           (KEY_F2, "F2"),
    ("эф", "два"):          (KEY_F2, "F2"),
    ("f", "два"):           (KEY_F2, "F2"),
    ("ф", "три"):           (KEY_F3, "F3"),
    ("эф", "три"):          (KEY_F3, "F3"),
    ("f", "три"):           (KEY_F3, "F3"),
    ("ф", "четыре"):        (KEY_F4, "F4"),
    ("эф", "четыре"):       (KEY_F4, "F4"),
    ("f", "четыре"):        (KEY_F4, "F4"),
    ("ф", "пять"):          (KEY_F5, "F5"),
    ("эф", "пять"):         (KEY_F5, "F5"),
    ("f", "пять"):          (KEY_F5, "F5"),
}

SINGLE_WORD_KEY_MAP = {
    "ноль":      (KEY_0, "0"),
    "0":         (KEY_0, "0"),
    "один":      (KEY_1, "1"),
    "раз":       (KEY_1, "1"),
    "единица":   (KEY_1, "1"),
    "1":         (KEY_1, "1"),
    "два":       (KEY_2, "2"),
    "двойка":    (KEY_2, "2"),
    "2":         (KEY_2, "2"),
    "три":       (KEY_3, "3"),
    "тройка":    (KEY_3, "3"),
    "3":         (KEY_3, "3"),
    "четыре":    (KEY_4, "4"),
    "четверка":  (KEY_4, "4"),
    "четвёрка":  (KEY_4, "4"),
    "4":         (KEY_4, "4"),
    "пять":      (KEY_5, "5"),
    "пятерка":   (KEY_5, "5"),
    "пятёрка":   (KEY_5, "5"),
    "5":         (KEY_5, "5"),
    "шесть":     (KEY_6, "6"),
    "шестерка":  (KEY_6, "6"),
    "шестёрка":  (KEY_6, "6"),
    "6":         (KEY_6, "6"),
    "семь":      (KEY_7, "7"),
    "семерка":   (KEY_7, "7"),
    "семёрка":   (KEY_7, "7"),
    "7":         (KEY_7, "7"),
    "восемь":    (KEY_8, "8"),
    "восьмерка": (KEY_8, "8"),
    "восьмёрка": (KEY_8, "8"),
    "8":         (KEY_8, "8"),
    "девять":    (KEY_9, "9"),
    "девятка":   (KEY_9, "9"),
    "9":         (KEY_9, "9"),

    "энтер":     (KEY_ENTER, "Enter"),
    "ентер":     (KEY_ENTER, "Enter"),
    "ввод":      (KEY_ENTER, "Enter"),
    "enter":     (KEY_ENTER, "Enter"),

    "пробел":    (KEY_SPACE, "Space"),
    "спейс":     (KEY_SPACE, "Space"),
    "space":     (KEY_SPACE, "Space"),

    "эскейп":    (KEY_ESC, "Esc"),
    "ескейп":    (KEY_ESC, "Esc"),
    "эскейпт":   (KEY_ESC, "Esc"),
    "ескейпт":   (KEY_ESC, "Esc"),
    "искейп":    (KEY_ESC, "Esc"),
    "отмена":    (KEY_ESC, "Esc"),
    "esc":       (KEY_ESC, "Esc"),

    "таб":       (KEY_TAB, "Tab"),
    "табуляция": (KEY_TAB, "Tab"),
    "tab":       (KEY_TAB, "Tab"),

    "бэкспейс":  (KEY_BACKSPACE, "Backspace"),
    "бекспейс":  (KEY_BACKSPACE, "Backspace"),
    "стереть":   (KEY_BACKSPACE, "Backspace"),
    "стирание":  (KEY_BACKSPACE, "Backspace"),
    "удалить":   (KEY_BACKSPACE, "Backspace"),
    "удаление":  (KEY_BACKSPACE, "Backspace"),
    "backspace": (KEY_BACKSPACE, "Backspace"),

    "вверх":     (KEY_UP, "Стрелка вверх"),
    "вниз":      (KEY_DOWN, "Стрелка вниз"),
    "влево":     (KEY_LEFT, "Стрелка влево"),
    "вправо":    (KEY_RIGHT, "Стрелка вправо"),

    "f1":        (KEY_F1, "F1"),
    "ф1":        (KEY_F1, "F1"),
    "f2":        (KEY_F2, "F2"),
    "ф2":        (KEY_F2, "F2"),
    "f3":        (KEY_F3, "F3"),
    "ф3":        (KEY_F3, "F3"),
    "f4":        (KEY_F4, "F4"),
    "ф4":        (KEY_F4, "F4"),
    "f5":        (KEY_F5, "F5"),
    "ф5":        (KEY_F5, "F5"),

    "игрек":     (KEY_Y, "Y"),
    "вай":       (KEY_Y, "Y"),
    "y":         (KEY_Y, "Y"),
    "да":        (KEY_Y, "Y"),
    "эн":        (KEY_N, "N"),
    "n":         (KEY_N, "N"),
    "нет":       (KEY_N, "N"),
}

FILLER_WORDS = {
    "клавиша", "клавиши", "клавишу",
    "кнопка", "кнопки", "кнопку",
    "цифра", "цифру", "цифры",
    "буква", "букву", "буквы",
    "и", "затем", "потом", "далее", "пожалуйста",
    "на", "мне", "же"
}

class VoiceSynthesizer:
    def __init__(self, enabled: bool = True, port: int = 1314, voice: str = "ru_female"):
        self.enabled = enabled
        self.port = port
        self.current_voice = "ru_female" if ("fem" in voice.lower() or "жен" in voice.lower() or "irina" in voice.lower()) else "ru_male"
        self._queue = queue.Queue()
        self._server_process = None
        self._thread = None

        if not self.enabled:
            return

        if not self._start_server():
            logger.warning("Festival сервер не запущен. TTS отключён.")
            self.stop()
            self.enabled = False
            return

        if not self._load_voice():
            logger.warning("Русский голос не загружен. TTS отключён.")
            self.stop()
            self.enabled = False
            return

        self._apply_voice_params(self.current_voice)

        self._thread = threading.Thread(target=self._worker, daemon=True, name="TTS-Worker")
        self._thread.start()
        display_name = "женский" if self.current_voice == "ru_female" else "мужской"
        logger.info(f"🎙️ Festival сервер запущен. Голос: {display_name} ({self.current_voice}).")

    def _start_server(self) -> bool:
        try:
            with socket.create_connection(("localhost", self.port), timeout=0.3):
                logger.info(f"Festival сервер уже запущен на порту {self.port}.")
                return True
        except (ConnectionRefusedError, OSError):
            pass

        try:
            env = os.environ.copy()
            env["FESTIVAL_VOICES"] = "/usr/share/festival/voices"
            self._server_process = subprocess.Popen(
                ["festival", "--server"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            for _ in range(20):
                if self._server_process.poll() is not None:
                    logger.error(f"Festival сервер аварийно завершился с кодом {self._server_process.poll()}.")
                    return False
                time.sleep(0.2)
                try:
                    with socket.create_connection(("localhost", self.port), timeout=0.5):
                        return True
                except (ConnectionRefusedError, OSError):
                    continue
            logger.warning("Festival сервер не отвечает на порту.")
            return False
        except (FileNotFoundError, OSError) as e:
            logger.error(f"Не удалось запустить Festival: {e}")
            return False

    def _send_scheme(self, scheme_code: str) -> bool:
        try:
            with socket.create_connection(("localhost", self.port), timeout=5) as sock:
                sock.sendall(scheme_code.encode("utf-8") + b"\n")
                sock.settimeout(5)
                try:
                    sock.recv(1024)
                except socket.timeout:
                    pass
            return True
        except Exception as e:
            logger.debug(f"Ошибка отправки в Festival: {e}")
            return False

    def _load_voice(self) -> bool:
        return self._send_scheme('(voice_msu_ru_nsh_clunits)')

    def _apply_voice_params(self, voice_type: str) -> bool:
        if "fem" in voice_type.lower() or "жен" in voice_type.lower():
            scheme = "(set! duffint_params '((start 220) (end 180)))\n(Parameter.set 'Duration_Stretch 0.95)"
        else:
            scheme = "(set! duffint_params '((start 115) (end 90)))\n(Parameter.set 'Duration_Stretch 1.0)"
        return self._send_scheme(scheme)

    def set_voice(self, voice_type: str) -> str:
        new_voice = "ru_female" if ("fem" in voice_type.lower() or "жен" in voice_type.lower() or "irina" in voice_type.lower()) else "ru_male"
        self.current_voice = new_voice
        self._apply_voice_params(new_voice)
        return self.current_voice

    def toggle_voice(self) -> str:
        new_voice = "ru_male" if self.current_voice == "ru_female" else "ru_female"
        self.set_voice(new_voice)
        display_name = "мужской" if new_voice == "ru_male" else "женский"
        self.speak(f"Установлен {display_name} голос")
        return new_voice

    def _worker(self):
        while True:
            text = self._queue.get()
            if text is None:
                break
            if text:
                safe_text = (
                    text.replace('\\', '\\\\')
                    .replace('"', '\\"')
                    .replace('\n', ' ')
                    .replace('\r', ' ')
                )
                scheme = f'(SayText "{safe_text}")'
                self._send_scheme(scheme)
            self._queue.task_done()

    def speak(self, text: str) -> None:
        if self.enabled and text:
            self._queue.put(text)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout=1.0)
        if self._server_process:
            try:
                self._send_scheme('(exit)')
            except Exception:
                pass
            time.sleep(0.3)
            if self._server_process.poll() is None:
                self._server_process.terminate()
                try:
                    self._server_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._server_process.kill()
            self._server_process = None


class AntigravityController:
    def __init__(self, socket_path: str = "/run/ydotoold.socket", tts: Optional[VoiceSynthesizer] = None):
        self.socket_path = socket_path
        self.tts = tts
        self._env = os.environ.copy()
        self._env["YDOTOOL_SOCKET"] = self.socket_path

        self._check_prerequisites()

    def _check_prerequisites(self) -> None:
        if not shutil.which("ydotool"):
            logger.critical("Утилита ydotool не найдена в PATH! Установите: sudo pacman -S ydotool")
            sys.exit(1)

        if not os.path.exists(self.socket_path):
            logger.warning(f"Сокет демона {self.socket_path} не обнаружен.")
            logger.warning("Убедитесь, что служба запущена: sudo systemctl start ydotoold.service")
        else:
            logger.info(f"🔌 Сокет ydotool подключен: {self.socket_path}")

        if not shutil.which("wl-paste"):
            logger.warning("Утилита wl-paste не найдена. Установите: sudo pacman -S wl-clipboard")

        if not shutil.which("wtype"):
            logger.warning("Утилита wtype не найдена. Для корректного ввода кириллицы установите: sudo pacman -S wtype")

    def activate_antigravity_window(self) -> bool:
        if not shutil.which("hyprctl"):
            return False

        try:
            result = subprocess.run(
                ["hyprctl", "dispatch", 'hl.dsp.focus({ window = "class:antigravity" })'],
                capture_output=True, text=True, timeout=2.0,
            )
            if "ok" in result.stdout.lower():
                logger.debug("Фокус переключён на окно Antigravity (hl.dsp.focus)")
                return True

            fallback = subprocess.run(
                ["hyprctl", "dispatch", "focuswindow", "class:antigravity"],
                capture_output=True, text=True, timeout=2.0,
            )
            if "ok" in fallback.stdout.lower():
                logger.debug("Фокус переключён на окно Antigravity (focuswindow)")
                return True

            logger.warning(f"Не удалось активировать окно: {result.stdout.strip()} {result.stderr.strip()}")
            return False
        except Exception as e:
            logger.warning(f"Ошибка активации окна: {e}")
            return False

    def _run_ydotool(self, *args: str) -> bool:
        cmd = ["ydotool", *args]
        try:
            res = subprocess.run(cmd, env=self._env, capture_output=True, text=True, timeout=5.0)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip()
                logger.error(f"ydotool вернул ошибку {res.returncode}: {err_msg}")
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error("Таймаут выполнения команды ydotool.")
            return False
        except Exception as e:
            logger.error(f"Исключение при вызове ydotool: {e}")
            return False

    def press_keys(self, keycodes: List[int], key_names: List[str]) -> None:
        if not keycodes:
            return

        self.activate_antigravity_window()
        time.sleep(0.2)

        display_names = ", ".join(key_names)
        logger.info(f"🔘 Нажатие клавиш: \033[1m{display_names}\033[0m (коды: {keycodes})")

        args = ["key"]
        for code in keycodes:
            args.extend([f"{code}:1", f"{code}:0"])

        success = self._run_ydotool(*args)
        if success and self.tts:
            if len(key_names) == 1:
                self.tts.speak(key_names[0])
            else:
                self.tts.speak("Нажато")

    def press_enter(self, speak: bool = True) -> None:
        logger.info("↵  \033[1mОтправка (Enter)\033[0m")
        self.activate_antigravity_window()
        time.sleep(0.2)
        success = self._run_ydotool("key", f"{KEY_ENTER}:1", f"{KEY_ENTER}:0")
        if success and speak and self.tts:
            self.tts.speak("Отправлено")

    def read_clipboard(self) -> str:
        try:
            res = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0:
                return res.stdout
            return ""
        except FileNotFoundError:
            logger.error("wl-paste не найден. Установите wl-clipboard.")
            return ""
        except Exception as e:
            logger.error(f"Ошибка чтения буфера обмена: {e}")
            return ""

    def paste_from_clipboard(self, and_send: bool = False) -> None:
        content = self.read_clipboard()
        if not content:
            logger.warning("📋 Буфер обмена пуст!")
            if self.tts:
                self.tts.speak("Буфер пуст")
            return

        preview = content[:35] + ("..." if len(content) > 35 else "")
        preview_clean = preview.replace("\n", " ")
        logger.info(f"📋 Вставка из буфера ({len(content)} симв.): «\033[1m{preview_clean}\033[0m»")

        self.activate_antigravity_window()
        time.sleep(0.3)

        success = False
        if shutil.which("wtype"):
            try:
                result = subprocess.run(
                    ["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
                    capture_output=True, text=True, timeout=3.0,
                )
                if result.returncode == 0:
                    success = True
                    logger.info("📥 Вставлено через wtype (Ctrl+V)")
            except Exception as e:
                logger.debug(f"wtype ошибка: {e}")

        if not success:
            success = self._run_ydotool("key", "29:1", "47:1", "47:0", "29:0")
            if success:
                logger.info("📥 Вставлено через ydotool (Ctrl+V)")

        if not success:
            if shutil.which("wtype"):
                try:
                    res = subprocess.run(["wtype", "--", content], capture_output=True, timeout=10.0)
                    if res.returncode == 0:
                        success = True
                        logger.info("📥 Вставлено через прямую печать wtype")
                except Exception as e:
                    logger.debug(f"wtype печать не удалась: {e}")

            if not success:
                success = self._run_ydotool("type", "-d", "5", "--", content)
                if success:
                    logger.info("📥 Вставлено через ydotool type")

        if success:
            if and_send:
                time.sleep(0.3)
                self.press_enter(speak=False)
                if self.tts:
                    self.tts.speak("Вставлено и отправлено")
            else:
                if self.tts:
                    self.tts.speak("Вставлено")
        else:
            logger.error("Не удалось вставить текст ни одним из способов")
            if self.tts:
                self.tts.speak("Ошибка вставки")

    def type_text(self, text: str, and_send: bool = False) -> None:
        if not text:
            logger.warning("Попытка ввода пустого текста.")
            return

        action_suffix = " \033[93m[с отправкой Enter]\033[0m" if and_send else ""
        logger.info(f"⌨️  Печать текста: «\033[1m{text}\033[0m»{action_suffix}")

        self.activate_antigravity_window()
        time.sleep(0.2)

        success = False
        if shutil.which("wtype"):
            try:
                result = subprocess.run(
                    ["wtype", "--", text],
                    capture_output=True, text=True, timeout=10.0,
                )
                if result.returncode == 0:
                    success = True
                    logger.debug(f"wtype напечатал текст: {text[:40]}")
                else:
                    logger.error(f"wtype вернул ошибку: {result.stderr.strip()}")
            except Exception as e:
                logger.error(f"Ошибка wtype: {e}")

        if not success:
            logger.warning("Попытка ввода через ydotool type (fallback)")
            success = self._run_ydotool("type", "-d", "5", "--", text)

        if success:
            if and_send:
                time.sleep(0.05)
                self.press_enter(speak=False)
                if self.tts:
                    self.tts.speak("Написано и отправлено")
            else:
                if self.tts:
                    self.tts.speak("Написано")


def parse_key_tokens(words: List[str]) -> Tuple[List[int], List[str], int]:
    clean_words = [w for w in words if w not in FILLER_WORDS]
    codes: List[int] = []
    names: List[str] = []
    i = 0
    n = len(clean_words)
    consumed = 0

    while i < n:
        if i + 1 < n:
            pair = (clean_words[i], clean_words[i + 1])
            if pair in MULTI_WORD_KEY_MAP:
                code, name = MULTI_WORD_KEY_MAP[pair]
                codes.append(code)
                names.append(name)
                i += 2
                consumed += 2
                continue

        word = clean_words[i]
        if word in SINGLE_WORD_KEY_MAP:
            code, name = SINGLE_WORD_KEY_MAP[word]
            codes.append(code)
            names.append(name)
            i += 1
            consumed += 1
            continue

        i += 1

    return codes, names, consumed


def parse_voice_command(phrase: str) -> Tuple[str, ...]:
    clean = phrase.strip().lower()
    if not clean:
        return ("IGNORE",)

    if clean in ["стоп", "выход", "завершить", "завершить работу", "закройся", "exit", "quit"]:
        return ("STOP",)

    if clean in ["справка", "справку", "помощь", "команды", "покажи команды", "покажи справку", "help"]:
        return ("HELP",)

    if clean in ["статистика", "статистику", "статы", "покажи статистику", "показать статистику", "выведи статистику", "stats", "status"]:
        return ("STATS",)

    if clean in ["история", "историю", "покажи историю", "показать историю", "выведи историю", "история команд", "лог", "history"]:
        return ("HISTORY",)

    if clean in ["смени голос", "поменяй голос", "переключи голос", "сменить голос", "поменять голос", "переключить голос", "другой голос"]:
        return ("VOICE_CHANGE",)

    if any(clean.startswith(p) for p in ["вставь", "вставить", "вставка"]):
        if any(s in clean for s in ["отправ", "пошли", "запусти", "выполни"]):
            return ("PASTE_AND_SEND",)
        return ("PASTE",)

    if any(clean == p or clean.startswith(p + " ") for p in ["отправь", "отправить", "выполни", "выполнить", "пошли", "послать"]):
        return ("SEND",)

    TYPE_TRIGGERS = [
        "напиши ", "напишите ", "на пиши ", "на пишите ",
        "напечатай ", "напечатайте ", "на печатай ",
        "введи ", "введите ", "в веди ",
        "набери ", "наберите ",
    ]
    SEND_SUFFIXES = [
        " и отправь", " и отправить", " и отправьте",
        " отправить", " отправь", " отправьте",
        " и пошли", " и послать",
        " и запусти", " и выполни",
    ]

    for prefix in TYPE_TRIGGERS:
        if prefix in clean:
            idx = clean.find(prefix)
            body = clean[idx + len(prefix):].strip().lstrip(" ,:;-")
            if not body:
                continue
            if body.startswith("пожалуйста "):
                body = body[len("пожалуйста "):].strip()
            send = False
            for suffix in SEND_SUFFIXES:
                if body.endswith(suffix):
                    body = body[:-len(suffix)].strip()
                    send = True
                    break
            if body:
                if send:
                    return ("TYPE_AND_SEND", body)
                else:
                    return ("TYPE", body)
            break

    for prefix in ["нажми ", "нажать ", "жми ", "кликни ", "нажмите "]:
        if clean.startswith(prefix):
            body = clean[len(prefix):].strip()
            codes, names, _ = parse_key_tokens(body.split())
            if codes:
                return ("KEYS", codes, names)

    words = clean.split()
    codes, names, consumed = parse_key_tokens(words)
    meaningful_words = [w for w in words if w not in FILLER_WORDS]
    if codes and consumed > 0 and consumed == len(meaningful_words):
        return ("KEYS", codes, names)

    for verb in ["напиши", "напишите", "напечатай", "напечатайте", "введи", "введите", "набери", "наберите"]:
        if clean.startswith(verb):
            body = clean[len(verb):].strip(" ,:;-")
            if body.startswith("ка ") or body.startswith("-ка "):
                body = body.split(" ", 1)[-1].strip(" ,:;-")
            if body.startswith("пожалуйста "):
                body = body[len("пожалуйста "):].strip()
            if body:
                for suffix in SEND_SUFFIXES:
                    if body.endswith(suffix):
                        body = body[:-len(suffix)].strip()
                        return ("TYPE_AND_SEND", body)
                return ("TYPE", body)

    for verb in ["нажми", "жми", "кликни"]:
        if clean.startswith(verb):
            body = clean[len(verb):].strip(" ,:;-")
            codes, names, _ = parse_key_tokens(body.split())
            if codes:
                return ("KEYS", codes, names)

    return ("UNKNOWN", clean)


def print_help_table() -> None:
    help_text = """
=============================================================================
              СПРАВОЧНИК ГОЛОСОВЫХ КОМАНД ANTIGRAVITY (v0.3 Beta)
=============================================================================
 Категория              | Пример фразы                  | Действие
------------------------+-------------------------------+--------------------
 1. НАЖАТИЕ КЛАВИШ      | "нажми три"                   | Клавиша 3
                        | "нажми энтер"                 | Клавиша Enter
                        | "нажми один два три"          | Цифры 1, затем 2, затем 3
                        | "нажми стрелка вверх"         | Стрелка вверх
                        | "нажми таб", "нажми пробел"   | Tab, Space
                        | "нажми эскейп", "нажми esc"   | Escape
                        | "нажми ф один" / "ф1"         | Функциональная F1
                        | "нажми бэкспейс" / "стереть"  | Backspace
                        | "нажми да" / "нажми нет"      | Клавиши Y / N
------------------------+-------------------------------+--------------------
 2. ВСТАВКА ИЗ БУФЕРА   | "вставь"                      | wl-paste + Ctrl+V
                        | "вставь и отправь"            | Вставка + Enter
------------------------+-------------------------------+--------------------
 3. ВВОД ТЕКСТА         | "напиши git status"           | wtype / ydotool type
                        | "напиши cargo test и отправь" | ввод текста + Enter
------------------------+-------------------------------+--------------------
 4. ОТПРАВКА            | "отправь"                     | Клавиша Enter
------------------------+-------------------------------+--------------------
 5. СИСТЕМА И НАСТРОЙКИ | "справка" / "помощь"          | Показать эту таблицу
                        | "статистика"                  | Статистика сессии
                        | "история"                     | Последние 10 команд
                        | "смени голос"                 | Переключить голос (М/Ж)
                        | "стоп" / "выход"              | Завершить работу
=============================================================================
 ⚡ Управление: по умолчанию команды активны при удержании клавиши F9.
    Флаг --always-on включает постоянное прослушивание без F9.
=============================================================================
"""
    print(help_text)


def main():
    parser = argparse.ArgumentParser(
        description="Голосовое управление терминалом Antigravity через Vosk и ydotool"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.path.expanduser("~/vosk-models/vosk-model-small-ru-0.22"),
        help="Путь к оффлайн-модели Vosk (по умолчанию: ~/vosk-models/vosk-model-small-ru-0.22)"
    )
    parser.add_argument(
        "--socket",
        type=str,
        default="/run/ydotoold.socket",
        help="Путь к сокету ydotoold (по умолчанию: /run/ydotoold.socket)"
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Отключить голосовые подтверждения синтезатора речи"
    )
    parser.add_argument(
        "--voice",
        type=str,
        default="ru_female",
        choices=["ru_female", "ru_male", "female", "male", "irina", "pavel"],
        help="Голос синтезатора речи Festival: ru_female (по умолчанию) или ru_male"
    )
    parser.add_argument(
        "--always-on",
        action="store_true",
        help="Режим постоянного слушания (не требовать удержания клавиши F9)"
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Индекс входного аудиоустройства (по умолчанию: системный микрофон)"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(" 🚀 Antigravity Voice Controller v0.3 (Beta)")
    print("=" * 60)
    print(" 🌐 Wayland / Hyprland / CachyOS")
    print(" 🎤 Vosk + 🔊 Festival + ⌨️  wtype / ydotool")
    print(" ⚡ Push-to-Talk: " + ("ВЫКЛЮЧЕН (--always-on)" if args.always_on else "Клавиша F9"))
    print("=" * 60)

    try:
        import sounddevice as sd
    except ImportError:
        logger.critical("Модуль sounddevice не установлен! Установите: pip install sounddevice")
        sys.exit(1)

    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
    except ImportError:
        logger.critical("Модуль vosk не установлен! Установите: pip install vosk")
        sys.exit(1)

    model_path = Path(args.model).resolve()
    if not model_path.exists():
        logger.critical(f"Модель Vosk не найдена по пути: {model_path}")
        logger.critical("\nИнструкция по загрузке модели:")
        logger.critical("  mkdir -p ~/vosk-models")
        logger.critical("  cd ~/vosk-models")
        logger.critical("  wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip")
        logger.critical("  unzip vosk-model-small-ru-0.22.zip\n")
        sys.exit(1)

    logger.info(f"🧠 Загрузка оффлайн-модели Vosk: {model_path} ...")
    try:
        vosk_model = Model(str(model_path))
    except Exception as e:
        logger.critical(f"Ошибка загрузки модели Vosk: {e}")
        sys.exit(1)

    stats = SessionStats()
    history = CommandHistory()
    hotkey_mgr = HotkeyManager(key="f9", always_on=args.always_on)
    tts = VoiceSynthesizer(enabled=not args.no_tts, voice=args.voice)
    controller = AntigravityController(socket_path=args.socket, tts=tts)

    print_help_table()
    logger.info("🎙️ Инициализация аудиопотока микрофона (16 кГц, моно)...")

    audio_queue: queue.Queue[bytes] = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        if status:
            logger.debug(f"Статус звукового потока: {status}")
        audio_queue.put(bytes(indata))

    is_running = threading.Event()
    is_running.set()

    def handle_sigint(signum, frame):
        logger.info("\n🛑 Получен сигнал прерывания...")
        is_running.clear()

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    samplerate = 16000
    recognizer = KaldiRecognizer(vosk_model, samplerate)

    tts.speak("Голосовое управление готово к работе")
    logger.info("🟢 ГОТОВ К РАБОТЕ. Произнесите команду...\n")

    try:
        with sd.RawInputStream(
            samplerate=samplerate,
            blocksize=8000,
            device=args.device,
            dtype="int16",
            channels=1,
            callback=audio_callback
        ):
            while is_running.is_set():
                hotkey_mgr.poll()

                try:
                    data = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                try:
                    accepted = recognizer.AcceptWaveform(data)
                except Exception as e:
                    logger.debug(f"Ошибка AcceptWaveform: {e}")
                    continue

                if accepted:
                    try:
                        res_json = json.loads(recognizer.Result())
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.debug(f"Не удалось распарсить JSON Vosk: {e}")
                        continue

                    phrase = res_json.get("text", "").strip()
                    if not phrase:
                        continue

                    stats.record_recognized()

                    if not hotkey_mgr.is_active():
                        logger.debug(f"🔇 [F9 не нажата, пропуск]: «{phrase}»")
                        continue

                    logger.info(f"🗣️  Распознано: «\033[96m{phrase}\033[0m»")

                    cmd_data = parse_voice_command(phrase)
                    cmd_type = cmd_data[0]
                    history.log(phrase, cmd_type)

                    if cmd_type == "PASTE_AND_SEND":
                        controller.paste_from_clipboard(and_send=True)
                        stats.record_command()

                    elif cmd_type == "PASTE":
                        controller.paste_from_clipboard(and_send=False)
                        stats.record_command()

                    elif cmd_type == "SEND":
                        controller.press_enter(speak=True)
                        stats.record_command()

                    elif cmd_type == "TYPE_AND_SEND":
                        text_to_type = cmd_data[1]
                        controller.type_text(text_to_type, and_send=True)
                        stats.record_command()

                    elif cmd_type == "TYPE":
                        text_to_type = cmd_data[1]
                        controller.type_text(text_to_type, and_send=False)
                        stats.record_command()

                    elif cmd_type == "KEYS":
                        codes = cmd_data[1]
                        names = cmd_data[2]
                        controller.press_keys(codes, names)
                        stats.record_command()

                    elif cmd_type == "STATS":
                        stats.record_command()
                        print(stats.get_summary())
                        tts.speak(f"Выполнено {stats.stats['commands']} команд")

                    elif cmd_type == "HISTORY":
                        recent_logs = history.get_recent(10)
                        print("\n" + "=" * 55)
                        print(" 📝 ПОСЛЕДНИЕ 10 КОМАНД (ИСТОРИЯ)")
                        print("=" * 55)
                        if recent_logs:
                            for idx, item in enumerate(recent_logs, 1):
                                print(f" {idx:2d}. {item}")
                        else:
                            print(" (История пока пуста)")
                        print("=" * 55 + "\n")
                        tts.speak("Показываю историю")
                        stats.record_command()

                    elif cmd_type == "VOICE_CHANGE":
                        new_voice = tts.toggle_voice()
                        stats.record_command()

                    elif cmd_type == "HELP":
                        print_help_table()
                        tts.speak("Вывожу справку")
                        stats.record_command()

                    elif cmd_type == "STOP":
                        logger.info("Завершение работы по голосовой команде.")
                        stats.record_command()
                        tts.speak("Завершение работы")
                        time.sleep(0.5)
                        is_running.clear()
                        break

                    elif cmd_type == "UNKNOWN":
                        stats.record_error()
                        logger.warning(f"Команда не распознана: «{phrase}». Скажите 'справка' для списка команд.")

    except Exception as e:
        logger.critical(f"Критическая ошибка захвата звука: {e}")
    finally:
        print(stats.get_summary())
        logger.info("👋 Остановка синтезатора речи и освобождение ресурсов...")
        tts.stop()
        logger.info("✅ Приложение успешно завершило работу.")


if __name__ == "__main__":
    main()
