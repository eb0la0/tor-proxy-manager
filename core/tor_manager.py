import os
import re
import socket
import struct
import subprocess
import time
import logging
from pathlib import Path
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from core.config import TOR_LOG_FILE, DATA_DIR, WATCHDOG_LOG_FILE, ERRORS_LOG_FILE, LOGS_DIR

logger = logging.getLogger(__name__)

# ── Выделенные логгеры для watchdog и ошибок ─────────────────────────────
_LOG_FMT = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s",
                              datefmt="%Y-%m-%d %H:%M:%S")


def _make_file_logger(name: str, filepath: Path) -> logging.Logger:
    """Создаёт логгер с файловым хэндлером (без дублирования в корневой)."""
    lg = logging.getLogger(name)
    if not lg.handlers:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(filepath), encoding="utf-8")
        fh.setFormatter(_LOG_FMT)
        lg.addHandler(fh)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
    return lg


wdlog = _make_file_logger("tor_watchdog", WATCHDOG_LOG_FILE)
errlog = _make_file_logger("tor_errors", ERRORS_LOG_FILE)

_BOOTSTRAP_RE = re.compile(r"Bootstrapped\s+(\d+)%[:\s]+(.+)", re.IGNORECASE)
_CREATE_NO_WINDOW = 0x08000000


class _TorMonitorThread(QThread):
    """Парсит stdout tor.exe в реальном времени — вычитывает bootstrap % для UI."""
    bootstrap_progress = pyqtSignal(int, str)
    log_line = pyqtSignal(str)
    process_ended = pyqtSignal(int)

    def __init__(self, process):
        super().__init__()
        self.process = process
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            for raw in iter(self.process.stdout.readline, b""):
                if self._stop:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self.log_line.emit(line)
                m = _BOOTSTRAP_RE.search(line)
                if m:
                    self.bootstrap_progress.emit(int(m.group(1)), m.group(2).strip())
        except Exception as e:
            logger.debug(f"Ошибка монитора tor: {e}")

        rc = self.process.poll()
        self.process_ended.emit(rc if rc is not None else -1)


class _BootstrapWatchdog(QThread):
    """
    Tor-level validator: отслеживает прогресс bootstrap после старта.

    Логика:
    - Bootstrap ≥ 10% означает что Tor успешно прошёл через мост (bridge connected).
    - Если за STALL_SECONDS секунд прогресс не достиг 10% → мосты не работают.
    - Сигнал `stalled` — триггер для автоматического обновления мостов.

    Почему 10%:
    - 1-2%  = PT соединение установлено (lyrebird запущен)
    - 10%   = Tor успешно прошёл через мост и достиг relay
    - 14%+  = handshake с relay (мост точно работает)
    """
    stalled = pyqtSignal()
    STALL_SECONDS = 90   # ждём 90 секунд без прогресса
    POLL_INTERVAL = 5    # проверяем каждые 5 секунд

    def __init__(self):
        super().__init__()
        self._max_pct = 0
        self._last_progress_t = time.monotonic()
        self._stopped = False

    def update(self, pct: int):
        """Вызывается при каждом bootstrap-событии."""
        if pct > self._max_pct:
            self._max_pct = pct
            self._last_progress_t = time.monotonic()

    def stop(self):
        self._stopped = True

    def run(self):
        while not self._stopped:
            for _ in range(self.POLL_INTERVAL * 10):  # sleep 5s in 0.1s chunks
                if self._stopped:
                    return
                time.sleep(0.1)

            if self._stopped:
                return

            # Если достигли хотя бы 10% — мост работает, сторож больше не нужен
            if self._max_pct >= 10:
                return

            elapsed = time.monotonic() - self._last_progress_t
            if elapsed >= self.STALL_SECONDS:
                logger.warning(
                    f"Bootstrap завис на {self._max_pct}% после {elapsed:.0f}с — "
                    "мосты не работают"
                )
                self.stalled.emit()
                return


class _ConnectivityWatchdog(QThread):
    """
    Адаптивный watchdog: следит за реальной работоспособностью SOCKS-прокси.

    Ключевые отличия от простого «проверить TCP раз в 30 сек»:
    1. Интервал 15 сек — быстрое обнаружение сбоя
    2. Трёхфазная диагностика: нет интернета / Tor грузится / Tor завис
    3. Bootstrap-проверка через ControlPort (GETINFO status/bootstrap-phase)
    4. NEWNYM cooldown — не чаще 1 раза в 15 сек
    5. Счётчик неудач для ротации мостов (3+ подряд → bridge_rotate)

    Алгоритм при SOCKS fail:
    ┌─ нет интернета (TCP 8.8.8.8:53 fail) → ждём, не трогаем Tor
    ├─ bootstrap < 100 → ждём, Tor ещё грузится
    ├─ NEWNYM cooldown → ждём, слишком рано для повторной попытки
    ├─ NEWNYM → ждём 8 сек → проверка → recovered? → продолжаем
    └─ NEWNYM не помог → tor_stale (MainWindow перезапускает)
    """
    tor_stale = pyqtSignal()          # NEWNYM не помог — нужен restart
    recovered = pyqtSignal()          # NEWNYM помог — соединение восстановлено
    bridge_rotate = pyqtSignal()      # 3+ неудач подряд — нужна ротация моста

    PROBE_INTERVAL = 15               # секунд между проверками
    RETRY_DELAY = 5                   # пауза перед повторной проверкой
    NEWNYM_WAIT = 8                   # ожидание после NEWNYM
    NEWNYM_COOLDOWN = 15              # минимум секунд между NEWNYM
    BRIDGE_FAIL_THRESHOLD = 3         # неудач подряд до ротации моста

    def __init__(self, socks_port: int, control_port: int):
        super().__init__()
        self._socks_port = socks_port
        self._control_port = control_port
        self._stopped = False
        self._last_newnym_t = 0.0          # monotonic-время последнего NEWNYM
        self._consecutive_failures = 0     # счётчик неудач подряд

    def stop(self):
        self._stopped = True

    # ── Основной цикл ────────────────────────────────────────────────────

    def run(self):
        wdlog.info("Watchdog запущен (интервал=%ds, порт=%d)",
                    self.PROBE_INTERVAL, self._socks_port)

        while not self._stopped:
            self._sleep_check(self.PROBE_INTERVAL)
            if self._stopped:
                return

            # ── Проба 1 ─────────────────────────────────────────────────
            if self._socks_probe():
                if self._consecutive_failures > 0:
                    wdlog.info("SOCKS OK (после %d неудач подряд)",
                               self._consecutive_failures)
                self._consecutive_failures = 0
                continue

            self._consecutive_failures += 1
            wdlog.warning("SOCKS fail #%d", self._consecutive_failures)

            # ── Проба 2 (через 5 сек) ───────────────────────────────────
            self._sleep_check(self.RETRY_DELAY)
            if self._stopped:
                return

            if self._socks_probe():
                wdlog.info("SOCKS восстановился сам (transient fail)")
                self._consecutive_failures = 0
                continue

            # ── Диагностика: почему SOCKS не работает? ───────────────────

            # (A) Нет интернета?
            if not self._internet_check():
                wdlog.info("Интернет недоступен — ждём следующий цикл")
                continue

            # (B) Tor ещё грузится? (bootstrap < 100)
            bootstrap_pct = self._get_bootstrap_via_control()
            if bootstrap_pct is not None and bootstrap_pct < 100:
                wdlog.info("Tor bootstrap %d%% — ждём", bootstrap_pct)
                continue

            # (C) Tor завис: bootstrap=100, интернет есть, SOCKS мёртв

            # Проверяем порог ротации мостов
            if self._consecutive_failures >= self.BRIDGE_FAIL_THRESHOLD:
                wdlog.warning("Неудач подряд: %d >= %d → ротация моста",
                               self._consecutive_failures, self.BRIDGE_FAIL_THRESHOLD)
                errlog.error("Bridge rotation triggered: %d consecutive SOCKS failures",
                              self._consecutive_failures)
                self._consecutive_failures = 0
                self.bridge_rotate.emit()
                return

            # Проверяем NEWNYM cooldown
            now = time.monotonic()
            since_last = now - self._last_newnym_t
            if since_last < self.NEWNYM_COOLDOWN:
                wait = self.NEWNYM_COOLDOWN - since_last
                wdlog.info("NEWNYM cooldown: ждём ещё %.0f сек", wait)
                self._sleep_check(wait)
                if self._stopped:
                    return
                # После cooldown — пробуем ещё раз перед NEWNYM
                if self._socks_probe():
                    wdlog.info("SOCKS восстановился во время cooldown")
                    self._consecutive_failures = 0
                    continue

            # SIGNAL NEWNYM
            wdlog.warning("Интернет есть, bootstrap=%s, SOCKS мёртв → NEWNYM",
                           bootstrap_pct if bootstrap_pct is not None else "?")
            if self._send_newnym():
                self._sleep_check(self.NEWNYM_WAIT)
                if self._stopped:
                    return

                if self._socks_probe():
                    wdlog.info("NEWNYM помог — соединение восстановлено")
                    self._consecutive_failures = 0
                    self.recovered.emit()
                    continue

            # NEWNYM не помог
            wdlog.warning("NEWNYM не помог → tor_stale")
            errlog.error("Tor stale: SOCKS dead after NEWNYM, restart needed")
            self.tor_stale.emit()
            return

    # ── Утилиты ──────────────────────────────────────────────────────────

    def _sleep_check(self, seconds: float):
        """Sleep с возможностью прерывания (шаг 0.1 сек)."""
        for _ in range(int(seconds * 10)):
            if self._stopped:
                return
            time.sleep(0.1)

    def _socks_probe(self) -> bool:
        """Полный SOCKS5 CONNECT через Tor — проверяет реальную маршрутизацию, не просто открытый порт."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect(("127.0.0.1", self._socks_port))

                s.sendall(b"\x05\x01\x00")
                resp = s.recv(2)
                if resp != b"\x05\x00":
                    return False

                s.sendall(b"\x05\x01\x00\x01"
                          + socket.inet_aton("1.1.1.1")
                          + struct.pack("!H", 443))
                resp = s.recv(10)
                return len(resp) >= 2 and resp[1] == 0x00
        except Exception:
            return False

    def _internet_check(self) -> bool:
        """TCP-проба к 8.8.8.8:53 напрямую (без SOCKS) — отличает «нет интернета» от «Tor завис»."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect(("8.8.8.8", 53))
            return True
        except Exception:
            return False

    def _get_bootstrap_via_control(self) -> int | None:
        """Запрашивает bootstrap % через ControlPort (cookie auth) — отличает «ещё грузится» от «завис»."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect(("127.0.0.1", self._control_port))
                s.recv(1024)

                cookie_path = DATA_DIR / "control_auth_cookie"
                if not cookie_path.exists():
                    return None
                cookie = cookie_path.read_bytes().hex()

                s.sendall(f"AUTHENTICATE {cookie}\r\n".encode())
                auth_resp = s.recv(1024).decode("utf-8", errors="replace")
                if "250 OK" not in auth_resp:
                    return None

                s.sendall(b"GETINFO status/bootstrap-phase\r\n")
                info_resp = s.recv(2048).decode("utf-8", errors="replace")
                s.sendall(b"QUIT\r\n")

            m = re.search(r"PROGRESS=(\d+)", info_resp)
            return int(m.group(1)) if m else None
        except Exception:
            return None

    def _send_newnym(self) -> bool:
        """SIGNAL NEWNYM через ControlPort — пересоздаёт circuits без перезапуска процесса."""
        try:
            cookie_path = DATA_DIR / "control_auth_cookie"
            if not cookie_path.exists():
                wdlog.warning("control_auth_cookie не найден")
                return False

            cookie = cookie_path.read_bytes().hex()

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect(("127.0.0.1", self._control_port))
                s.recv(1024)

                s.sendall(f"AUTHENTICATE {cookie}\r\n".encode())
                auth_resp = s.recv(1024).decode("utf-8", errors="replace")
                if "250 OK" not in auth_resp:
                    wdlog.warning("ControlPort auth failed: %s", auth_resp.strip())
                    errlog.error("ControlPort auth failed: %s", auth_resp.strip())
                    return False

                s.sendall(b"SIGNAL NEWNYM\r\n")
                newnym_resp = s.recv(1024).decode("utf-8", errors="replace")
                s.sendall(b"QUIT\r\n")

            if "250 OK" in newnym_resp:
                self._last_newnym_t = time.monotonic()
                wdlog.info("SIGNAL NEWNYM отправлен успешно")
                return True
            else:
                wdlog.warning("NEWNYM failed: %s", newnym_resp.strip())
                errlog.error("NEWNYM command rejected: %s", newnym_resp.strip())
                return False
        except Exception as e:
            wdlog.warning("Ошибка отправки NEWNYM: %s", e)
            errlog.error("NEWNYM exception: %s", e)
            return False


def _find_pids_on_port(port: int) -> list[int]:
    """Возвращает PID-ы процессов, слушающих на данном TCP-порту."""
    pids = []
    try:
        flags = _CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=5,
            creationflags=flags,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    try:
                        pids.append(int(parts[-1]))
                    except ValueError:
                        pass
    except Exception as e:
        logger.debug(f"netstat failed: {e}")
    return pids


def _kill_pid(pid: int):
    """Принудительно завершает процесс по PID."""
    try:
        flags = _CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, timeout=5,
            creationflags=flags,
        )
        logger.info(f"Убит осиротевший процесс PID={pid}")
    except Exception as e:
        logger.warning(f"Не удалось убить PID={pid}: {e}")


class TorManager(QObject):
    """Управляет процессом tor.exe."""
    status_changed = pyqtSignal(str)         # 'stopped' | 'starting' | 'running' | 'error'
    bootstrap_progress = pyqtSignal(int, str)
    bootstrap_stalled = pyqtSignal()         # мосты не работают — нужно обновить
    tor_stale = pyqtSignal()                 # SOCKS мёртв, NEWNYM не помог — рестарт
    tor_recovered = pyqtSignal()             # NEWNYM помог — соединение восстановлено
    bridge_rotate = pyqtSignal()             # 3+ неудач подряд — ротация моста
    log_message = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._process = None
        self._monitor: _TorMonitorThread | None = None
        self._watchdog: _BootstrapWatchdog | None = None
        self._conn_watchdog: _ConnectivityWatchdog | None = None
        self._status = "stopped"
        self._bootstrap_pct = 0
        self._stopping = False

    # ── публичное API ────────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        return self._status

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, torrc_path: str):
        if self.is_running():
            logger.warning("Tor уже запущен")
            return

        tor_exe = self.config.tor_exe
        if not tor_exe or not Path(tor_exe).exists():
            self._emit_error(
                f"tor.exe не найден: {tor_exe!r}\n"
                "Укажите путь в Настройках или положите папку tor/ рядом с программой."
            )
            return

        port = self.config.socks_port
        if not self._is_port_free(port):
            # Порт занят — убиваем осиротевший процесс автоматически
            logger.warning(f"Порт {port} занят, ищу осиротевший процесс...")
            for pid in _find_pids_on_port(port):
                _kill_pid(pid)
            for _ in range(30):
                if self._is_port_free(port):
                    break
                time.sleep(0.1)

            if not self._is_port_free(port):
                self._emit_error(
                    f"Порт {port} всё ещё занят.\n"
                    "Перезапустите приложение или измените порт в Настройках."
                )
                return

        try:
            self._stopping = False
            self._bootstrap_pct = 0
            self._set_status("starting")

            # Очистка лог-файла при каждом запуске (Tor не ротирует логи)
            try:
                TOR_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                TOR_LOG_FILE.write_text("", encoding="utf-8")
            except Exception:
                pass

            cmd = [tor_exe, "-f", torrc_path]
            logger.info(f"Запуск Tor: {' '.join(cmd)}")

            flags = _CREATE_NO_WINDOW if os.name == "nt" else 0
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )

            # Монитор stdout
            self._monitor = _TorMonitorThread(self._process)
            self._monitor.bootstrap_progress.connect(self._on_bootstrap)
            self._monitor.log_line.connect(self.log_message)
            self._monitor.process_ended.connect(self._on_ended)
            self._monitor.start()

            # Сторож bootstrap: если за 90 секунд не достигнем 10% → мосты мёртвые
            self._watchdog = _BootstrapWatchdog()
            self._watchdog.stalled.connect(self._on_watchdog_stalled)
            self._watchdog.start()

        except Exception as e:
            self._emit_error(f"Не удалось запустить Tor: {e}")

    def stop(self):
        if self._stopping:
            return
        self._stopping = True

        # Сначала останавливаем сторожей — чтобы не стрельнули во время shutdown
        self._stop_conn_watchdog()

        if self._watchdog:
            self._watchdog.stop()
            if self._watchdog.isRunning():
                self._watchdog.wait(2000)
            self._watchdog = None

        if self._monitor:
            self._monitor.stop()

        proc = self._process
        if proc is not None and proc.poll() is None:
            logger.info("Остановка Tor...")
            try:
                proc.terminate()
                for _ in range(50):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                else:
                    logger.warning("Tor не завершился за 5 сек, принудительное завершение")
                    proc.kill()
                    for _ in range(30):
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка при остановке Tor: {e}")

        if self._monitor and self._monitor.isRunning():
            self._monitor.wait(3000)

        self._process = None
        self._monitor = None
        self._bootstrap_pct = 0
        self._stopping = False
        self._set_status("stopped")

    def restart(self, torrc_path: str):
        self.stop()
        time.sleep(1.0)
        self.start(torrc_path)

    def get_bootstrap_progress(self) -> int:
        return self._bootstrap_pct

    # ── приватные методы ─────────────────────────────────────────────────────

    def _set_status(self, s: str):
        self._status = s
        self.status_changed.emit(s)

    def _emit_error(self, msg: str):
        logger.error(msg)
        self.error.emit(msg)
        self._set_status("stopped")

    def _on_bootstrap(self, pct: int, msg: str):
        self._bootstrap_pct = pct
        self.bootstrap_progress.emit(pct, msg)
        if self._watchdog:
            self._watchdog.update(pct)
        # 100% bootstrap = Tor готов к работе, запускаем мониторинг связности
        if pct >= 100 and self._status != "running":
            self._set_status("running")
            self._start_conn_watchdog()

    def _start_conn_watchdog(self):
        """Запускает connectivity watchdog после успешного bootstrap."""
        self._stop_conn_watchdog()
        port = self.config.socks_port
        self._conn_watchdog = _ConnectivityWatchdog(port, port + 1)
        self._conn_watchdog.tor_stale.connect(self._on_tor_stale)
        self._conn_watchdog.recovered.connect(self._on_tor_recovered)
        self._conn_watchdog.bridge_rotate.connect(self._on_bridge_rotate)
        self._conn_watchdog.start()
        logger.info("Connectivity watchdog запущен")

    def _stop_conn_watchdog(self):
        if self._conn_watchdog:
            self._conn_watchdog.stop()
            if self._conn_watchdog.isRunning():
                self._conn_watchdog.wait(3000)
            self._conn_watchdog = None

    def _on_tor_stale(self):
        """SOCKS мёртв и NEWNYM не помог — нужен полный рестарт."""
        if self._stopping or self._status == "stopped":
            return
        logger.warning("Connectivity watchdog: Tor stale — нужен рестарт")
        self.tor_stale.emit()

    def _on_tor_recovered(self):
        """NEWNYM помог — соединение восстановлено."""
        if self._stopping or self._status == "stopped":
            return
        logger.info("Connectivity watchdog: соединение восстановлено через NEWNYM")
        self.tor_recovered.emit()

    def _on_bridge_rotate(self):
        """3+ неудач подряд — нужна ротация моста."""
        if self._stopping or self._status == "stopped":
            return
        logger.warning("Connectivity watchdog: ротация моста")
        self.bridge_rotate.emit()

    def _on_watchdog_stalled(self):
        """Сторож сработал: мосты не дали bootstrap ≥ 10% за 90 секунд."""
        if self._stopping or self._status == "stopped":
            return
        logger.warning("Watchdog: мосты не работают — сигнал bootstrap_stalled")
        self.bootstrap_stalled.emit()

    def _on_ended(self, code: int):
        """Вызывается из monitor-потока через сигнал — stop() уже мог обнулить _process."""
        logger.info(f"Процесс Tor завершился с кодом {code}")
        self._process = None
        self._monitor = None
        self._bootstrap_pct = 0
        if self._status != "stopped":
            self._set_status("stopped")

    @staticmethod
    def _is_port_free(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
