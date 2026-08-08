import re
import ssl
import random
import socket
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from PyQt5.QtCore import QThread, pyqtSignal

from core.bridge_validator import validate as validate_format

logger = logging.getLogger(__name__)

_IPV4_PORT_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})")
_IPV6_PORT_RE = re.compile(r"\[([0-9a-fA-F:]+)\]:(\d{2,5})")
_WEBTUNNEL_URL_RE = re.compile(r"\burl=(https?://[^\s]+)", re.IGNORECASE)
_DOC_IPV6_PREFIX = "2001:db8"


def _extract_addr(bridge_line: str):
    """
    Возвращает (host, port) для сетевого теста.

    webtunnel: домен из url=https://...  (IP — фиктивный 2001:db8::/32)
    obfs4/vanilla: IPv4, затем IPv6 (кроме 2001:db8::)
    """
    stripped = bridge_line.strip()
    lower = stripped.lower()

    if lower.startswith("webtunnel") or "webtunnel" in lower:
        m = _WEBTUNNEL_URL_RE.search(stripped)
        if m:
            try:
                parsed = urlparse(m.group(1))
                host = parsed.hostname
                port = parsed.port or 443
                if host:
                    return host, port
            except Exception:
                pass
        return None, None

    m = _IPV4_PORT_RE.search(stripped)
    if m:
        return m.group(1), int(m.group(2))

    m = _IPV6_PORT_RE.search(stripped)
    if m:
        ip = m.group(1)
        if ip.startswith(_DOC_IPV6_PREFIX):
            return None, None
        return ip, int(m.group(2))

    return None, None


def _test_tcp(host: str, port: int, timeout: int) -> float | None:
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return (time.monotonic() - t0) * 1000.0
    except Exception:
        return None


def _test_tls(host: str, port: int, timeout: int) -> float | None:
    """
    TCP + TLS handshake с проверкой сертификата.
    Мост с просроченным или невалидным сертом → None (отклонён).
    """
    try:
        t0 = time.monotonic()
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                tls.do_handshake()
        return (time.monotonic() - t0) * 1000.0
    except ssl.SSLCertVerificationError as e:
        logger.debug(f"TLS cert invalid {host}:{port}: {e}")
        return None
    except ssl.SSLError as e:
        logger.debug(f"TLS error {host}:{port}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Connection failed {host}:{port}: {e}")
        return None


def test_bridge(bridge_line: str, timeout: int = 10):
    """
    Полная проверка моста:
    1. Синтаксическая валидация (формат, обязательные поля)
    2. Сетевая проверка:
       - webtunnel → TCP + TLS (фильтрует просроченные серты)
       - obfs4/vanilla → TCP (PT сам шифрует трафик)

    Возвращает (bridge_line, latency_ms) или (bridge_line, None).
    """
    stripped = bridge_line.strip()

    # ── Шаг 1: формат ─────────────────────────────────────────────────────────
    ok, reason = validate_format(stripped)
    if not ok:
        logger.debug(f"Format rejected [{reason}]: {stripped[:60]}")
        return bridge_line, None

    # ── Шаг 2: сеть ───────────────────────────────────────────────────────────
    host, port = _extract_addr(stripped)
    if host is None:
        return bridge_line, None

    lower = stripped.lower()
    if lower.startswith("webtunnel") or "webtunnel" in lower:
        latency = _test_tls(host, port, timeout)
    else:
        latency = _test_tcp(host, port, timeout)

    return bridge_line, latency


class BridgeTesterThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    MAX_SAMPLE = 250

    # Доля выборки, которая берётся с начала списка без перемешивания.
    # Список приходит отсортированным по приоритету источника, поэтому в голове
    # находятся курируемые и предпроверенные мосты. Чисто случайная выборка
    # из тысяч мостов почти гарантированно их бы потеряла.
    HEAD_RATIO = 0.6

    def __init__(self, bridges: list, timeout: int = 10, top_n: int = 20, workers: int = 30):
        super().__init__()
        self.timeout = timeout
        self.top_n = top_n
        self.workers = workers
        self._cancelled = False
        self.bridges = self._make_sample(bridges)

    def _make_sample(self, bridges: list) -> list:
        """
        Выборка = голова списка (лучшие источники) + случайные из остатка.
        Случайная часть нужна, чтобы при каждом обновлении пробовались разные
        мосты и набор не «залипал» на одних и тех же мёртвых адресах.
        """
        if len(bridges) <= self.MAX_SAMPLE:
            return list(bridges)

        head_n = int(self.MAX_SAMPLE * self.HEAD_RATIO)
        head = list(bridges[:head_n])
        tail_n = self.MAX_SAMPLE - len(head)
        tail = random.sample(bridges[head_n:], tail_n)

        logger.info(
            f"Выборка: {self.MAX_SAMPLE} из {len(bridges)} мостов "
            f"({len(head)} приоритетных + {len(tail)} случайных)"
        )
        return head + tail

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.bridges)
        if total == 0:
            self.finished.emit([])
            return

        self.progress.emit(0, f"Тестирование {total} мостов...")
        results = []
        completed = 0

        # Executor создаётся без `with`: при отмене нельзя дожидаться очереди
        # из сотен проверок по self.timeout секунд каждая — выход из приложения
        # должен быть быстрым.
        executor = ThreadPoolExecutor(max_workers=self.workers)
        cancelled = False
        try:
            futures = [
                executor.submit(test_bridge, b, self.timeout)
                for b in self.bridges
            ]
            for future in as_completed(futures):
                if self._cancelled:
                    cancelled = True
                    return

                completed += 1
                try:
                    bridge_line, latency = future.result()
                    if latency is not None:
                        results.append((bridge_line, latency))
                except Exception as e:
                    logger.debug(f"Ошибка теста: {e}")

                if completed % 20 == 0 or completed == total:
                    pct = int(completed / total * 100)
                    self.progress.emit(
                        pct,
                        f"Протестировано {completed}/{total}, рабочих: {len(results)}"
                    )

            results.sort(key=lambda x: x[1])
            top = results[: self.top_n]
            self.progress.emit(
                100,
                f"Готово! Рабочих: {len(results)}, выбрано топ-{len(top)}"
            )
            self.finished.emit(top)

        except Exception as e:
            logger.error(f"Ошибка тестирования: {e}")
            self.error.emit(str(e))
        finally:
            # cancel_futures отбрасывает не начатые проверки; уже открытые
            # сокеты доработают до своего таймаута в фоне.
            executor.shutdown(wait=not cancelled, cancel_futures=cancelled)
