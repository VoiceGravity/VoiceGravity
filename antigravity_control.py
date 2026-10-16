#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
Голосовой контроллер терминала Antigravity v0.1v (Beta) для CachyOS / Wayland
=============================================================================
Архитектура:
  - Распознавание речи: Vosk (оффлайн, модель vosk-model-small-ru-0.22)
  - Захват звука: sounddevice (16 кГц, моно, 16-бит PCM)
  - Синтез речи: Festival + voice_msu_ru_nsh_clunits (выполняется в отдельном потоке)
  - Эмуляция ввода: ydotool через сокет демона (/run/ydotoold.socket)
  - Буфер обмена Wayland: wl-clipboard (wl-paste)

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
  5. Управление приложением:
     - "справка" / "помощь"         -> вывод таблицы команд
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
from typing import Tuple, List, Optional

# ---------------------------------------------------------------------------
# 1. Настройка цветного логирования с эмодзи-статусами
# ---------------------------------------------------------------------------
class CustomFormatter(logging.Formatter):
    """Форматтер консоли с эмодзи и ANSI-цветами для наглядного статуса."""
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

# ---------------------------------------------------------------------------
# 2. Коды клавиш Linux Input Event (/usr/include/linux/input-event-codes.h)
# ---------------------------------------------------------------------------
# Стандартные скан-коды ядра Linux, используемые ydotool:
# KEY_ESC = 1, KEY_1 = 2, KEY_2 = 3, KEY_3 = 4, KEY_4 = 5 ... KEY_0 = 11
KEY_ESC       = 1
KEY_1         = 2
KEY_2         = 3
KEY_3         = 4   # Ядерный скан-код KEY_3 равен 4 (KEY_1 = 2, KEY_2 = 3)
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

# Двухсловные фразы клавиш (проверяются анализатором в первую очередь)
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

# Однословные клавиши и их русскоязычные синонимы
SINGLE_WORD_KEY_MAP = {
    # Цифры 0-9
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

    # Enter (Ввод)
    "энтер":     (KEY_ENTER, "Enter"),
    "ентер":     (KEY_ENTER, "Enter"),
    "ввод":      (KEY_ENTER, "Enter"),
    "enter":     (KEY_ENTER, "Enter"),

    # Space (Пробел)
    "пробел":    (KEY_SPACE, "Space"),
    "спейс":     (KEY_SPACE, "Space"),
    "space":     (KEY_SPACE, "Space"),

    # Escape (Отмена)
    "эскейп":    (KEY_ESC, "Esc"),
    "ескейп":    (KEY_ESC, "Esc"),
    "эскейпт":   (KEY_ESC, "Esc"),
    "ескейпт":   (KEY_ESC, "Esc"),
    "искейп":    (KEY_ESC, "Esc"),
    "отмена":    (KEY_ESC, "Esc"),
    "esc":       (KEY_ESC, "Esc"),

    # Tab (Табуляция)
    "таб":       (KEY_TAB, "Tab"),
    "табуляция": (KEY_TAB, "Tab"),
    "tab":       (KEY_TAB, "Tab"),

    # Backspace (Удаление/стирание)
    "бэкспейс":  (KEY_BACKSPACE, "Backspace"),
    "бекспейс":  (KEY_BACKSPACE, "Backspace"),
    "стереть":   (KEY_BACKSPACE, "Backspace"),
    "стирание":  (KEY_BACKSPACE, "Backspace"),
    "удалить":   (KEY_BACKSPACE, "Backspace"),
    "удаление":  (KEY_BACKSPACE, "Backspace"),
    "backspace": (KEY_BACKSPACE, "Backspace"),

    # Стрелки одиночными словами
    "вверх":     (KEY_UP, "Стрелка вверх"),
    "вниз":      (KEY_DOWN, "Стрелка вниз"),
    "влево":     (KEY_LEFT, "Стрелка влево"),
    "вправо":    (KEY_RIGHT, "Стрелка вправо"),

    # F1 - F5
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

    # Y / N (Да / Нет)
    "игрек":     (KEY_Y, "Y"),
    "вай":       (KEY_Y, "Y"),
    "y":         (KEY_Y, "Y"),
    "да":        (KEY_Y, "Y"),
    "эн":        (KEY_N, "N"),
    "n":         (KEY_N, "N"),
    "нет":       (KEY_N, "N"),
}

# Вспомогательные слова, которые игнорируются при разборе последовательностей клавиш
FILLER_WORDS = {
    "клавиша", "клавиши", "клавишу",
    "кнопка", "кнопки", "кнопку",
    "цифра", "цифру", "цифры",
    "буква", "букву", "буквы",
    "и", "затем", "потом", "далее", "пожалуйста",
    "на", "мне", "же"
}

# ---------------------------------------------------------------------------
# 3. Асинхронный синтез речи (TTS) на базе Festival в серверном режиме
# ---------------------------------------------------------------------------
class VoiceSynthesizer:
    """
    Синтезатор речи через Festival в серверном режиме.
    Сервер запускается один раз, все фразы отправляются через TCP-сокет.
    """
    def __init__(self, enabled: bool = True, port: int = 1314):
        self.enabled = enabled
        self.port = port
        self._queue = queue.Queue()
        self._server_process = None
        self._thread = None

        if not self.enabled:
            return

        # Запускаем festival --server
        if not self._start_server():
            logger.warning("Festival сервер не запущен. TTS отключён.")
            self.stop()
            self.enabled = False
            return

        # Загружаем русский голос в сервер
        if not self._load_voice():
            logger.warning("Русский голос не загружен. TTS отключён.")
            self.stop()
            self.enabled = False
            return

        # Запускаем воркер-поток
        self._thread = threading.Thread(target=self._worker, daemon=True, name="TTS-Worker")
        self._thread.start()
        logger.info("🎙️ Festival сервер запущен, русский голос загружен.")

    def _start_server(self) -> bool:
        """Запускает festival --server в фоне."""
        # Проверяем, возможно сервер уже работает на этом порту
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
            # Ждём, пока сервер стартует
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
        """Отправляет Scheme-код в Festival сервер."""
        try:
            with socket.create_connection(("localhost", self.port), timeout=5) as sock:
                sock.sendall(scheme_code.encode("utf-8") + b"\n")
                # Ждём ответа (festival присылает "nil" после выполнения)
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
        """Загружает русский голос в сервер."""
        return self._send_scheme('(voice_msu_ru_nsh_clunits)')

    def _worker(self):
        """Рабочий цикл: берёт фразы из очереди и отправляет в сервер."""
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
        """Добавляет фразу в очередь озвучки (не блокирует)."""
        if self.enabled and text:
            self._queue.put(text)

    def stop(self) -> None:
        """Останавливает поток синтеза речи и завершает процесс сервера."""
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout=1.0)
        # Завершаем сервер
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


# ---------------------------------------------------------------------------
# 4. Контроллер эмуляции ввода (ydotool / wtype) и буфера обмена (wl-clipboard)
# ---------------------------------------------------------------------------
class AntigravityController:
    """Управляет эмуляцией ввода через wtype / ydotool и буфером обмена Wayland."""
    def __init__(self, socket_path: str = "/run/ydotoold.socket", tts: Optional[VoiceSynthesizer] = None):
        self.socket_path = socket_path
        self.tts = tts
        # Передаём сокет через переменную окружения без необходимости в sudo
        self._env = os.environ.copy()
        self._env["YDOTOOL_SOCKET"] = self.socket_path

        self._check_prerequisites()

    def _check_prerequisites(self) -> None:
        """Проверяет доступность бинарников ydotool, wtype, wl-paste и сокета демона."""
        # Проверка ydotool
        if not shutil.which("ydotool"):
            logger.critical("Утилита ydotool не найдена в PATH!")
            logger.critical("Установите её командой: sudo pacman -S ydotool")
            sys.exit(1)

        # Проверка сокета ydotoold
        if not os.path.exists(self.socket_path):
            logger.warning(f"Сокет демона {self.socket_path} не обнаружен.")
            logger.warning("Убедитесь, что служба запущена: sudo systemctl start ydotoold.service")
        else:
            logger.info(f"🔌 Сокет ydotool подключен: {self.socket_path}")

        # Проверка wl-clipboard
        if not shutil.which("wl-paste"):
            logger.warning("Утилита wl-paste не найдена. Установите: sudo pacman -S wl-clipboard")

        # Проверка wtype (критично для кириллицы в Wayland)
        if not shutil.which("wtype"):
            logger.warning("Утилита wtype не найдена. Для корректного ввода кириллицы установите: sudo pacman -S wtype")

    def activate_antigravity_window(self) -> bool:
        """
        Переключает фокус на окно Antigravity через hyprctl (Hyprland).
        Окно определяется по классу: "class:antigravity".
        """
        if not shutil.which("hyprctl"):
            return False

        try:
            result = subprocess.run(
                ["hyprctl", "dispatch",
                 'hl.dsp.focus({ window = "class:antigravity" })'],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if "ok" in result.stdout.lower():
                logger.debug("Фокус переключён на окно Antigravity (hl.dsp.focus)")
                return True

            # Запасной вариант стандартного диспетчера Hyprland
            fallback = subprocess.run(
                ["hyprctl", "dispatch", "focuswindow", "class:antigravity"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if "ok" in fallback.stdout.lower():
                logger.debug("Фокус переключён на окно Antigravity (focuswindow)")
                return True

            logger.warning(f"Не удалось активировать окно: "
                           f"{result.stdout.strip()} {result.stderr.strip()}")
            return False
        except Exception as e:
            logger.warning(f"Ошибка активации окна: {e}")
            return False

    def _run_ydotool(self, *args: str) -> bool:
        """Вызывает утилиту ydotool через subprocess с настроенным сокетом."""
        cmd = ["ydotool", *args]
        try:
            res = subprocess.run(
                cmd,
                env=self._env,
                capture_output=True,
                text=True,
                timeout=5.0
            )
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip()
                logger.error(f"ydotool вернул код ошибки {res.returncode}: {err_msg}")
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error("Таймаут выполнения команды ydotool.")
            return False
        except Exception as e:
            logger.error(f"Исключение при вызове ydotool: {e}")
            return False

    def press_keys(self, keycodes: List[int], key_names: List[str]) -> None:
        """
        Нажимает последовательность клавиш по их Linux keycode.
        Для каждой клавиши формируется пара <code:1> (нажатие) и <code:0> (отпускание).
        """
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
        """Эмулирует нажатие клавиши Enter (KEY_ENTER = 28)."""
        logger.info("↵  \033[1mОтправка (Enter)\033[0m")
        self.activate_antigravity_window()
        time.sleep(0.2)
        success = self._run_ydotool("key", f"{KEY_ENTER}:1", f"{KEY_ENTER}:0")
        if success and speak and self.tts:
            self.tts.speak("Отправлено")

    def read_clipboard(self) -> str:
        """Считывает текстовое содержимое буфера обмена Wayland через wl-paste."""
        try:
            res = subprocess.run(
                ["wl-paste", "--no-newline"],
                capture_output=True,
                text=True,
                timeout=2.0
            )
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
        """
        Вставляет содержимое буфера обмена в активное окно Antigravity 2.0 (Ctrl+V).
        Использует wtype (Wayland-native), если доступен, иначе fallback на ydotool.
        """
        content = self.read_clipboard()
        if not content:
            logger.warning("📋 Буфер обмена пуст!")
            if self.tts:
                self.tts.speak("Буфер пуст")
            return

        preview = content[:35] + ("..." if len(content) > 35 else "")
        preview_clean = preview.replace("\n", " ")
        logger.info(f"📋 Вставка из буфера ({len(content)} симв.): «\033[1m{preview_clean}\033[0m»")

        # Активируем окно Antigravity
        self.activate_antigravity_window()
        time.sleep(0.3)

        success = False
        # Способ 1: wtype Ctrl+V (основной надёжный метод для Electron GUI)
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

        # Способ 2: ydotool Ctrl+V (fallback)
        if not success:
            # 29 = KEY_LEFTCTRL, 47 = KEY_V
            success = self._run_ydotool("key", "29:1", "47:1", "47:0", "29:0")
            if success:
                logger.info("📥 Вставлено через ydotool (Ctrl+V)")

        # Способ 3: Прямая печать содержимого буфера
        if not success:
            if shutil.which("wtype"):
                logger.warning("Ctrl+V не сработал, печатаю содержимое через wtype")
                try:
                    res = subprocess.run(["wtype", "--", content], capture_output=True, timeout=10.0)
                    if res.returncode == 0:
                        success = True
                        logger.info("📥 Вставлено через прямую печать wtype")
                except Exception as e:
                    logger.debug(f"wtype печать не удалась: {e}")

            if not success:
                logger.warning("Печатаю содержимое через ydotool type")
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
        """
        Печатает распознанный текст через wtype (с поддержкой кириллицы)
        с fallback на ydotool type и опционально нажимает Enter.
        """
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

        # Fallback на ydotool type, если wtype отсутствует или дал сбой
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


# ---------------------------------------------------------------------------
# 5. Парсер голосовых команд и соответствий
# ---------------------------------------------------------------------------
def parse_key_tokens(words: List[str]) -> Tuple[List[int], List[str], int]:
    """
    Разбирает список слов на последовательность клавиш.
    Обрабатывает как сложные фразы ('стрелка вверх', 'ф один'),
    так и простые слова ('один', 'два', 'три', 'энтер', 'пробел').
    Возвращает:
      - Список числовых кодов клавиш Linux
      - Список названий клавиш для вывода и озвучки
      - Количество успешно сопоставленных слов
    """
    clean_words = [w for w in words if w not in FILLER_WORDS]
    codes: List[int] = []
    names: List[str] = []
    i = 0
    n = len(clean_words)
    consumed = 0

    while i < n:
        # Проверяем двухсловные сочетания
        if i + 1 < n:
            pair = (clean_words[i], clean_words[i + 1])
            if pair in MULTI_WORD_KEY_MAP:
                code, name = MULTI_WORD_KEY_MAP[pair]
                codes.append(code)
                names.append(name)
                i += 2
                consumed += 2
                continue

        # Проверяем однословные клавиши
        word = clean_words[i]
        if word in SINGLE_WORD_KEY_MAP:
            code, name = SINGLE_WORD_KEY_MAP[word]
            codes.append(code)
            names.append(name)
            i += 1
            consumed += 1
            continue

        # Неизвестное слово пропускается
        i += 1

    return codes, names, consumed


def parse_voice_command(phrase: str) -> Tuple[str, ...]:
    """
    Классифицирует голосовую фразу пользователя в конкретную команду.
    """
    clean = phrase.strip().lower()
    if not clean:
        return ("IGNORE",)

    # 1. Завершение работы
    if clean in ["стоп", "выход", "завершить", "завершить работу", "закройся", "exit", "quit"]:
        return ("STOP",)

    # 2. Вызов интерактивной справки
    if clean in ["справка", "помощь", "команды", "help"]:
        return ("HELP",)

    # 3. Вставка из буфера (с отправкой или без)
    if any(clean.startswith(p) for p in ["вставь", "вставить", "вставка"]):
        if any(s in clean for s in ["отправ", "пошли", "запусти", "выполни"]):
            return ("PASTE_AND_SEND",)
        return ("PASTE",)

    # 4. Просто отправка ("отправь")
    if any(clean == p or clean.startswith(p + " ") for p in ["отправь", "отправить", "выполни", "выполнить", "пошли", "послать"]):
        return ("SEND",)

    # 5. Ввод текста: "напиши [текст]" или "напиши [текст] и отправь"
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

    # 6. Нажатие клавиш с префиксом ("нажми три", "нажми один два три")
    for prefix in ["нажми ", "нажать ", "жми ", "кликни ", "нажмите "]:
        if clean.startswith(prefix):
            body = clean[len(prefix):].strip()
            codes, names, _ = parse_key_tokens(body.split())
            if codes:
                return ("KEYS", codes, names)

    # 7. Прямой ввод клавиш без префикса (например: "энтер", "стрелка вверх")
    words = clean.split()
    codes, names, consumed = parse_key_tokens(words)
    meaningful_words = [w for w in words if w not in FILLER_WORDS]
    if codes and consumed > 0 and consumed == len(meaningful_words):
        return ("KEYS", codes, names)

    # 8. Запасной разбор, если фраза начинается с глагола действия
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


# ---------------------------------------------------------------------------
# 6. Справка по командам
# ---------------------------------------------------------------------------
def print_help_table() -> None:
    """Выводит подробную справочную таблицу по голосовым командам."""
    help_text = """
=============================================================================
              СПРАВОЧНИК ГОЛОСОВЫХ КОМАНД ANTIGRAVITY
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
 5. СИСТЕМА             | "справка" / "помощь"          | Показать эту таблицу
                        | "стоп" / "выход"              | Завершить работу
=============================================================================
"""
    print(help_text)


# ---------------------------------------------------------------------------
# 7. Точка входа и главный цикл прослушивания
# ---------------------------------------------------------------------------
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
        "--device",
        type=int,
        default=None,
        help="Индекс входного аудиоустройства (по умолчанию: системный микрофон)"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(" 🚀 Antigravity Voice Controller v0.1v (Beta)")
    print("=" * 60)
    print(" 🌐 Wayland / Hyprland / CachyOS")
    print(" 🎤 Vosk + 🔊 Festival + ⌨️  wtype / ydotool")
    print("=" * 60)

    # Проверка зависимостей Python
    try:
        import sounddevice as sd
    except ImportError:
        logger.critical("Модуль sounddevice не установлен! Установите: pip install sounddevice")
        sys.exit(1)

    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        # Отключаем отладочный вывод Kaldi в консоль
        SetLogLevel(-1)
    except ImportError:
        logger.critical("Модуль vosk не установлен! Установите: pip install vosk")
        sys.exit(1)

    # Проверка каталога модели Vosk
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

    # Инициализация подсистем
    tts = VoiceSynthesizer(enabled=not args.no_tts)
    controller = AntigravityController(socket_path=args.socket, tts=tts)

    # Вывод справки по командам в консоль
    print_help_table()
    logger.info("🎙️ Инициализация аудиопотока микрофона (16 кГц, моно)...")

    # Потокобезопасная очередь аудиосэмплов
    audio_queue: queue.Queue[bytes] = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        """Callback-функция sounddevice для захвата аудио в реальном времени."""
        if status:
            logger.debug(f"Статус звукового потока: {status}")
        audio_queue.put(bytes(indata))

    is_running = threading.Event()
    is_running.set()

    def handle_sigint(signum, frame):
        """Плавное завершение при нажатии Ctrl+C."""
        logger.info("\n🛑 Получен сигнал прерывания...")
        is_running.clear()

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    samplerate = 16000
    recognizer = KaldiRecognizer(vosk_model, samplerate)

    tts.speak("Голосовое управление готово к работе")
    logger.info("🟢 ГОТОВ К РАБОТЕ. Сделайте активным окно терминала Antigravity и произнесите команду...\n")

    # Главный цикл захвата звука и обработки событий
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

                    logger.info(f"🗣️  Распознано: «\033[96m{phrase}\033[0m»")

                    cmd_data = parse_voice_command(phrase)
                    cmd_type = cmd_data[0]

                    if cmd_type == "PASTE_AND_SEND":
                        controller.paste_from_clipboard(and_send=True)

                    elif cmd_type == "PASTE":
                        controller.paste_from_clipboard(and_send=False)

                    elif cmd_type == "SEND":
                        controller.press_enter(speak=True)

                    elif cmd_type == "TYPE_AND_SEND":
                        text_to_type = cmd_data[1]
                        controller.type_text(text_to_type, and_send=True)

                    elif cmd_type == "TYPE":
                        text_to_type = cmd_data[1]
                        controller.type_text(text_to_type, and_send=False)

                    elif cmd_type == "KEYS":
                        codes = cmd_data[1]
                        names = cmd_data[2]
                        controller.press_keys(codes, names)

                    elif cmd_type == "HELP":
                        print_help_table()
                        tts.speak("Вывожу справку")

                    elif cmd_type == "STOP":
                        logger.info("Завершение работы по голосовой команде.")
                        tts.speak("Завершение работы")
                        time.sleep(0.5)
                        is_running.clear()
                        break

                    elif cmd_type == "UNKNOWN":
                        logger.warning(f"Команда не распознана: «{phrase}». Скажите 'справка' для списка команд.")

    except Exception as e:
        logger.critical(f"Критическая ошибка захвата звука: {e}")
    finally:
        logger.info("👋 Остановка синтезатора речи и освобождение ресурсов...")
        tts.stop()
        logger.info("✅ Приложение успешно завершило работу.")


if __name__ == "__main__":
    main()
