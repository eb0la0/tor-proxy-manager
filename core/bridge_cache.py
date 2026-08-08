"""
Кеш последнего успешного набора мостов.

Кеш — не оптимизация, а критический слой отказоустойчивости: если сегодня
все источники недоступны, приложение обязано работать на вчерашних мостах,
а не показывать «мостов нет».

Формат (версия 2):

    {
      "version": 2,
      "bridge_type": "obfs4",
      "updated_at": "2026-08-08T12:00:00",
      "bridges": [{"bridge": "obfs4 1.2.3.4:443 ...", "latency": 210.5}, ...]
    }

Версия 1 (голый список [{"bridge":..., "latency":...}]) читается как есть —
кеш пользователя после обновления приложения не теряется.

Запись атомарная (tmp + os.replace): прерывание питания или закрытие
приложения во время записи не оставит наполовину записанный файл.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from core.config import BRIDGES_FILE

logger = logging.getLogger(__name__)

CACHE_VERSION = 2

# Сколько кеш считается свежим. Совпадает по смыслу с auto_update_hours,
# но живёт отдельно: даже просроченный кеш пригоден, если сеть недоступна.
DEFAULT_TTL_HOURS = 24

# Абсолютный предел: мосты старше этого срока почти наверняка мертвы,
# и предлагать их пользователю как «рабочие» уже нечестно.
MAX_STALE_DAYS = 30


class BridgeCache:
    """Разобранное содержимое кеша. Всегда валиден: битые данные → пустой кеш."""

    def __init__(self, bridges=None, bridge_type: str = "", updated_at=None):
        self.bridges: list = bridges or []          # list[tuple[str, float]]
        self.bridge_type: str = bridge_type
        self.updated_at: datetime | None = updated_at

    # ── Свойства состояния ───────────────────────────────────────────────────

    def __bool__(self) -> bool:
        return bool(self.bridges)

    @property
    def age(self) -> timedelta | None:
        if self.updated_at is None:
            return None
        return datetime.now() - self.updated_at

    def is_fresh(self, ttl_hours: int = DEFAULT_TTL_HOURS) -> bool:
        age = self.age
        return age is not None and age < timedelta(hours=ttl_hours)

    def is_expired(self, max_days: int = MAX_STALE_DAYS) -> bool:
        """True, если кеш настолько стар, что использовать его бессмысленно."""
        age = self.age
        return age is not None and age > timedelta(days=max_days)

    def matches_type(self, bridge_type: str) -> bool:
        """
        Пустой bridge_type = кеш версии 1, тип неизвестен.
        Считаем его подходящим: лучше показать мосты, чем потерять их.
        """
        return not self.bridge_type or self.bridge_type == bridge_type

    def age_text(self) -> str:
        age = self.age
        if age is None:
            return "неизвестно"
        secs = int(age.total_seconds())
        if secs < 60:
            return "только что"
        if secs < 3600:
            return f"{secs // 60} мин назад"
        if secs < 86400:
            return f"{secs // 3600} ч назад"
        return f"{secs // 86400} дн назад"


# ── Чтение ───────────────────────────────────────────────────────────────────

def _parse_entries(raw_list) -> list:
    """Разбирает список записей, пропуская повреждённые."""
    bridges = []
    for item in raw_list:
        try:
            if isinstance(item, dict):
                line = item.get("bridge")
                latency = item.get("latency")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                line, latency = item[0], item[1]
            else:
                continue
            if not isinstance(line, str) or not line.strip():
                continue
            latency = float(latency) if latency is not None else 0.0
            bridges.append((line.strip(), latency))
        except (TypeError, ValueError):
            continue
    return bridges


def load(path: Path = BRIDGES_FILE) -> BridgeCache:
    """
    Читает кеш. Любая проблема (нет файла, битый JSON, чужая кодировка,
    неизвестная версия, мусор внутри) → пустой кеш, без исключения.
    """
    if not path.exists():
        return BridgeCache()

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Кеш, записанный старой версией в системной кодировке
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Кеш мостов нечитаем: {e}")
            return BridgeCache()
    except Exception as e:
        logger.error(f"Кеш мостов нечитаем: {e}")
        return BridgeCache()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Кеш мостов повреждён (невалидный JSON): {e}")
        return BridgeCache()

    # ── Версия 1: голый список ───────────────────────────────────────────────
    if isinstance(data, list):
        bridges = _parse_entries(data)
        logger.info(f"Загружен кеш v1: {len(bridges)} мостов (тип неизвестен)")
        return BridgeCache(bridges=bridges)

    if not isinstance(data, dict):
        logger.error("Кеш мостов повреждён (неожиданная структура)")
        return BridgeCache()

    # ── Версия из будущего ───────────────────────────────────────────────────
    # Молча интерпретировать незнакомый формат нельзя: поля могли поменять
    # смысл, и «успешно прочитанный» мусор хуже честного отсутствия кеша.
    # Файл при этом НЕ удаляем — более новая версия приложения его прочитает.
    version = data.get("version")
    if isinstance(version, int) and version > CACHE_VERSION:
        logger.warning(
            f"Кеш мостов имеет версию {version} > поддерживаемой {CACHE_VERSION} — "
            "игнорируем, файл не трогаем"
        )
        return BridgeCache()

    # ── Версия 2 ─────────────────────────────────────────────────────────────
    raw_list = data.get("bridges")
    if not isinstance(raw_list, list):
        logger.error("Кеш мостов повреждён (нет списка bridges)")
        return BridgeCache()

    bridges = _parse_entries(raw_list)

    updated_at = None
    raw_ts = data.get("updated_at")
    if isinstance(raw_ts, str):
        try:
            updated_at = datetime.fromisoformat(raw_ts)
        except ValueError:
            logger.warning("Кеш мостов: некорректный updated_at, игнорируем")

    btype = data.get("bridge_type")
    if not isinstance(btype, str):
        btype = ""

    logger.info(f"Загружен кеш: {len(bridges)} мостов, тип={btype or '?'}")
    return BridgeCache(bridges=bridges, bridge_type=btype, updated_at=updated_at)


# ── Запись ───────────────────────────────────────────────────────────────────

def save(bridges: list, bridge_type: str, path: Path = BRIDGES_FILE) -> bool:
    """
    Атомарно сохраняет набор мостов.

    ВАЖНО: пустой список не сохраняется. Неудачное обновление не должно
    затирать последний рабочий набор — иначе один недоступный источник
    лишает пользователя мостов, которые у него уже были.
    """
    if not bridges:
        logger.warning("Пустой результат — кеш мостов НЕ перезаписан")
        return False

    payload = {
        "version": CACHE_VERSION,
        "bridge_type": bridge_type,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "bridges": [
            {"bridge": b[0] if isinstance(b, (tuple, list)) else b,
             "latency": round(float(b[1]), 1) if isinstance(b, (tuple, list)) and len(b) > 1 else 0.0}
            for b in bridges
        ],
    }

    # Имя временного файла уникально для процесса: два экземпляра приложения
    # (или тест, идущий параллельно) не должны писать в один и тот же tmp
    # и подсовывать друг другу наполовину записанные данные.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        logger.info(f"Кеш мостов обновлён: {len(bridges)} шт., тип={bridge_type}")
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения кеша мостов: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False
