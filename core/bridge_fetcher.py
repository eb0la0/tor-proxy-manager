import re
import urllib.request
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtCore import QThread, pyqtSignal

from core.bridge_validator import validate as validate_format

logger = logging.getLogger(__name__)

_FINGERPRINT_RE = re.compile(r'\b([0-9A-Fa-f]{40})\b')
_IPPORT_RE = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3}:\d{2,5})')
_IP_ONLY_RE = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})')
_DOC_IPV6_PREFIX = "2001:db8"

# ── Приоритетные источники (Delta-Kronecker) ──────────────────────────────────
# Загружаются ПЕРВЫМИ и последовательно.
# Если мост из приоритетного источника совпадает по fingerprint с мостом из
# обычного — берётся приоритетная версия.
PRIORITY_SOURCES = {
    "obfs4": [
        # Протестированные мосты — самый высокий приоритет
        "https://raw.githubusercontent.com/Delta-Kronecker/Tor-Bridges-Collector/main/obfs4_tested.txt",
        # Основной сборник Delta-Kronecker
        "https://raw.githubusercontent.com/Delta-Kronecker/Tor-Bridges-Collector/main/bridges-obfs4",
    ],
    "webtunnel": [
        "https://raw.githubusercontent.com/Delta-Kronecker/Tor-Bridges-Collector/main/bridges-webtunnel",
    ],
    "vanilla": [
        "https://raw.githubusercontent.com/Delta-Kronecker/Tor-Bridges-Collector/main/bridges-vanilla",
    ],
}

# ── Стандартные источники (scriptzteam + зеркала) ────────────────────────────
# Загружаются параллельно ПОСЛЕ приоритетных.
# Дублирующиеся fingerprint'ы отбрасываются.
STANDARD_SOURCES = {
    "obfs4": [
        "https://raw.githubusercontent.com/scriptzteam/Tor-Bridges-Collector/main/bridges-obfs4",
        "https://raw.githubusercontent.com/Ckid-Home/tor-bridges/main/bridges-obfs4",
        "https://raw.githubusercontent.com/miguelneto0/tor-bridges-list/main/obfs4_bridges.txt",
        "https://raw.githubusercontent.com/miladtorrent/tor-bridges/main/obfs4.txt",
        "https://raw.githubusercontent.com/nicktacular/tor-obfs4-bridges/main/bridges.txt",
    ],
    "webtunnel": [
        "https://raw.githubusercontent.com/scriptzteam/Tor-Bridges-Collector/main/bridges-webtunnel",
        "https://raw.githubusercontent.com/Ckid-Home/tor-bridges/main/bridges-webtunnel",
        "https://raw.githubusercontent.com/miguelneto0/tor-bridges-list/main/webtunnel_bridges.txt",
    ],
    "vanilla": [
        "https://raw.githubusercontent.com/scriptzteam/Tor-Bridges-Collector/main/bridges-vanilla",
        "https://raw.githubusercontent.com/Ckid-Home/tor-bridges/main/bridges-vanilla",
        "https://raw.githubusercontent.com/miguelneto0/tor-bridges-list/main/vanilla_bridges.txt",
    ],
}

# Объединённый список для информационных нужд
BRIDGE_SOURCES = {
    k: PRIORITY_SOURCES.get(k, []) + STANDARD_SOURCES.get(k, [])
    for k in ("obfs4", "webtunnel", "vanilla")
}


def _bridge_key(line: str) -> str:
    """Ключ для дедупликации по fingerprint."""
    m = _FINGERPRINT_RE.search(line)
    if m:
        return m.group(1).upper()
    m = _IPPORT_RE.search(line)
    if m:
        ip = m.group(1).split(":")[0]
        if not ip.startswith(_DOC_IPV6_PREFIX):
            return m.group(1)
    return line.strip()


def _bridge_ip(line: str) -> str | None:
    """Извлекает IP-адрес из строки моста (для IP-дедупликации)."""
    m = _IPPORT_RE.search(line)
    if m:
        return m.group(1).split(":")[0]
    return None


def _source_label(url: str) -> str:
    """Короткое название для лога и UI."""
    if "github.com" in url:
        parts = url.split("github.com/")[-1].split("/")
        return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else url.split("/")[-1]
    return url.split("/")[-1]


def _fetch_from_url(url: str, timeout: int = 15) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "TorProxyManager/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read().decode("utf-8", errors="replace")
    return [
        ln.strip()
        for ln in content.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _add_bridge(bridge: str, unique: dict, seen_ips: set, rejected: list) -> bool:
    """
    Пытается добавить мост в словарь unique.
    Проверяет: формат (validate_format), дубликат fingerprint, дубликат IP.
    Возвращает True если мост принят.
    """
    ok, reason = validate_format(bridge)
    if not ok:
        rejected.append((bridge, reason))
        return False

    key = _bridge_key(bridge)
    if key in unique:
        return False  # дубликат по fingerprint

    ip = _bridge_ip(bridge)
    if ip and ip in seen_ips:
        rejected.append((bridge, f"duplicate IP: {ip}"))
        return False

    unique[key] = bridge
    if ip:
        seen_ips.add(ip)
    return True


def fetch_bridges_parallel(bridge_type: str, fetch_timeout: int = 15,
                            progress_cb=None) -> list:
    """
    Двухэтапная загрузка:
    1. Последовательно — приоритетные источники (Delta-Kronecker, tested first)
    2. Параллельно — стандартные источники (scriptzteam + зеркала)

    Каждый мост проверяется:
    - Формат (validate_format): fingerprint, cert=, iat-mode=, url= и т.д.
    - Чёрный список IP: 8.8.8.8, приватные подсети, loopback
    - Дедупликация по fingerprint: приоритетные версии сохраняются
    - Дедупликация по IP: один мост на IP (первый найденный побеждает)
    """
    unique: dict = {}  # key → bridge_line
    seen_ips: set = set()  # для IP-дедупликации
    rejected: list = []  # для статистики отклонённых
    priority = PRIORITY_SOURCES.get(bridge_type, [])
    standard = STANDARD_SOURCES.get(bridge_type, [])

    # ── Шаг 1: приоритетные источники ─────────────────────────────────────────
    for url in priority:
        label = _source_label(url)
        try:
            bridges = _fetch_from_url(url, fetch_timeout)
            added = 0
            for b in bridges:
                if _add_bridge(b, unique, seen_ips, rejected):
                    added += 1
            logger.info(f"[★ {label}] {len(bridges)} мостов, {added} новых")
            if progress_cb and added > 0:
                progress_cb(f"[★] {label}: +{added} мостов")
        except Exception as e:
            logger.warning(f"Приоритетный источник недоступен [{label}]: {e}")

    # ── Шаг 2: стандартные источники параллельно ──────────────────────────────
    if standard:
        with ThreadPoolExecutor(max_workers=len(standard)) as executor:
            future_to_url = {
                executor.submit(_fetch_from_url, url, fetch_timeout): url
                for url in standard
            }
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                label = _source_label(url)
                try:
                    bridges = future.result()
                    added = 0
                    for b in bridges:
                        if _add_bridge(b, unique, seen_ips, rejected):
                            added += 1
                    logger.info(f"[{label}] {len(bridges)} мостов, {added} новых")
                    if progress_cb and added > 0:
                        progress_cb(f"[OK] {label}: +{added} мостов")
                except Exception as e:
                    logger.warning(f"Источник недоступен [{label}]: {e}")

    if rejected:
        logger.info(f"Отклонено {len(rejected)} мостов (формат/bogon/дубли IP)")
        for bridge, reason in rejected[:10]:
            logger.debug(f"  rejected [{reason}]: {bridge[:80]}")

    return list(unique.values())


class BridgeFetcherThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, bridge_type: str):
        super().__init__()
        self.bridge_type = bridge_type

    def run(self):
        try:
            p = len(PRIORITY_SOURCES.get(self.bridge_type, []))
            s = len(STANDARD_SOURCES.get(self.bridge_type, []))
            self.progress.emit(
                f"Загрузка мостов: {p} приоритетных + {s} стандартных ({self.bridge_type})..."
            )
            bridges = fetch_bridges_parallel(
                self.bridge_type,
                progress_cb=lambda msg: self.progress.emit(msg),
            )
            self.progress.emit(f"Собрано {len(bridges)} уникальных мостов")
            self.finished.emit(bridges)
        except Exception as e:
            logger.error(f"Ошибка загрузки мостов: {e}")
            self.error.emit(str(e))
