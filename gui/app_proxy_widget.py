"""
Виджет управления приложениями, запущенными через Tor-прокси.
Автоматически выбирает лучший метод для каждого типа приложения.
"""
import logging
import webbrowser
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QFileDialog, QMessageBox,
    QSizePolicy,
)

from core.app_proxy import (
    find_proxychains_exe,
    detect_app_type,
    launch_proxied,
    PROXYCHAINS_GITHUB,
)
from gui.styles import (
    APP_ROW_STYLE, APP_ROW_RUNNING_BTN, APP_ROW_LAUNCH_BTN, BADGE_METHOD,
    COLOR_CONNECTED, COLOR_DISCONNECTED, dot_pixmap,
)

logger = logging.getLogger(__name__)

_METHOD_LABELS = {
    "proxy-server": "встроенный прокси",
    "firefox-profile": "профиль Firefox",
    "proxychains": "proxychains",
    "env-proxy": "env-proxy",
}


_DOT_RUN = dot_pixmap(COLOR_CONNECTED, 10)
_DOT_STOP = dot_pixmap(COLOR_DISCONNECTED, 10)


class AppProxyWidget(QGroupBox):
    """Панель «Приложения через прокси»."""

    def __init__(self, config, log_fn=None, parent=None):
        super().__init__("Приложения через прокси", parent)
        self.config = config
        self._log_fn = log_fn
        self._rows: dict = {}          # path → {frame, dot, btn, name_lbl, badge}
        self._procs: dict = {}         # path → subprocess.Popen

        self._build_ui()
        self._load_apps()

        # Таймер проверки статуса процессов (каждые 2 сек)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_processes)
        self._poll.start(2000)

    # ================================================================= build

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # --- Статус proxychains ---
        self._pc_status = QLabel()
        self._pc_status.setObjectName("lbl_secondary")
        self._pc_status.setWordWrap(True)
        lay.addWidget(self._pc_status)

        self._btn_download = QPushButton("Скачать proxychains-windows")
        self._btn_download.setObjectName("btn_update")
        self._btn_download.setCursor(Qt.PointingHandCursor)
        self._btn_download.setFixedWidth(280)
        self._btn_download.clicked.connect(
            lambda: webbrowser.open(PROXYCHAINS_GITHUB)
        )
        lay.addWidget(self._btn_download)

        self._refresh_pc_status()

        # --- Список приложений ---
        self._list_lay = QVBoxLayout()
        self._list_lay.setSpacing(4)
        lay.addLayout(self._list_lay)

        # --- Кнопка добавления ---
        row_add = QHBoxLayout()
        btn_add = QPushButton("+ Добавить приложение")
        btn_add.setObjectName("btn_add_app")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setFixedWidth(220)
        btn_add.setFixedHeight(36)
        btn_add.clicked.connect(self._on_add)
        row_add.addWidget(btn_add)
        row_add.addStretch()
        lay.addLayout(row_add)

    # ================================================================= proxychains status

    def _refresh_pc_status(self):
        pc = find_proxychains_exe()
        if pc:
            self._pc_status.setText(
                f"proxychains: {Path(pc).name}\n"
                "Браузеры: авто-настройка (без proxychains)"
            )
            self._pc_status.setStyleSheet(f"color: {COLOR_CONNECTED}; font-size: 11px;")
            self._btn_download.setVisible(False)
        else:
            self._pc_status.setText(
                "Браузеры: авто-настройка прокси\n"
                "Другие приложения: proxychains не найден — "
                "положите в папку tools/ (или используется fallback)"
            )
            self._pc_status.setStyleSheet("color: #ffa502; font-size: 11px;")
            self._btn_download.setVisible(True)

    # ================================================================= app list persistence

    def _load_apps(self):
        for entry in self.config.proxied_apps:
            path = entry.get("path", "")
            name = entry.get("name", Path(path).stem if path else "?")
            if path and path not in self._rows:
                self._add_row(name, path)

    def _save_apps(self):
        apps = [
            {"name": info["name"], "path": path}
            for path, info in self._rows.items()
        ]
        self.config.set("proxied_apps", apps)

    # ================================================================= row management

    def _add_row(self, name: str, path: str):
        frame = QFrame()
        frame.setObjectName("app_row")
        frame.setStyleSheet(APP_ROW_STYLE)
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(10)

        dot_lbl = QLabel()
        dot_lbl.setFixedSize(10, 10)
        dot_lbl.setPixmap(_DOT_STOP)
        row.addWidget(dot_lbl)

        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Segoe UI", 12, QFont.DemiBold))
        name_lbl.setToolTip(path)
        name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(name_lbl, 1)

        # Бейдж с методом проксирования
        app_type = detect_app_type(path)
        method_txt = {
            "chromium": "proxy-server",
            "firefox": "profile",
            "generic": "proxychains",
        }.get(app_type, "?")
        badge = QLabel(method_txt)
        badge.setStyleSheet(BADGE_METHOD)
        row.addWidget(badge)

        btn = QPushButton("Запустить")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedWidth(110)
        btn.setFixedHeight(32)
        btn.setStyleSheet(APP_ROW_LAUNCH_BTN)
        btn.clicked.connect(lambda checked, p=path: self._toggle(p))
        row.addWidget(btn)

        btn_rm = QPushButton("\u00d7")       # x
        btn_rm.setCursor(Qt.PointingHandCursor)
        btn_rm.setFixedWidth(30)
        btn_rm.setFixedHeight(30)
        btn_rm.setStyleSheet(
            "QPushButton { background: transparent; color: #6a6a8a;"
            "  font-size: 18px; border: none; border-radius: 6px; }"
            "QPushButton:hover { color: #ff4757; background: rgba(255,71,87,0.1); }"
        )
        btn_rm.clicked.connect(lambda checked, p=path: self._remove(p))
        row.addWidget(btn_rm)

        self._list_lay.addWidget(frame)
        self._rows[path] = {
            "frame": frame,
            "dot": dot_lbl,
            "btn": btn,
            "name_lbl": name_lbl,
            "badge": badge,
            "name": name,
        }

    def _remove(self, path: str):
        self._stop_app(path)
        info = self._rows.pop(path, None)
        if info:
            info["frame"].setParent(None)
            info["frame"].deleteLater()
        self._save_apps()

    # ================================================================= launch / stop

    def _toggle(self, path: str):
        proc = self._procs.get(path)
        if proc and proc.poll() is None:
            self._stop_app(path)
        else:
            self._launch_app(path)

    def _launch_app(self, path: str):
        if not Path(path).exists():
            QMessageBox.warning(
                self, "Ошибка",
                f"Файл не найден:\n{path}"
            )
            return

        self._refresh_pc_status()
        port = self.config.socks_port

        try:
            proc, method = launch_proxied(path, port)
            self._procs[path] = proc
            self._set_row_running(path, True)
            name = self._rows[path]["name"]
            label = _METHOD_LABELS.get(method, method)
            self._log(f"Запущено: {name} [{label}] (PID {proc.pid})")

        except Exception as e:
            logger.error(f"Не удалось запустить {path}: {e}")
            QMessageBox.warning(
                self, "Ошибка запуска",
                f"Не удалось запустить:\n{e}"
            )

    def _stop_app(self, path: str):
        proc = self._procs.pop(path, None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
            except Exception:
                pass
            name = self._rows.get(path, {}).get("name", path)
            self._log(f"Остановлено: {name}")
        self._set_row_running(path, False)

    def stop_all(self):
        """Остановить все запущенные приложения."""
        for path in list(self._procs):
            self._stop_app(path)

    # ================================================================= UI update

    def _set_row_running(self, path: str, running: bool):
        info = self._rows.get(path)
        if not info:
            return
        info["dot"].setPixmap(_DOT_RUN if running else _DOT_STOP)
        info["btn"].setText("Остановить" if running else "Запустить")
        if running:
            info["btn"].setStyleSheet(APP_ROW_RUNNING_BTN)
        else:
            info["btn"].setStyleSheet(APP_ROW_LAUNCH_BTN)

    def _poll_processes(self):
        """Обновить статус завершившихся процессов."""
        for path in list(self._procs):
            proc = self._procs[path]
            if proc.poll() is not None:
                self._procs.pop(path)
                self._set_row_running(path, False)

    # ================================================================= helpers

    def _on_add(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите приложение", "",
            "Приложения (*.exe);;Все файлы (*)"
        )
        if not path:
            return
        if path in self._rows:
            QMessageBox.information(self, "Дубликат", "Это приложение уже добавлено.")
            return
        name = Path(path).stem
        self._add_row(name, path)
        self._save_apps()

    def _log(self, msg: str):
        logger.info(msg)
        if self._log_fn:
            self._log_fn(msg)
