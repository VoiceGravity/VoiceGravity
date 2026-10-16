#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
Голосовой контроллер Antigravity 2.0 для Windows 10/11
=============================================================================
Архитектура:
  - Распознавание речи: Vosk (оффлайн, русская модель vosk-model-small-ru-0.22)
  - Захват звука: sounddevice (16 кГц, моно, 16-бит PCM)
  - Синтез речи: pyttsx3 через Windows SAPI5 (Microsoft Irina / Pavel)
  - Эмуляция клавиатуры и текста: keyboard (поддерживает ввод кириллицы)
  - Буфер обмена: pyperclip
  - Управление окнами и фокусом: pygetwindow + pywin32 (fallback)

Установка зависимостей в Windows:
  pip install vosk sounddevice pyttsx3 pyperclip keyboard pygetwindow pywin32

Загрузка русской модели Vosk:
  1. Скачать: https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
  2. Распаковать в каталог: C:\\vosk-models\\vosk-model-small-ru-0.22

Запуск:
  python antigravity_control_windows.py
=============================================================================
"""

import os
import sys
import json
import time
import queue
import signal
import logging
import argparse
import threading
from pathlib import Path
from typing import Tuple, List, Optional

# ---------------------------------------------------------------------------
# 1. Цветное форматирование логов в консоли Windows
# ---------------------------------------------------------------------------
class CustomFormatter(logging.Formatter):
    """Форматтер консоли с эмодзи и цветами ANSI."""
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

logger = logging.getLogger("AntigravityVoiceWin")
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(CustomFormatter())
logger.addHandler(console_handler)

# Включение поддержки ANSI-последовательностей в командной строке Windows
if sys.platform == "win32":
    os.system("")

# ---------------------------------------------------------------------------
# 2. Маппинг клавиш для библиотеки keyboard
# ---------------------------------------------------------------------------
# Двухсловные фразы клавиш
MULTI_WORD_KEY_MAP = {
    ("стрелка", "вверх"):   ("up", "Стрелка вверх"),
    ("стрелку", "вверх"):   ("up", "Стрелка вверх"),
    ("стрелка", "вниз"):    ("down", "Стрелка вниз"),
    ("стрелку", "вниз"):    ("down", "Стрелка вниз"),
    ("стрелка", "влево"):   ("left", "Стрелка влево"),
    ("стрелку", "влево"):   ("left", "Стрелка влево"),
    ("стрелка", "вправо"):  ("right", "Стрелка вправо"),
    ("стрелку", "вправо"):  ("right", "Стрелка вправо"),
    ("ф", "один"):          ("f1", "F1"),
    ("эф", "один"):         ("f1", "F1"),
    ("f", "один"):          ("f1", "F1"),
    ("ф", "два"):           ("f2", "F2"),
    ("эф", "два"):          ("f2", "F2"),
    ("f", "два"):           ("f2", "F2"),
    ("ф", "три"):           ("f3", "F3"),
    ("эф", "три"):          ("f3", "F3"),
    ("f", "три"):           ("f3", "F3"),
    ("ф", "четыре"):        ("f4", "F4"),
    ("эф", "четыре"):       ("f4", "F4"),
    ("f", "четыре"):        ("f4", "F4"),
    ("ф", "пять"):          ("f5", "F5"),
    ("эф", "пять"):         ("f5", "F5"),
    ("f", "пять"):          ("f5", "F5"),
}

# Однословные клавиши и их синонимы
SINGLE_WORD_KEY_MAP = {
    # Цифры 0-9
    "ноль":      ("0", "0"),
    "0":         ("0", "0"),
    "один":      ("1", "1"),
    "раз":       ("1", "1"),
    "единица":   ("1", "1"),
    "1":         ("1", "1"),
    "два":       ("2", "2"),
    "двойка":    ("2", "2"),
    "2":         ("2", "2"),
    "три":       ("3", "3"),
    "тройка":    ("3", "3"),
    "3":         ("3", "3"),
    "четыре":    ("4", "4"),
    "четверка":  ("4", "4"),
    "четвёрка":  ("4", "4"),
    "4":         ("4", "4"),
    "пять":      ("5", "5"),
    "пятерка":   ("5", "5"),
    "пятёрка":   ("5", "5"),
    "5":         ("5", "5"),
    "шесть":     ("6", "6"),
    "шестерка":  ("6", "6"),
    "шестёрка":  ("6", "6"),
    "6":         ("6", "6"),
    "семь":      ("7", "7"),
    "семерка":   ("7", "7"),
    "семёрка":   ("7", "7"),
    "7":         ("7", "7"),
    "восемь":    ("8", "8"),
    "восьмерка": ("8", "8"),
    "восьмёрка": ("8", "8"),
    "8":         ("8", "8"),
    "девять":    ("9", "9"),
    "девятка":   ("9", "9"),
    "9":         ("9", "9"),

    # Enter (Ввод)
    "энтер":     ("enter", "Enter"),
    "ентер":     ("enter", "Enter"),
    "ввод":      ("enter", "Enter"),
    "enter":     ("enter", "Enter"),

    # Space (Пробел)
    "пробел":    ("space", "Space"),
    "спейс":     ("space", "Space"),
    "space":     ("space", "Space"),

    # Escape (Отмена)
    "эскейп":    ("esc", "Esc"),
    "ескейп":    ("esc", "Esc"),
    "эскейпт":   ("esc", "Esc"),
    "ескейпт":   ("esc", "Esc"),
    "искейп":    ("esc", "Esc"),
    "отмена":    ("esc", "Esc"),
    "esc":       ("esc", "Esc"),

    # Tab (Табуляция)
    "таб":       ("tab", "Tab"),
    "табуляция": ("tab", "Tab"),
    "tab":       ("tab", "Tab"),

    # Backspace (Стирание)
    "бэкспейс":  ("backspace", "Backspace"),
    "бекспейс":  ("backspace", "Backspace"),
    "стереть":   ("backspace", "Backspace"),
    "стирание":  ("backspace", "Backspace"),
    "удалить":   ("backspace", "Backspace"),
    "удаление":  ("backspace", "Backspace"),
    "backspace": ("backspace", "Backspace"),

    # Стрелки одиночными словами
    "вверх":     ("up", "Стрелка вверх"),
    "вниз":      ("down", "Стрелка вниз"),
    "влево":     ("left", "Стрелка влево"),
    "вправо":    ("right", "Стрелка вправо"),

    # F1 - F5
    "f1":        ("f1", "F1"),
    "ф1":        ("f1", "F1"),
    "f2":        ("f2", "F2"),
    "ф2":        ("f2", "F2"),
    "f3":        ("f3", "F3"),
    "ф3":        ("f3", "F3"),
    "f4":        ("f4", "F4"),
    "ф4":        ("f4", "F4"),
    "f5":        ("f5", "F5"),
    "ф5":        ("f5", "F5"),

    # Y / N (Да / Нет)
    "игрек":     ("y", "Y"),
    "вай":       ("y", "Y"),
    "y":         ("y", "Y"),
    "да":        ("y", "Y"),
    "эн":        ("n", "N"),
    "n":         ("n", "N"),
    "нет":       ("n", "N"),
}

FILLER_WORDS = {
    "клавиша", "клавиши", "клавишу",
    "кнопка", "кнопки", "кнопку",
    "цифра", "цифру", "цифры",
    "буква", "букву", "буквы",
    "и", "затем", "потом", "далее", "пожалуйста",
    "на", "мне", "же"
}

# ---------------------------------------------------------------------------
# 3. Синтез речи через pyttsx3 (SAPI5 на Windows) в отдельном потоке
# ---------------------------------------------------------------------------
class VoiceSynthesizer:
    """
    Асинхронный синтезатор речи на базе pyttsx3 (SAPI5).
    Инициализация и вызовы say/runAndWait происходят строго в выделенном
    потоке-демоне, чтобы не блокировать распознавание речи микрофона.
    """
    def __init__(self, speed: int = 200, enabled: bool = True):
        self.enabled = enabled
        self.speed = speed
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="TTS-Worker")
        self._engine = None

        if self.enabled:
            self._thread.start()

    def _worker(self):
        """Рабочий поток SAPI5 TTS с корректной инициализацией COM."""
        # На Windows в отдельных потоках требуется явная инициализация COM
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.ole32.CoInitialize(None)
            except Exception as e:
                logger.debug(f"CoInitialize warning: {e}")

        try:
            import pyttsx3
            # Инициализация SAPI5 внутри рабочего потока
            self._engine = pyttsx3.init("sapi5")
            self._engine.setProperty("rate", self.speed)

            # Выбор русского голоса (Microsoft Irina, Pavel или любой русский)
            voices = self._engine.getProperty("voices")
            russian_voice_found = False
            for voice in voices:
                v_name = voice.name.lower()
                v_id = voice.id.lower()
                if any(tag in v_name or tag in v_id for tag in ["irina", "pavel", "russian", "ru-ru", "ru"]):
                    self._engine.setProperty("voice", voice.id)
                    russian_voice_found = True
                    logger.info(f"🎙️ Выбран голос TTS: {voice.name}")
                    break

            if not russian_voice_found:
                logger.debug("Русский голос SAPI5 не найден, используется стандартный голос Windows.")
        except Exception as e:
            logger.warning(f"Ошибка инициализации pyttsx3 SAPI5: {e}. TTS отключён.")
            self._engine = None

        try:
            while True:
                text = self._queue.get()
                if text is None:
                    break
                if self._engine and text:
                    try:
                        self._engine.say(text)
                        self._engine.runAndWait()
                    except Exception as e:
                        logger.debug(f"Ошибка воспроизведения речи: {e}")
                self._queue.task_done()
        finally:
            if sys.platform == "win32":
                try:
                    import ctypes
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass

    def speak(self, text: str) -> None:
        """Помещает фразу в очередь озвучивания (не блокирует вызов)."""
        if self.enabled and text:
            self._queue.put(text)

    def stop(self) -> None:
        """Останавливает рабочий поток TTS."""
        if self.enabled and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout=1.0)


# ---------------------------------------------------------------------------
# 4. Контроллер ввода и управления окнами для Windows
# ---------------------------------------------------------------------------
class AntigravityController:
    """Управляет окном Antigravity 2.0 и эмуляцией ввода в Windows."""
    def __init__(self, tts: Optional[VoiceSynthesizer] = None):
        self.tts = tts
        self._check_modules()

    def _check_modules(self) -> None:
        """Проверяет наличие необходимых Windows-библиотек."""
        missing = []
        for mod in ["keyboard", "pyperclip"]:
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)

        if missing:
            logger.critical(f"Не установлены обязательные модули: {', '.join(missing)}!")
            logger.critical(f"Выполните: pip install {' '.join(missing)}")
            sys.exit(1)

        try:
            __import__("pygetwindow")
        except ImportError:
            logger.warning("Модуль 'pygetwindow' не установлен (будет использоваться win32gui fallback).")
            logger.warning("Для лучшей работы установите: pip install pygetwindow pywin32")

    def activate_antigravity_window(self) -> bool:
        """
        Переключает фокус на окно Antigravity 2.0.
        Использует pygetwindow с надёжным fallback через win32gui.
        """
        # Способ 1: pygetwindow
        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle("Antigravity")
            if windows:
                win = windows[0]
                if win.isMinimized:
                    win.restore()
                win.activate()
                logger.debug("Фокус переключён на окно Antigravity (pygetwindow)")
                return True
        except Exception as e:
            logger.debug(f"pygetwindow не смог активировать окно: {e}")

        # Способ 2: win32gui fallback (если установлен pywin32)
        try:
            import win32gui
            import win32con

            matched_hwnds = []

            def enum_handler(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if "antigravity" in title.lower():
                        matched_hwnds.append(hwnd)
                return True

            win32gui.EnumWindows(enum_handler, None)
            if matched_hwnds:
                hwnd = matched_hwnds[0]
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception as e:
                    logger.debug(f"SetForegroundWindow warning: {e}")
                logger.debug("Фокус переключён на окно Antigravity (win32gui)")
                return True
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"win32gui fallback не сработал: {e}")

        logger.debug("Окно 'Antigravity' не найдено. Команда отправляется в текущее активное окно.")
        return False

    def press_keys(self, key_codes: List[str], key_names: List[str]) -> None:
        """Нажимает последовательность клавиш через keyboard.press_and_release."""
        if not key_codes:
            return

        import keyboard

        self.activate_antigravity_window()
        time.sleep(0.15)

        display_names = ", ".join(key_names)
        logger.info(f"🔘 Нажатие клавиш: \033[1m{display_names}\033[0m")

        try:
            for key in key_codes:
                keyboard.press_and_release(key)
                time.sleep(0.05)

            if self.tts:
                if len(key_names) == 1:
                    self.tts.speak(key_names[0])
                else:
                    self.tts.speak("Нажато")
        except Exception as e:
            logger.error(f"Ошибка нажатия клавиш: {e}")

    def press_enter(self, speak: bool = True) -> None:
        """Нажимает Enter."""
        import keyboard

        logger.info("↵  \033[1mОтправка (Enter)\033[0m")
        self.activate_antigravity_window()
        time.sleep(0.15)

        try:
            keyboard.press_and_release("enter")
            if speak and self.tts:
                self.tts.speak("Отправлено")
        except Exception as e:
            logger.error(f"Ошибка нажатия Enter: {e}")

    def type_text(self, text: str, and_send: bool = False) -> None:
        """
        Печатает текст через keyboard.write (на Windows отлично работает с кириллицей)
        и опционально нажимает Enter.
        """
        if not text:
            logger.warning("Попытка ввода пустого текста.")
            return

        import keyboard

        action_suffix = " \033[93m[с отправкой Enter]\033[0m" if and_send else ""
        logger.info(f"⌨️  Печать текста: «\033[1m{text}\033[0m»{action_suffix}")

        self.activate_antigravity_window()
        time.sleep(0.2)

        try:
            keyboard.write(text)
            if and_send:
                time.sleep(0.1)
                self.press_enter(speak=False)
                if self.tts:
                    self.tts.speak("Написано и отправлено")
            else:
                if self.tts:
                    self.tts.speak("Написано")
        except Exception as e:
            logger.error(f"Ошибка ввода текста через keyboard.write: {e}")
            if self.tts:
                self.tts.speak("Ошибка ввода")

    def paste_from_clipboard(self, and_send: bool = False) -> None:
        """
        Считывает буфер обмена через pyperclip и вставляет в окно через Ctrl+V.
        """
        try:
            import pyperclip
            import keyboard
            content = pyperclip.paste()
        except Exception as e:
            logger.error(f"Ошибка чтения буфера обмена: {e}")
            content = ""

        if not content:
            logger.warning("📋 Буфер обмена пуст!")
            if self.tts:
                self.tts.speak("Буфер пуст")
            return

        preview = content[:35] + ("..." if len(content) > 35 else "")
        preview_clean = preview.replace("\n", " ").replace("\r", "")
        logger.info(f"📋 Вставка из буфера ({len(content)} симв.): «\033[1m{preview_clean}\033[0m»")

        self.activate_antigravity_window()
        time.sleep(0.2)

        try:
            keyboard.hotkey("ctrl", "v")
            if and_send:
                time.sleep(0.2)
                self.press_enter(speak=False)
                if self.tts:
                    self.tts.speak("Вставлено и отправлено")
            else:
                if self.tts:
                    self.tts.speak("Вставлено")
        except Exception as e:
            logger.error(f"Ошибка вставки через Ctrl+V: {e}")
            if self.tts:
                self.tts.speak("Ошибка вставки")


# ---------------------------------------------------------------------------
# 5. Парсер голосовых команд
# ---------------------------------------------------------------------------
def parse_key_tokens(words: List[str]) -> Tuple[List[str], List[str], int]:
    """
    Разбирает слова в список названий клавиш для keyboard.
    """
    clean_words = [w for w in words if w not in FILLER_WORDS]
    codes: List[str] = []
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
    """
    Классифицирует голосовую фразу в команду.
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
              СПРАВОЧНИК ГОЛОСОВЫХ КОМАНД ANTIGRAVITY (WINDOWS)
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
 2. ВСТАВКА ИЗ БУФЕРА   | "вставь"                      | pyperclip + Ctrl+V
                        | "вставь и отправь"            | Вставка + Enter
------------------------+-------------------------------+--------------------
 3. ВВОД ТЕКСТА         | "напиши создай змейку"        | keyboard.write [текст]
                        | "напиши тест и отправь"       | keyboard.write + Enter
------------------------+-------------------------------+--------------------
 4. ОТПРАВКА            | "отправь"                     | Клавиша Enter
------------------------+-------------------------------+--------------------
 5. СИСТЕМА             | "справка" / "помощь"          | Показать эту таблицу
                        | "стоп" / "выход"              | Завершить работу
=============================================================================
"""
    print(help_text)


# ---------------------------------------------------------------------------
# 7. Точка входа и главный цикл
# ---------------------------------------------------------------------------
def find_default_model_path() -> str:
    """Определяет стандартный путь к модели Vosk в Windows."""
    candidates = [
        r"C:\vosk-models\vosk-model-small-ru-0.22",
        str(Path.home() / "vosk-models" / "vosk-model-small-ru-0.22"),
        os.path.expanduser(r"~\vosk-models\vosk-model-small-ru-0.22"),
        r"vosk-model-small-ru-0.22",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return r"C:\vosk-models\vosk-model-small-ru-0.22"


def main():
    parser = argparse.ArgumentParser(
        description="Голосовое управление Antigravity 2.0 для Windows 10/11"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=find_default_model_path(),
        help="Путь к оффлайн-модели Vosk (по умолчанию: C:\\vosk-models\\vosk-model-small-ru-0.22)"
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
        help="Индекс устройства аудиоввода (по умолчанию: системный микрофон)"
    )
    args = parser.parse_args()

    # Вывод баннера Windows-версии
    print("\n" + "=" * 60)
    print(" 🚀 Antigravity 2.0 Voice Controller v0.1 (Windows Beta)")
    print("=" * 60)
    print(" 🪟 Windows 10/11")
    print(" 🎤 Vosk + 🔊 pyttsx3 (SAPI5) + ⌨️  keyboard + 📋 pyperclip")
    print("=" * 60)

    # 1. Проверка внешних библиотек
    try:
        import sounddevice as sd
    except ImportError:
        logger.critical("Модуль sounddevice не установлен! Выполните: pip install sounddevice")
        sys.exit(1)

    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
    except ImportError:
        logger.critical("Модуль vosk не установлен! Выполните: pip install vosk")
        sys.exit(1)

    # 2. Проверка модели Vosk
    model_path = Path(args.model).resolve()
    if not model_path.exists():
        logger.critical(f"Модель Vosk не найдена по пути: {model_path}")
        logger.critical("\nИнструкция по установке модели на Windows:")
        logger.critical("  1. Скачайте архив:")
        logger.critical("     https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip")
        logger.critical(r"  2. Распакуйте его в папку: C:\vosk-models\vosk-model-small-ru-0.22")
        logger.critical("  3. Либо укажите путь через флаг: python antigravity_control_windows.py --model <путь>\n")
        sys.exit(1)

    logger.info(f"🧠 Загрузка модели Vosk: {model_path} ...")
    try:
        vosk_model = Model(str(model_path))
    except Exception as e:
        logger.critical(f"Ошибка загрузки модели Vosk: {e}")
        sys.exit(1)

    # 3. Инициализация TTS и контроллера
    tts = VoiceSynthesizer(enabled=not args.no_tts)
    controller = AntigravityController(tts=tts)

    # 4. Проверка запущенного окна Antigravity 2.0
    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle("Antigravity")
        if windows:
            logger.info("🪟 Окно Antigravity 2.0 обнаружено в системе.")
        else:
            logger.warning("Окно 'Antigravity' сейчас не найдено. Запустите Antigravity 2.0.")
    except Exception:
        pass

    # 5. Справка по командам
    print_help_table()
    logger.info("🎙️ Инициализация микрофона (16 кГц, моно)...")

    audio_queue: queue.Queue[bytes] = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        """Callback захвата звука."""
        if status:
            logger.debug(f"Статус звукового потока: {status}")
        audio_queue.put(bytes(indata))

    is_running = threading.Event()
    is_running.set()

    def handle_sigint(signum, frame):
        logger.info("\n🛑 Получен сигнал завершения...")
        is_running.clear()

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    samplerate = 16000
    recognizer = KaldiRecognizer(vosk_model, samplerate)

    tts.speak("Голосовое управление Antigravity готово к работе")
    logger.info("🟢 ГОТОВ К РАБОТЕ. Говорите команды в микрофон...\n")

    # 6. Цикл прослушивания
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
                        tts.speak("Вывожу справку по командам")

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
        logger.info("👋 Остановка синтезатора речи и завершение работы...")
        tts.stop()
        logger.info("✅ Приложение успешно завершило работу.")


if __name__ == "__main__":
    main()
