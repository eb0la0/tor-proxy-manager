"""
Синтаксическая валидация строк мостов без сетевого доступа.
Мост прошедший эту проверку не обязательно работает,
но провалившийся — точно неисправен.

Включает чёрный список IP: публичные DNS, localhost, приватные подсети,
и другие адреса, которые гарантированно не являются Tor-мостами.
"""
import re
import ipaddress
from urllib.parse import urlparse

_FINGERPRINT_RE = re.compile(r'\b([0-9A-Fa-f]{40})\b')
_IPV4_PORT_RE = re.compile(r'\b(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})\b')
_IPV6_PORT_RE = re.compile(r'\[([0-9a-fA-F:]+)\]:(\d{2,5})')
_OBFS4_CERT_RE = re.compile(r'\bcert=([A-Za-z0-9+/]{10,}={0,2})\b')
_OBFS4_IAT_RE = re.compile(r'\biat-mode=([012])\b')
_WEBTUNNEL_URL_RE = re.compile(r'\burl=(https?://[^\s]+)', re.IGNORECASE)

# RFC 3849 — документационный диапазон, используется как placeholder в webtunnel
_DOC_IPV6 = "2001:db8"

# ── Чёрный список конкретных IP ──────────────────────────────────────────────
# Публичные DNS-серверы, anycast-адреса и другие IP, которые точно не являются
# мостами Tor. Если такой IP появляется в строке моста — источник загрязнён.
_BLACKLISTED_IPS = frozenset({
    # Google DNS
    "8.8.8.8", "8.8.4.4",
    # Cloudflare DNS
    "1.1.1.1", "1.0.0.1",
    # Quad9
    "9.9.9.9", "149.112.112.112",
    # OpenDNS
    "208.67.222.222", "208.67.220.220",
    # Yandex DNS
    "77.88.8.8", "77.88.8.1",
    # Comodo DNS
    "8.26.56.26", "8.20.247.20",
    # Localhost / loopback
    "127.0.0.1", "0.0.0.0",
})

# ── Приватные и зарезервированные подсети (RFC 1918 / RFC 6598 и др.) ─────────
# Мост по определению — публично доступный сервер. Адреса из приватных подсетей
# не могут быть мостами (кроме тестирования в LAN, но это не наш случай).
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),    # CGN (RFC 6598)
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("0.0.0.0/8"),         # "This" network
    ipaddress.ip_network("224.0.0.0/4"),       # Multicast
    ipaddress.ip_network("240.0.0.0/4"),       # Reserved
    ipaddress.ip_network("255.255.255.255/32"),
]


def _is_bogon_ip(ip_str: str) -> bool:
    """Проверяет, является ли IP приватным, зарезервированным или из чёрного списка."""
    if ip_str in _BLACKLISTED_IPS:
        return True
    try:
        addr = ipaddress.ip_address(ip_str)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return True
    except ValueError:
        pass
    return False


def _check_ip_port(ip_str: str, port_str: str) -> tuple[bool, str]:
    """Проверяет IP и порт на валидность."""
    if _is_bogon_ip(ip_str):
        return False, f"bogon/blacklisted IP: {ip_str}"
    try:
        port = int(port_str)
        if not (1 <= port <= 65535):
            return False, f"invalid port: {port}"
    except ValueError:
        return False, f"invalid port: {port_str}"
    return True, "ok"


def validate(line: str) -> tuple[bool, str]:
    """
    Возвращает (is_valid, reason).

    obfs4  — требует: IP:PORT + fingerprint + cert= + iat-mode=
    webtunnel — требует: fingerprint + url=https://...
    vanilla — требует: реальный IP:PORT (не 2001:db8) + fingerprint

    Дополнительно отклоняет:
    - IP из приватных/зарезервированных подсетей (RFC 1918 и др.)
    - IP из чёрного списка (публичные DNS: 8.8.8.8, 1.1.1.1 и т.д.)
    - Невалидные порты (0, >65535)
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return False, "empty"

    # Убираем необязательный префикс "bridge "
    bare = line[7:].strip() if line.lower().startswith("bridge ") else line
    lower = bare.lower()

    # ── fingerprint обязателен для всех типов ────────────────────────────────
    if not _FINGERPRINT_RE.search(bare):
        return False, "no fingerprint"

    # ── obfs4 ────────────────────────────────────────────────────────────────
    if lower.startswith("obfs4"):
        m_cert = _OBFS4_CERT_RE.search(bare)
        if not m_cert:
            return False, "obfs4: missing cert="
        if len(m_cert.group(1)) < 50:
            return False, "obfs4: cert= too short"
        if not _OBFS4_IAT_RE.search(bare):
            return False, "obfs4: missing iat-mode="
        m4 = _IPV4_PORT_RE.search(bare)
        m6 = _IPV6_PORT_RE.search(bare)
        if m4:
            ok, reason = _check_ip_port(m4.group(1), m4.group(2))
            if not ok:
                return False, f"obfs4: {reason}"
        elif m6:
            pass  # IPv6 — не проверяем bogon (мало актуально для мостов)
        else:
            return False, "obfs4: no address"
        return True, "ok"

    # ── webtunnel ─────────────────────────────────────────────────────────────
    if lower.startswith("webtunnel"):
        m_url = _WEBTUNNEL_URL_RE.search(bare)
        if not m_url:
            return False, "webtunnel: missing url="
        try:
            parsed = urlparse(m_url.group(1))
            if not parsed.scheme.startswith("http"):
                return False, "webtunnel: url must be http(s)"
            if not parsed.hostname:
                return False, "webtunnel: invalid hostname in url="
        except Exception:
            return False, "webtunnel: malformed url="
        return True, "ok"

    # ── vanilla / прочие ─────────────────────────────────────────────────────
    # Для vanilla запрещаем 2001:db8:: (фиктивный placeholder)
    m4 = _IPV4_PORT_RE.search(bare)
    if m4:
        ok, reason = _check_ip_port(m4.group(1), m4.group(2))
        if not ok:
            return False, reason
        return True, "ok"
    m6 = _IPV6_PORT_RE.search(bare)
    if m6 and not m6.group(1).startswith(_DOC_IPV6):
        return True, "ok"

    return False, "no valid address"
