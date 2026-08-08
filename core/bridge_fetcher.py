"""
Загрузка мостов из нескольких независимых источников с автоматическим fallback.

Схема работы:

    для каждого источника (параллельно, с ограничением concurrency)
        перебрать зеркала по очереди → первое валидное содержимое побеждает
                    ↓
    слить результаты по убыванию приоритета источника
                    ↓
    validate → normalize → deduplicate
                    ↓
    FetchResult (мосты + статус каждого источника)

Ни один источник не является обязательным: падение GitHub, GitLab или любого
другого хостинга уменьшает количество мостов, но не ломает обновление.
"""
import re
import time
import logging
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import urlparse

from PyQt5.QtCore import QThread, pyqtSignal

from core.bridge_validator import validate as validate_format
from core.bridge_sources import SOURCES, sources_for

logger = logging.getLogger(__name__)

_FINGERPRINT_RE = re.compile(r'\b([0-9A-Fa-f]{40})\b')
_IPPORT_RE = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3}:\d{2,5})')
_DOC_IPV6_PREFIX = "2001:db8"

# ── Защита от недоверенного содержимого ──────────────────────────────────────
# Любой внешний источник считается недоверенным: он может отдать HTML-страницу
# ошибки с кодом 200, страницу rate-limit, гигабайтный файл или мусор.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024   # 8 МБ — все реальные списки < 1.5 МБ
MAX_REDIRECTS = 3
MAX_LINES = 200_000
_HTML_MARKERS = ("<!doctype html", "<html", "<head", "<body", "<?xml")
_ALLOWED_SCHEMES = ("https",)
_USER_AGENT = "TorProxyManager/1.0"

# Ограничение параллелизма: источников немного, но каждый может перебирать
# несколько зеркал. 4 одновременных загрузки — компромисс скорость/нагрузка.
MAX_CONCURRENT_SOURCES = 4

# Общий дедлайн на всю операцию, чтобы один мёртвый источник не подвешивал UI.
DEFAULT_TOTAL_DEADLINE = 60.0
DEFAULT_TIMEOUT = 12


class FetchRejected(Exception):
    """Ответ получен, но не является списком мостов (зеркало непригодно)."""


class EmptyContent(Exception):
    """
    Ответ корректный, но списка мостов в нём нет.

    Это НЕ то же самое, что недоступность. Источник может честно опубликовать
    пустой файл (у сборщиков такое бывает для редких транспортов), и это
    валидный ответ «сейчас мостов нет», а не поломка. Такое зеркало не
    считается сбойным, но перебор продолжается: вдруг другое зеркало
    успело обновиться.
    """


# ── Совместимость: плоский список URL для справки/диагностики ────────────────
BRIDGE_SOURCES = {
    t: [u for s in sources_for(t) for u in s.urls_for(t)]
    for t in ("obfs4", "webtunnel", "vanilla")
}


class _StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    Редиректы разрешены только на https и только в пределах того же хоста.

    Проверено 2026-08-08: ни одно из настроенных зеркал редиректов не требует —
    все отдают 200 напрямую. Поэтому запрет межхостовых переходов ничего не
    ломает, но лишает недоверенное (или скомпрометированное) зеркало
    возможности превратить загрузку мостов в запрос к произвольному адресу.
    """

    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlparse(newurl)
        if target.scheme not in _ALLOWED_SCHEMES:
            raise FetchRejected(f"redirect to non-https: {newurl[:80]}")
        if (target.hostname or "").lower() != (req.host or "").split(":")[0].lower():
            raise FetchRejected(f"cross-host redirect to {target.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_StrictRedirectHandler())


def _looks_like_html(text: str) -> bool:
    head = text[:512].lstrip().lower()
    return any(head.startswith(m) for m in _HTML_MARKERS)


def _fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT) -> list:
    """
    Скачивает один URL и возвращает список содержательных строк.

    Поднимает FetchRejected, если ответ не похож на текстовый список мостов:
    HTML-страница ошибки, неверный Content-Type, пустой или слишком большой
    ответ. HTTP 200 сам по себе НЕ считается успехом.
    """
    if urlparse(url).scheme not in _ALLOWED_SCHEMES:
        raise FetchRejected(f"unsupported scheme in {url[:80]}")

    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "text/plain, */*",
    })
    with _opener.open(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" in ctype:
            raise FetchRejected(f"unexpected Content-Type: {ctype[:60]}")
        # Читаем на 1 байт больше лимита, чтобы отличить "ровно лимит" от обрезки
        raw = resp.read(MAX_RESPONSE_BYTES + 1)

    if len(raw) > MAX_RESPONSE_BYTES:
        raise FetchRejected(f"response too large (> {MAX_RESPONSE_BYTES} bytes)")

    content = raw.decode("utf-8", errors="replace")
    if _looks_like_html(content):
        raise FetchRejected("HTML page instead of plain text")

    lines = []
    for ln in content.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            lines.append(ln)
        if len(lines) >= MAX_LINES:
            break

    # Пустой (или состоящий из одних комментариев) файл — корректный ответ
    # «мостов нет», а не признак сломанного зеркала. См. EmptyContent.
    if not lines:
        raise EmptyContent("no bridge lines in response")
    return lines


# ── Дедупликация ─────────────────────────────────────────────────────────────

def _bridge_key(line: str) -> str:
    """Ключ дедупликации: fingerprint, иначе IP:порт, иначе сама строка."""
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
    m = _IPPORT_RE.search(line)
    return m.group(1).split(":")[0] if m else None


def _source_label(url: str) -> str:
    """Короткая метка хоста для лога: gitlab.com, raw.githack.com и т.д."""
    return urlparse(url).hostname or url[:40]


# ── Результаты ───────────────────────────────────────────────────────────────

@dataclass
class SourceResult:
    name: str
    priority: int
    provider: str = ""
    ok: bool = False         # зеркало ответило корректными данными (возможно, пустыми)
    empty: bool = False      # ответ валиден, но мостов в нём нет
    url: str = ""
    host: str = ""
    lines: list = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0
    accepted: int = 0        # сколько мостов от этого источника попало в итог


@dataclass
class FetchResult:
    bridges: list = field(default_factory=list)
    sources: list = field(default_factory=list)     # list[SourceResult]
    rejected: int = 0

    @property
    def ok_sources(self) -> list:
        return [s for s in self.sources if s.ok]

    @property
    def failed_sources(self) -> list:
        return [s for s in self.sources if not s.ok]

    @property
    def total_sources(self) -> int:
        return len(self.sources)

    @property
    def any_success(self) -> bool:
        return bool(self.ok_sources)

    # ── Провайдеры, а не источники ───────────────────────────────────────────
    # Два списка из одного репозитория («проверенный» и «полный») падают
    # вместе, поэтому показывать их пользователю как две независимые точки
    # отказа неверно. Считаем именно независимых поставщиков.

    @property
    def ok_providers(self) -> set:
        return {s.provider for s in self.sources if s.ok and s.provider}

    @property
    def all_providers(self) -> set:
        return {s.provider for s in self.sources if s.provider}

    @property
    def total_providers(self) -> int:
        return len(self.all_providers)

    @property
    def empty_sources(self) -> list:
        """Источники, ответившие корректно, но без мостов."""
        return [s for s in self.sources if s.ok and s.empty]


def _add_bridge(bridge: str, unique: dict, seen_ips: set, rejected: list) -> bool:
    """
    Добавляет мост, если он валиден по формату и не является дублем
    по fingerprint или по IP. Возвращает True, если мост принят.
    """
    ok, reason = validate_format(bridge)
    if not ok:
        rejected.append((bridge, reason))
        return False

    key = _bridge_key(bridge)
    if key in unique:
        return False

    ip = _bridge_ip(bridge)
    if ip and ip in seen_ips:
        rejected.append((bridge, f"duplicate IP: {ip}"))
        return False

    unique[key] = bridge
    if ip:
        seen_ips.add(ip)
    return True


def _fetch_source(source, bridge_type: str, timeout: int,
                  deadline: float, cancel: threading.Event) -> SourceResult:
    """
    Перебирает зеркала источника по порядку до первого валидного ответа.
    Не-GitHub зеркала стоят первыми — см. core/bridge_sources.
    """
    res = SourceResult(name=source.name, priority=source.priority,
                       provider=source.provider)
    errors = []
    saw_empty = ""            # зеркало ответило корректно, но без мостов
    t_start = time.monotonic()

    for url in source.urls_for(bridge_type):
        if cancel.is_set() or time.monotonic() > deadline:
            res.error = "cancelled" if cancel.is_set() else "deadline exceeded"
            break

        host = _source_label(url)
        t0 = time.monotonic()
        try:
            lines = _fetch_url(url, timeout)
        except EmptyContent:
            # Не сбой: источник честно отдал пустой список. Пробуем остальные
            # зеркала — вдруг какое-то уже обновилось, — но если пусто везде,
            # источник всё равно считается ответившим.
            saw_empty = host
            logger.info(f"[{source.name}] {host}: ответ пуст (мостов нет)")
            continue
        except FetchRejected as e:
            errors.append(f"{host}: invalid content ({e})")
            logger.warning(f"[{source.name}] {host}: отклонено — {e}")
            continue
        except urllib.error.HTTPError as e:
            errors.append(f"{host}: HTTP {e.code}")
            logger.warning(f"[{source.name}] {host}: HTTP {e.code}")
            continue
        except Exception as e:
            errors.append(f"{host}: {type(e).__name__}")
            logger.warning(f"[{source.name}] {host}: {type(e).__name__}: {e}")
            continue

        res.ok = True
        res.url = url
        res.host = host
        res.lines = lines
        res.elapsed = time.monotonic() - t0
        logger.info(
            f"[{source.name}] {host}: 200 OK, {len(lines)} строк "
            f"за {res.elapsed * 1000:.0f}мс"
        )
        return res

    res.elapsed = time.monotonic() - t_start

    if saw_empty and not res.error:
        # Ни одно зеркало не дало мостов, но как минимум одно ответило корректно.
        # Это «источник пуст», а не «источник недоступен».
        res.ok = True
        res.empty = True
        res.host = saw_empty
        logger.info(f"[{source.name}] источник доступен, но мостов не содержит")
        return res

    if not res.error:
        res.error = "; ".join(errors) or "no mirrors configured"
    logger.warning(f"[{source.name}] все зеркала недоступны: {res.error}")
    return res


def fetch_bridges(bridge_type: str,
                  fetch_timeout: int = DEFAULT_TIMEOUT,
                  progress_cb=None,
                  cancel: threading.Event | None = None,
                  total_deadline: float = DEFAULT_TOTAL_DEADLINE) -> FetchResult:
    """
    Загружает мосты указанного типа из всех включённых источников.

    Источники грузятся параллельно (не ждём таймаут каждого по очереди),
    но сливаются строго по убыванию приоритета — результат детерминирован
    и не зависит от того, кто ответил первым.
    """
    cancel = cancel or threading.Event()
    deadline = time.monotonic() + total_deadline
    srcs = sources_for(bridge_type)

    result = FetchResult()
    if not srcs:
        logger.error(f"Нет источников для типа {bridge_type}")
        return result

    logger.info(f"[BridgeManager] Старт обновления: {len(srcs)} источников ({bridge_type})")

    results_by_name = {}
    workers = min(MAX_CONCURRENT_SOURCES, len(srcs))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_source, s, bridge_type, fetch_timeout, deadline, cancel): s
            for s in srcs
        }
        for future in as_completed(futures):
            src = futures[future]
            try:
                sr = future.result()
            except Exception as e:  # защита от неожиданного падения воркера
                logger.error(f"[{src.name}] внутренняя ошибка: {e}")
                sr = SourceResult(name=src.name, priority=src.priority,
                                  provider=src.provider,
                                  error=f"internal: {type(e).__name__}")
            results_by_name[src.name] = sr
            if progress_cb:
                if sr.ok:
                    progress_cb(f"[OK] {sr.name} ({sr.host}): {len(sr.lines)} строк")
                else:
                    progress_cb(f"[--] {sr.name}: недоступен")

    # ── Слияние строго по приоритету ─────────────────────────────────────────
    unique: dict = {}
    seen_ips: set = set()
    rejected: list = []

    for src in srcs:                      # уже отсортированы по убыванию приоритета
        sr = results_by_name.get(src.name)
        if sr is None:
            sr = SourceResult(name=src.name, priority=src.priority,
                              provider=src.provider, error="not run")
        result.sources.append(sr)
        if not sr.ok:
            continue
        before = len(unique)
        for line in sr.lines:
            _add_bridge(line, unique, seen_ips, rejected)
        sr.accepted = len(unique) - before
        logger.info(f"[BridgeManager] {sr.name}: +{sr.accepted} уникальных")

    result.bridges = list(unique.values())
    result.rejected = len(rejected)

    logger.info(
        f"[BridgeManager] Источников OK: {len(result.ok_sources)}/{result.total_sources}, "
        f"независимых поставщиков: {len(result.ok_providers)}/{result.total_providers}, "
        f"уникальных мостов: {len(result.bridges)}, отклонено строк: {result.rejected}"
    )
    for bridge, reason in rejected[:5]:
        logger.debug(f"  rejected [{reason}]: {bridge[:80]}")

    return result


def fetch_bridges_parallel(bridge_type: str, fetch_timeout: int = DEFAULT_TIMEOUT,
                           progress_cb=None) -> list:
    """Обратно совместимая обёртка: только список мостов, без статистики."""
    return fetch_bridges(bridge_type, fetch_timeout, progress_cb).bridges


class BridgeFetcherThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)     # FetchResult
    error = pyqtSignal(str)

    def __init__(self, bridge_type: str, fetch_timeout: int = DEFAULT_TIMEOUT):
        super().__init__()
        self.bridge_type = bridge_type
        self.fetch_timeout = fetch_timeout
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            result = fetch_bridges(
                self.bridge_type,
                fetch_timeout=self.fetch_timeout,
                progress_cb=self.progress.emit,
                cancel=self._cancel,
            )
            if self._cancel.is_set():
                return
            self.finished.emit(result)
        except Exception as e:
            logger.error(f"Ошибка загрузки мостов: {e}", exc_info=True)
            self.error.emit(str(e))
