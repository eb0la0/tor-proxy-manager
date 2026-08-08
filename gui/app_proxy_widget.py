"""
Панель «Приложения через прокси».

Список приложений подаётся как строки-объекты: имя, способ проксирования
и одно понятное действие. Технические подробности (полный путь, метод)
доступны, но не занимают первый план.
"""
import logging
import webbrowser
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QFileDialog, QMessageBox,
)

from core.app_proxy import (
    find_proxychains_exe,
    detect_app_type,
    launch_proxied,
    PROXYCHAINS_GITHUB,
)
from core.i18n import tr
from gui import icons, theme
from gui.widgets import Card, StatusPill, label, text_button

logger = logging.getLogger(__name__)

_METHOD_KEYS = {
    "proxy-server": "app.method.proxy_server",
    "firefox-profile": "app.method.firefox",
    "proxychains": "app.method.proxychains",
    "env-proxy": "app.method.env",
}

_TYPE_METHOD = {
    "chromium": "proxy-server",
    "firefox": "firefox-profile",
    "generic": "proxychains",
}


class AppProxyWidget(Card):
    """Секция со списком приложений, запускаемых через прокси."""

    def __init__(self, config, log_fn=None, parent=None):
        super().__init__(tr("app.group_title"), parent=parent)
        self.config = config
        self._log_fn = log_fn
        self._rows: dict = {}          # path → {frame, dot, btn, name_lbl, badge}
        self._procs: dict = {}         # path → subprocess.Popen

        self._build_ui()
        self._load_apps()
        self._refresh_empty_state()

        # Таймер проверки статуса процессов (каждые 2 сек)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_processes)
        self._poll.start(2000)

    # ================================================================= build

    def _build_ui(self):
        # Третичное действие: только текст с иконкой. Пунктирная рамка на
        # пустой карточке выглядела тяжелее, чем само содержимое.
        self._btn_add = text_button(tr("app.add"), "plus", color=theme.ACCENT)
        self._btn_add.setCursor(Qt.PointingHandCursor)
        self._btn_add.setMinimumHeight(30)
        self._btn_add.clicked.connect(self._on_add)
        self.add_header_widget(self._btn_add)

        # Предупреждение о proxychains — только когда оно актуально.
        self._notice = QFrame()
        notice_lay = QHBoxLayout(self._notice)
        notice_lay.setContentsMargins(theme.SP_3, theme.SP_2, theme.SP_3, theme.SP_2)
        notice_lay.setSpacing(theme.SP_2)

        self._notice_icon = QLabel()
        self._notice_icon.setPixmap(icons.pixmap("warning", theme.ICON_SM, theme.WARN))
        notice_lay.addWidget(self._notice_icon, 0, Qt.AlignTop)

        self._pc_status = label("", "caption")
        self._pc_status.setWordWrap(True)
        notice_lay.addWidget(self._pc_status, 1)

        self._btn_download = text_button(tr("app.download_proxychains"), "download")
        self._btn_download.clicked.connect(
            lambda: webbrowser.open(PROXYCHAINS_GITHUB)
        )
        notice_lay.addWidget(self._btn_download, 0, Qt.AlignTop)
        self.add(self._notice)

        self._list_lay = QVBoxLayout()
        self._list_lay.setSpacing(theme.SP_2)
        self.add_layout(self._list_lay)

        # Пустое состояние — одна строка. Заголовок + описание + кнопка
        # раздували карточку сильнее, чем реальный список приложений.
        self._empty = label(tr("app.empty_hint"), "secondary")
        self._empty.setWordWrap(True)
        self.add(self._empty)
        self.body.addStretch()

        self._refresh_pc_status()

    # ================================================================= proxychains status

    def _refresh_pc_status(self):
        pc = find_proxychains_exe()
        if pc:
            # Всё на месте — не занимать место предупреждением.
            self._notice.setVisible(False)
        else:
            self._notice.setVisible(True)
            self._pc_status.setText(tr("app.proxychains_missing"))
            self._pc_status.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: {theme.FS_CAPTION}px;")
            self._btn_download.setVisible(True)

    def _refresh_empty_state(self):
        self._empty.setVisible(not self._rows)

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
        frame.setObjectName("row")
        row = QHBoxLayout(frame)
        row.setContentsMargins(theme.SP_3, theme.SP_2, theme.SP_2, theme.SP_2)
        row.setSpacing(theme.SP_3)

        dot_lbl = QLabel()
        dot_lbl.setFixedSize(10, 10)
        dot_lbl.setPixmap(icons.dot(theme.TEXT_MUTE, 8))
        row.addWidget(dot_lbl, 0, Qt.AlignVCenter)

        # Имя приложения крупнее, файл — подписью: так строка читается сразу.
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name_lbl = label(name)
        name_lbl.setStyleSheet(f"font-size: {theme.FS_BODY}px; font-weight: 500;")
        name_lbl.setToolTip(path)
        texts.addWidget(name_lbl)

        file_lbl = label(Path(path).name, "caption")
        file_lbl.setToolTip(path)
        texts.addWidget(file_lbl)
        row.addLayout(texts, 1)

        app_type = detect_app_type(path)
        method = _TYPE_METHOD.get(app_type, "proxychains")
        badge = StatusPill(tr(_METHOD_KEYS.get(method, "app.method.proxychains")),
                           theme.TEXT_DIM, theme.SURFACE)
        row.addWidget(badge, 0, Qt.AlignVCenter)

        btn = text_button(tr("app.launch"), "play", object_name="", color=theme.TEXT)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumWidth(132)
        btn.setFixedHeight(32)
        btn.clicked.connect(lambda checked, p=path: self._toggle(p))
        row.addWidget(btn, 0, Qt.AlignVCenter)

        btn_rm = QPushButton()
        btn_rm.setObjectName("icon_btn")
        btn_rm.setIcon(icons.icon("trash", theme.ICON_SM, theme.TEXT_MUTE))
        btn_rm.setCursor(Qt.PointingHandCursor)
        btn_rm.setFixedSize(30, 30)
        btn_rm.setToolTip(tr("app.remove"))
        btn_rm.clicked.connect(lambda checked, p=path: self._remove(p))
        row.addWidget(btn_rm, 0, Qt.AlignVCenter)

        self._list_lay.addWidget(frame)
        self._rows[path] = {
            "frame": frame,
            "dot": dot_lbl,
            "btn": btn,
            "name_lbl": name_lbl,
            "badge": badge,
            "name": name,
        }
        self._refresh_empty_state()

    def _remove(self, path: str):
        self._stop_app(path)
        info = self._rows.pop(path, None)
        if info:
            info["frame"].setParent(None)
            info["frame"].deleteLater()
        self._save_apps()
        self._refresh_empty_state()

    # ================================================================= launch / stop

    def _toggle(self, path: str):
        proc = self._procs.get(path)
        if proc and proc.poll() is None:
            self._stop_app(path)
        else:
            self._launch_app(path)

    def _launch_app(self, path: str):
        if not Path(path).exists():
            QMessageBox.warning(self, tr("alert.error_title"),
                                tr("app.file_missing", path=path))
            return

        self._refresh_pc_status()
        port = self.config.socks_port

        try:
            proc, method = launch_proxied(path, port)
            self._procs[path] = proc
            self._set_row_running(path, True)
            name = self._rows[path]["name"]
            label_txt = tr(_METHOD_KEYS.get(method, "app.method.proxychains"))
            self._log(tr("app.launched", name=name, method=label_txt, pid=proc.pid))

        except Exception as e:
            logger.error(f"Не удалось запустить {path}: {e}")
            QMessageBox.warning(self, tr("app.launch_failed_title"),
                                tr("app.launch_failed_body", err=e))

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
            self._log(tr("app.stopped", name=name))
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
        info["dot"].setPixmap(
            icons.dot(theme.OK, 8, glow=True) if running
            else icons.dot(theme.TEXT_MUTE, 8))
        info["btn"].setText(tr("app.stop") if running else tr("app.launch"))
        info["btn"].setIcon(icons.icon(
            "stop" if running else "play", theme.ICON_SM,
            theme.ERR if running else theme.TEXT))

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
            self, tr("app.choose_title"), "",
            tr("app.file_filter")
        )
        if not path:
            return
        if path in self._rows:
            QMessageBox.information(self, tr("app.duplicate_title"),
                                    tr("app.duplicate_body"))
            return
        name = Path(path).stem
        self._add_row(name, path)
        self._save_apps()

    def _log(self, msg: str):
        logger.info(msg)
        if self._log_fn:
            self._log_fn(msg)
