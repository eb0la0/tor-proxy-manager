"""
Lightweight translation module.

Usage:
    from core.i18n import tr, load_language, current_language

    load_language("ru")       # load at startup from config
    label = tr("btn.connect") # "Подключить"
    msg   = tr("msg.copied", text="127.0.0.1:9051")
"""
import json
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_lang: str = "ru"
_strings: dict[str, str] = {}


def _translations_dir() -> Path:
    """
    Resolves the translations/ directory for both script and PyInstaller frozen modes.
    Frozen onefile: sys._MEIPASS/translations/  (temp extraction dir)
    Script:         <project_root>/translations/
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "translations"
    return Path(__file__).parent.parent / "translations"


def load_language(lang: str) -> None:
    """
    Load translation strings for the given language code ("ru" | "en").
    Falls back to the other language if the requested file is missing,
    then falls back to returning the raw key.
    """
    global _lang, _strings

    lang = lang.lower().strip()
    path = _translations_dir() / f"{lang}.json"

    if not path.exists():
        logger.warning(f"Translation file not found: {path}")
        # Try fallback language
        fallback = "ru" if lang != "ru" else "en"
        path = _translations_dir() / f"{fallback}.json"
        if not path.exists():
            logger.error("No translation files found — will return raw keys")
            _lang = lang
            _strings = {}
            return
        lang = fallback

    try:
        _strings = json.loads(path.read_text(encoding="utf-8"))
        _lang = lang
        logger.info(f"Language loaded: {lang} ({len(_strings)} strings)")
    except Exception as e:
        logger.error(f"Failed to load translations from {path}: {e}")
        _strings = {}


def tr(key: str, **kwargs) -> str:
    """
    Return the translated string for `key`.
    Supports named placeholders:
        tr("msg.copied", text="127.0.0.1:9051")  →  "Скопировано: 127.0.0.1:9051"
    Falls back to the raw key if translation is missing.
    """
    text = _strings.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


def current_language() -> str:
    """Returns the currently loaded language code."""
    return _lang


SUPPORTED_LANGUAGES: dict[str, str] = {
    "ru": "Русский",
    "en": "English",
}
