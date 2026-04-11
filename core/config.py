import json
import sys
import logging
from pathlib import Path

try:
    import winreg
    _HAS_WINREG = True
except ImportError:
    _HAS_WINREG = False

logger = logging.getLogger(__name__)

# ---- Корневая папка приложения ----
# При запуске как скрипт: core/../  = папка с main.py
# При сборке PyInstaller (frozen): папка рядом с .exe
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent.parent

# Папка с бандлом Tor (кладётся рядом с main.py)
TOR_BUNDLE_DIR = APP_DIR / "tor"

CONFIG_DIR = Path.home() / ".tor_proxy_manager"
DATA_DIR = CONFIG_DIR / "data"
LOGS_DIR = CONFIG_DIR / "logs"
CONFIG_FILE = CONFIG_DIR / "config.json"
BRIDGES_FILE = CONFIG_DIR / "bridges.json"
TORRC_FILE = CONFIG_DIR / "torrc"
TOR_LOG_FILE = LOGS_DIR / "tor.log"
WATCHDOG_LOG_FILE = LOGS_DIR / "watchdog.log"
ERRORS_LOG_FILE = LOGS_DIR / "errors.log"

DEFAULT_CONFIG = {
    "tor_exe": "",
    "lyrebird_exe": "",
    "socks_port": 9050,
    "bridge_type": "obfs4",
    "max_bridges": 5,
    "test_timeout": 5,
    "auto_update_hours": 24,
    "last_bridge_update": None,
    "language": "ru",
    "proxied_apps": [],       # [{"name": "...", "path": "..."}, ...]
}

# Кандидаты для поиска tor.exe
# Порядок: бандл рядом с приложением → Tor Expert Bundle → Tor Browser
TOR_EXE_CANDIDATES = [
    # Бандл рядом с приложением (tor/tor.exe или tor.exe)
    TOR_BUNDLE_DIR / "tor.exe",
    APP_DIR / "tor.exe",
    # Tor Expert Bundle — типичные пути установки
    Path("C:/tor/tor/tor.exe"),
    Path("C:/tor/tor.exe"),
    Path("D:/tor/tor/tor.exe"),
    Path("D:/tor/tor.exe"),
    # Tor Browser
    Path.home() / "Desktop/Tor Browser/Browser/TorBrowser/Tor/tor.exe",
    Path("C:/Program Files/Tor Browser/Browser/TorBrowser/Tor/tor.exe"),
    Path("C:/Program Files (x86)/Tor Browser/Browser/TorBrowser/Tor/tor.exe"),
    Path.home() / "AppData/Local/Tor Browser/Browser/TorBrowser/Tor/tor.exe",
]

LYREBIRD_EXE_CANDIDATES = [
    # Бандл рядом с приложением
    TOR_BUNDLE_DIR / "lyrebird.exe",
    TOR_BUNDLE_DIR / "pluggable_transports" / "lyrebird.exe",
    APP_DIR / "lyrebird.exe",
    # Tor Expert Bundle — lyrebird лежит в pluggable_transports/
    Path("C:/tor/tor/pluggable_transports/lyrebird.exe"),
    Path("C:/tor/pluggable_transports/lyrebird.exe"),
    Path("D:/tor/tor/pluggable_transports/lyrebird.exe"),
    Path("D:/tor/pluggable_transports/lyrebird.exe"),
    Path("C:/tor/tor/lyrebird.exe"),
    Path("D:/tor/tor/lyrebird.exe"),
    Path("D:/tor/lyrebird.exe"),
    # Tor Browser
    Path.home() / "Desktop/Tor Browser/Browser/TorBrowser/Tor/lyrebird.exe",
    Path.home() / "Desktop/Tor Browser/Browser/TorBrowser/Tor/PluggableTransports/lyrebird.exe",
    Path("C:/Program Files/Tor Browser/Browser/TorBrowser/Tor/lyrebird.exe"),
    Path("C:/Program Files/Tor Browser/Browser/TorBrowser/Tor/PluggableTransports/lyrebird.exe"),
    Path("C:/Program Files (x86)/Tor Browser/Browser/TorBrowser/Tor/lyrebird.exe"),
    Path.home() / "AppData/Local/Tor Browser/Browser/TorBrowser/Tor/lyrebird.exe",
    Path.home() / "AppData/Local/Tor Browser/Browser/TorBrowser/Tor/PluggableTransports/lyrebird.exe",
]


def find_tor_exe() -> str:
    for c in TOR_EXE_CANDIDATES:
        if c.exists():
            return str(c)
    return ""


def find_lyrebird_exe() -> str:
    for c in LYREBIRD_EXE_CANDIDATES:
        if c.exists():
            return str(c)
    return ""


_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "TorProxyManager"


def set_windows_autostart(enable: bool) -> bool:
    """Добавляет/удаляет запись автозапуска в реестре Windows."""
    if not _HAS_WINREG:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _AUTOSTART_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
        if enable:
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ, f'"{sys.executable}"')
            logger.info(f"Автозапуск включён: {exe}")
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
                logger.info("Автозапуск отключён")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        logger.error(f"Ошибка реестра автозапуска: {e}")
        return False


def get_windows_autostart() -> bool:
    """Проверяет, включён ли автозапуск в реестре."""
    if not _HAS_WINREG:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _AUTOSTART_KEY,
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, _AUTOSTART_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False


class Config:
    def __init__(self):
        self._data = dict(DEFAULT_CONFIG)
        self._ensure_dirs()
        self.load()
        self._auto_fill_paths()

    def _ensure_dirs(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    def load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data.update(saved)
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига: {e}")

    def _auto_fill_paths(self):
        """
        Если пути не заданы — ищем автоматически.
        Приоритет: папка tor/ рядом с приложением, затем Tor Browser.
        """
        changed = False
        if not self._data["tor_exe"] or not Path(self._data["tor_exe"]).exists():
            found = find_tor_exe()
            if found:
                self._data["tor_exe"] = found
                logger.info(f"Авто-обнаружен tor.exe: {found}")
                changed = True
        if not self._data["lyrebird_exe"] or not Path(self._data["lyrebird_exe"]).exists():
            found = find_lyrebird_exe()
            if found:
                self._data["lyrebird_exe"] = found
                logger.info(f"Авто-обнаружен lyrebird.exe: {found}")
                changed = True
        if changed:
            self.save()

    def save(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка сохранения конфига: {e}")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def update(self, data: dict):
        self._data.update(data)
        self.save()

    @property
    def tor_exe(self) -> str:
        return self._data["tor_exe"]

    @property
    def lyrebird_exe(self) -> str:
        return self._data["lyrebird_exe"]

    @property
    def socks_port(self) -> int:
        return self._data["socks_port"]

    @property
    def bridge_type(self) -> str:
        return self._data["bridge_type"]

    @property
    def max_bridges(self) -> int:
        return self._data["max_bridges"]

    @property
    def test_timeout(self) -> int:
        return self._data["test_timeout"]

    @property
    def auto_update_hours(self) -> int:
        return self._data["auto_update_hours"]

    @property
    def last_bridge_update(self):
        return self._data["last_bridge_update"]

    @property
    def language(self) -> str:
        return self._data.get("language", "ru")

    @property
    def proxied_apps(self) -> list:
        return self._data.get("proxied_apps", [])
