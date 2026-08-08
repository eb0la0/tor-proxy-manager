"""
Реестр источников мостов.

Ключевая идея: **источник** (BridgeSource) — это логический поставщик данных,
у которого может быть несколько **зеркал** (mirrors) с ОДНИМ И ТЕМ ЖЕ
содержимым. Зеркала перебираются по очереди до первого успеха, разные
источники загружаются параллельно и затем объединяются.

Почему так, а не просто список URL:
- три зеркала igareck (GitLab/Codeberg/Gitea) отдают побайтово одинаковый файл;
  качать их параллельно — бессмысленный трафик. Это ОДИН источник с тремя
  зеркалами, а не три источника.
- GitHub в РФ периодически недоступен, поэтому в каждом источнике зеркала
  на не-GitHub доменах стоят ПЕРВЫМИ.

Добавление нового источника = добавление одной записи в SOURCES.
Никакой другой код менять не нужно.
"""
from dataclasses import dataclass, field

BRIDGE_TYPES = ("obfs4", "webtunnel", "vanilla")


# ── Построители raw-URL для разных хостингов ─────────────────────────────────

def gitlab_raw(project: str, path: str, branch: str = "main") -> str:
    return f"https://gitlab.com/{project}/-/raw/{branch}/{path}"


def codeberg_raw(repo: str, path: str, branch: str = "main") -> str:
    return f"https://codeberg.org/{repo}/raw/branch/{branch}/{path}"


def gitea_raw(repo: str, path: str, branch: str = "main") -> str:
    return f"https://gitea.com/{repo}/raw/branch/{branch}/{path}"


def githack_raw(repo: str, path: str, branch: str = "main") -> str:
    """
    raw.githack.com — CDN-прокси перед raw.githubusercontent.com.

    Полезен по двум причинам:
    1. Другой домен → работает там, где заблокирован сам GitHub.
    2. Отдаёт заголовок stale-if-error=604800 — если upstream (GitHub) лёг,
       CDN неделю продолжает отдавать последнюю успешную копию.

    Минус: это сторонний бесплатный сервис и данные могут отставать до ~60с
    (max-age=60). Поэтому он всегда зеркало, а не единственный endpoint.
    """
    return f"https://raw.githack.com/{repo}/{branch}/{path}"


def github_raw(repo: str, path: str, branch: str = "main") -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


@dataclass(frozen=True)
class BridgeSource:
    """
    name     — короткая метка для логов и UI.
    provider — кто на самом деле публикует данные. Два источника с одним
               provider (например «проверенный» и «полный» списки одного
               репозитория) НЕ являются независимыми: они падают вместе.
               Считать их за две независимые точки отказа — самообман.
    priority — больше = важнее. Источники сливаются по убыванию приоритета,
               и при совпадении fingerprint побеждает версия из более
               приоритетного источника.
    paths    — bridge_type → путь к файлу внутри репозитория.
               Если типа нет в словаре, источник для этого типа пропускается.
    mirrors  — упорядоченный список функций (path) → url.
               Перебираются по очереди до первого валидного ответа.
    """
    name: str
    provider: str
    priority: int
    paths: dict
    mirrors: tuple
    note: str = ""
    enabled: bool = True

    def urls_for(self, bridge_type: str) -> list:
        path = self.paths.get(bridge_type)
        if not path:
            return []
        return [build(path) for build in self.mirrors]


# ── Зеркала igareck/vpn-configs-for-russia ───────────────────────────────────
# Проверено 2026-08-08: GitLab, Codeberg и Gitea отдают побайтово идентичный
# файл (39650 B для ALL) и обновляются одним пушем в ту же минуту.
# Не-GitHub зеркала идут первыми — это главный обход блокировки GitHub в РФ.
_IGARECK_MIRRORS = (
    lambda p: gitlab_raw("igareck/vpn-configs-for-russia", p),
    lambda p: codeberg_raw("igareck/vpn-configs-for-russia", p),
    lambda p: gitea_raw("igareck/vpn-configs-for-russia", p),
    lambda p: githack_raw("igareck/vpn-configs-for-russia", p),
    lambda p: github_raw("igareck/vpn-configs-for-russia", p),
)

# Источники, живущие только на GitHub: githack первым как обход блокировки.
_SCRIPTZTEAM_V2_MIRRORS = (
    lambda p: githack_raw("scriptzteam/Tor-Bridges-Collector-v2", p),
    lambda p: github_raw("scriptzteam/Tor-Bridges-Collector-v2", p),
)

_ONIONHOP_MIRRORS = (
    lambda p: githack_raw("center2055/OnionHop-Bridges-Collector", p),
    lambda p: github_raw("center2055/OnionHop-Bridges-Collector", p),
)

# У scriptzteam-v1 файлы без расширения (bridges-obfs4, bridges-vanilla...).
# Проверено 2026-08-08: такие пути githack не проксирует, а отдаёт 302 на
# raw.githubusercontent.com. То есть при заблокированном GitHub githack здесь
# бесполезен — он лишь возвращает нас к недоступному origin. Держать его в
# списке зеркал значит обманывать себя запасом, которого нет.
_SCRIPTZTEAM_V1_MIRRORS = (
    lambda p: github_raw("scriptzteam/Tor-Bridges-Collector", p),
)


SOURCES: tuple = (
    # ── Приоритет 100: курируемый список под РФ, три не-GitHub зеркала ───────
    BridgeSource(
        name="igareck",
        provider="igareck",
        priority=100,
        paths={
            "obfs4": "TOR-BRIDGES/TOR_BRIDGES_OBFS4.txt",
            "webtunnel": "TOR-BRIDGES/TOR_BRIDGES_WEBTUNNEL.txt",
            "vanilla": "TOR-BRIDGES/TOR_BRIDGES_VANILLA.txt",
        },
        mirrors=_IGARECK_MIRRORS,
        note="Курируемый список для РФ, обновляется несколько раз в сутки",
    ),

    # ── Приоритет 80/70: предварительно проверенные наборы ───────────────────
    # *_tested.txt — мосты, прошедшие проверку у самого сборщика,
    # поэтому они ценнее полных списков.
    BridgeSource(
        name="scriptzteam-v2/tested",
        provider="scriptzteam-v2",
        priority=80,
        paths={
            "obfs4": "bridges/obfs4_tested.txt",
            "webtunnel": "bridges/webtunnel_tested.txt",
            "vanilla": "bridges/vanilla_tested.txt",
        },
        mirrors=_SCRIPTZTEAM_V2_MIRRORS,
        note="Активно обновляемый сборщик (v2), предпроверенные мосты",
    ),
    BridgeSource(
        name="onionhop/tested",
        provider="onionhop",
        priority=70,
        paths={
            "obfs4": "bridge/obfs4_tested.txt",
            "webtunnel": "bridge/webtunnel_tested.txt",
            "vanilla": "bridge/vanilla_tested.txt",
        },
        mirrors=_ONIONHOP_MIRRORS,
        note="Предпроверенные мосты, обновляется ежедневно",
    ),

    # ── Приоритет 50/40: полные (непроверенные) списки — объём про запас ─────
    BridgeSource(
        name="scriptzteam-v2/full",
        provider="scriptzteam-v2",
        priority=50,
        paths={
            "obfs4": "bridges/obfs4.txt",
            "webtunnel": "bridges/webtunnel.txt",
            "vanilla": "bridges/vanilla.txt",
        },
        mirrors=_SCRIPTZTEAM_V2_MIRRORS,
        note="Полный список того же сборщика",
    ),
    BridgeSource(
        name="onionhop/full",
        provider="onionhop",
        priority=40,
        paths={
            "obfs4": "bridge/obfs4.txt",
            "webtunnel": "bridge/webtunnel.txt",
            "vanilla": "bridge/vanilla.txt",
        },
        mirrors=_ONIONHOP_MIRRORS,
        note="Полный список OnionHop",
    ),

    # ── Приоритет 20: исторический источник приложения ───────────────────────
    # Обновляется реже остальных (на 2026-08-08 отставал на 10 дней),
    # но даёт большой объём и остаётся последним рубежом.
    BridgeSource(
        name="scriptzteam-v1",
        provider="scriptzteam-v1",
        priority=20,
        paths={
            "obfs4": "bridges-obfs4",
            "webtunnel": "bridges-webtunnel",
            "vanilla": "bridges-vanilla",
        },
        mirrors=_SCRIPTZTEAM_V1_MIRRORS,
        note="Легаси-источник, обновляется нерегулярно",
    ),
)


def sources_for(bridge_type: str) -> list:
    """Включённые источники для типа моста, по убыванию приоритета."""
    return sorted(
        (s for s in SOURCES if s.enabled and s.urls_for(bridge_type)),
        key=lambda s: -s.priority,
    )
