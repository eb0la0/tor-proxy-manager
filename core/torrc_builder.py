"""
Генератор torrc — конфиг оптимизирован для:
- Обхода блокировок РКН / глубокой инспекции пакетов (DPI)
- Максимальной скорости при подключении через мосты
- Корректной работы obfs4 и webtunnel транспортов
"""
import os
import logging
from pathlib import Path
from core.config import CONFIG_DIR, DATA_DIR, LOGS_DIR, TOR_LOG_FILE, TORRC_FILE

logger = logging.getLogger(__name__)


def _winpath(p) -> str:
    """
    Возвращает абсолютный путь в Windows-формате (обратные слеши).

    На Windows дополнительно конвертирует путь в короткую 8.3-форму через
    GetShortPathNameW, чтобы путь содержал только ASCII-символы.
    Это необходимо для корректной работы tor.exe на системах с кириллическими
    именами пользователей: Tor читает torrc через ANSI-кодпейдж (CP1251/1252),
    а не UTF-8, поэтому Unicode-пути превращаются в мусор.

    ВАЖНО: GetShortPathNameW работает только для уже существующих путей.
    Директории DataDirectory и др. должны быть созданы до вызова этой функции.
    Config._ensure_dirs() гарантирует это при каждом запуске приложения.
    """
    abs_path = os.path.abspath(str(p))
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(32767)
            ret = ctypes.windll.kernel32.GetShortPathNameW(abs_path, buf, len(buf))
            if ret:
                return buf.value
            # ret == 0 означает что путь не существует или нет 8.3-имён —
            # в таком случае возвращаем оригинальный путь как fallback
        except Exception:
            pass
    return abs_path


def _find_geoip(tor_exe: str):
    """Ищет geoip/geoip6 рядом с tor.exe."""
    if not tor_exe:
        return None, None
    tor_dir = Path(tor_exe).parent
    candidates = [
        tor_dir / "geoip",
        tor_dir.parent / "Data" / "Tor" / "geoip",
        tor_dir / "Data" / "Tor" / "geoip",
        DATA_DIR / "geoip",
    ]
    for c in candidates:
        if c.exists():
            geoip6 = c.parent / "geoip6"
            return c, geoip6 if geoip6.exists() else None
    return None, None


def build_torrc(
    socks_port: int,
    bridge_type: str,
    bridges: list,
    lyrebird_exe: str = "",
    tor_exe: str = "",
) -> str:
    """
    Генерирует содержимое torrc.
    bridges — список строк мостов или список кортежей (строка, latency).
    """
    lines = [
        "# ================================================================",
        "# TorProxy Manager — автоматически сгенерированный torrc",
        "# Оптимизирован для обхода РКН/DPI и максимальной производительности",
        "# ================================================================",
        "",

        # ── Базовые настройки ──────────────────────────────────────────────
        "# Порт SOCKS5-прокси (127.0.0.1 — только локально, безопасно)",
        f"SocksPort 127.0.0.1:{socks_port}",
        "",

        "# Папка для хранения состояния (ключи, статистика guard-нод)",
        f"DataDirectory {_winpath(DATA_DIR)}",
        "",

        "# Логи: stdout для UI-монитора + файл для диагностики",
        "Log notice stdout",
        f"Log notice file {_winpath(TOR_LOG_FILE)}",
        "",

        # ── Режим клиента ──────────────────────────────────────────────────
        "# Работать только как клиент — не становиться ретранслятором",
        "ClientOnly 1",
        "",

        "# Не писать лишние файлы на диск (быстрее, меньше нагрузка на SSD)",
        "AvoidDiskWrites 1",
        "",

        "# Microdescriptors вместо полных дескрипторов (~10x меньше данных)",
        "# Ускоряет bootstrap на 10-30 сек за счёт меньшего объёма скачивания",
        "UseMicrodescriptors 1",
        "",

        "# Предпочитать IPv4 для OR-портов — IPv6 часто блокируется провайдерами РФ",
        "ClientPreferIPv6ORPort 0",
        "",

        # ── Производительность цепочек ─────────────────────────────────────
        # ВАЖНО: через мосты (особенно webtunnel/obfs4) сборка цепочки
        # занимает 15–40 сек. Слишком короткий таймаут приводит к тому, что
        # Tor убивает circuit до завершения → "invalid selected path",
        # а consensus (2-3 МБ) не успевает скачаться → зависание на 95%.
        #
        "# Начальный лимит на время сборки цепочки — 30 сек",
        "# Через мосты нужно больше времени чем напрямую (PT-хэндшейк + CDN + relay)",
        "CircuitBuildTimeout 30",
        "",

        "# Разрешить Tor адаптировать таймаут к реальным условиям сети",
        "# (1 = включено — Tor учится на успешных circuit'ах и подстраивает таймаут)",
        "LearnCircuitBuildTimeout 1",
        "",

        "# Максимальное время жизни цепочки до принудительной смены — 10 минут",
        "MaxCircuitDirtiness 600",
        "",

        "# Создавать новую цепочку каждые 120 секунд",
        "# Слишком частая смена (30 сек) убивает circuit во время скачивания consensus",
        "# и вызывает бесконечный цикл на 95% bootstrap",
        "NewCircuitPeriod 120",
        "",

        "# Если поток данных завис — разорвать и создать новую цепочку через 120 сек",
        "# (через мосты передача медленнее — нужно больше терпения)",
        "CircuitStreamTimeout 120",
        "",

        "# Таймаут ответа от SOCKS-клиента (браузер/приложение) — 2 минуты",
        "SocksTimeout 120",
        "",

        "# Количество Entry Guard-нод (первых узлов цепочки)",
        "# 2 — при мостах меньше guard'ов = меньше неудачных попыток",
        "NumEntryGuards 2",
        "",

        # ── CPU и буферизация ──────────────────────────────────────────────
        "# Автоматически использовать все доступные CPU-ядра (0 = авто)",
        "NumCPUs 0",
        "",

        "# Интервал пополнения токен-бакета — 10 мс (по умолчанию 100 мс)",
        "# Снижает джиттер при передаче данных, особенно важно для видео/VoIP",
        "TokenBucketRefillInterval 10 msec",
        "",

        # ── Авто-восстановление после обрыва сети ─────────────────────────
        "# Keepalive: как часто Tor проверяет живые ли OR-соединения",
        "# По умолчанию 300 сек (5 мин!) — слишком долго для обнаружения обрыва",
        "# 60 сек — мёртвый мост обнаруживается за ~1 минуту вместо ~5",
        "KeepalivePeriod 60",
        "",

        "# ControlPort: позволяет отправлять команды Tor без перезапуска процесса",
        "# SIGNAL NEWNYM = пересоздать все circuits (мягкий reset)",
        "# CookieAuthentication = авторизация через файл в DataDirectory",
        f"ControlPort 127.0.0.1:{socks_port + 1}",
        "CookieAuthentication 1",
        "",

    ]

    # ── GeoIP ──────────────────────────────────────────────────────────────
    geoip, geoip6 = _find_geoip(tor_exe)
    # Записываем только если файл реально существует на диске
    geoip_ok = geoip and geoip.exists()
    geoip6_ok = geoip6 and geoip6.exists()
    if geoip_ok:
        lines += [
            "# Таблица геолокации IP-адресов (нужна для статистики и исключений)",
            f"GeoIPFile {_winpath(geoip)}",
        ]
    if geoip6_ok:
        lines.append(f"GeoIPv6File {_winpath(geoip6)}")
    if geoip_ok or geoip6_ok:
        lines.append("")

    # ── Мосты ──────────────────────────────────────────────────────────────
    bridge_strings = []
    for b in bridges:
        s = b[0] if isinstance(b, tuple) else b
        s = s.strip()
        if s:
            bridge_strings.append(s)

    if not bridge_strings:
        return "\n".join(lines) + "\n"

    lines += [
        "# ── Мосты и транспорты ──────────────────────────────────────────",
        "# Включить поддержку мостов (не использовать публичные relay-ноды)",
        "UseBridges 1",
        "",
    ]

    # Определяем реальные типы транспортов из строк мостов
    transport_types: set[str] = set()
    for bs in bridge_strings:
        clean = bs[7:] if bs.lower().startswith("bridge ") else bs
        first = clean.split()[0] if clean.split() else ""
        if first in ("obfs4", "webtunnel", "scramblesuit", "meek_lite", "snowflake"):
            transport_types.add(first)
    # Также учитываем настроенный тип
    if bridge_type in ("obfs4", "webtunnel"):
        transport_types.add(bridge_type)

    has_webtunnel = "webtunnel" in transport_types
    if has_webtunnel:
        lines += [
            "# webtunnel использует фиктивный IPv6 (2001:db8::) в строке моста.",
            "# Реальный трафик идёт через CDN по IPv4 — поэтому отключаем IPv6",
            "ClientUseIPv4 1",
            "ClientUseIPv6 0",
            "",
        ]

    # ClientTransportPlugin для каждого транспорта
    if lyrebird_exe and Path(lyrebird_exe).exists():
        lyre_path = _winpath(lyrebird_exe)
        for transport in sorted(transport_types):
            lines += [
                f"# Подключаемый транспорт {transport} — запускается через lyrebird",
                f"ClientTransportPlugin {transport} exec {lyre_path}",
            ]
        lines.append("")
    elif lyrebird_exe:
        logger.warning(f"lyrebird.exe не найден по пути: {lyrebird_exe}")

    lines.append("# Список мостов (отсортированы по скорости ответа — лучшие первые)")
    for bs in bridge_strings:
        prefix = "Bridge " if not bs.lower().startswith("bridge ") else ""
        lines.append(f"{prefix}{bs}")

    return "\n".join(lines) + "\n"


def save_torrc(content: str) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TORRC_FILE.write_text(content, encoding="utf-8")
    logger.info(f"torrc сохранён: {TORRC_FILE}")
    return TORRC_FILE


def build_and_save_torrc(
    socks_port: int,
    bridge_type: str,
    bridges: list,
    lyrebird_exe: str = "",
    tor_exe: str = "",
) -> Path:
    content = build_torrc(socks_port, bridge_type, bridges, lyrebird_exe, tor_exe)
    return save_torrc(content)
