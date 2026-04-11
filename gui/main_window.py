import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QTextEdit,
    QComboBox, QGroupBox, QApplication, QFrame,
    QSizePolicy, QScrollArea, QMessageBox,
)

from core.config import Config, BRIDGES_FILE, TORRC_FILE
from core.i18n import tr
from core.bridge_fetcher import BridgeFetcherThread
from core.bridge_tester import BridgeTesterThread
from core.torrc_builder import build_and_save_torrc
from core.tor_manager import TorManager
from gui.styles import (
    DARK_THEME, BTN_CONNECT_STYLE, BTN_DISCONNECT_STYLE, BTN_CONNECTING_STYLE,
    CARD_DEFAULT, CARD_CONNECTED, CARD_CONNECTING,
    BADGE_SOCKS,
    COLOR_CONNECTED, COLOR_DISCONNECTED, COLOR_CONNECTING,
    dot_pixmap,
)

logger = logging.getLogger(__name__)

APP_VERSION = "1.0"

_ACCENT = "#7c5cbf"
_ACCENT_LT = "#9370db"


class MainWindow(QMainWindow):

    def __init__(self, config: Config, tor_manager: TorManager):
        super().__init__()
        self.config = config
        self.tor_manager = tor_manager

        self._bridges: list = []
        self._start_time: float | None = None
        self._fetch_thread: BridgeFetcherThread | None = None
        self._test_thread: BridgeTesterThread | None = None

        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        self._connect_timeout = QTimer(self)
        self._connect_timeout.setSingleShot(True)
        self._connect_timeout.timeout.connect(self._on_connect_timeout)

        self._auto_update_timer = QTimer(self)
        self._auto_update_timer.timeout.connect(self._check_auto_update)
        self._auto_update_timer.start(60 * 60 * 1000)

        self._next_update_timer = QTimer(self)
        self._next_update_timer.timeout.connect(self._refresh_time_labels)
        self._next_update_timer.start(60 * 1000)

        self._user_requested_update: bool = False
        self._pending_connect_after_update: bool = False
        self._stall_retries: int = 0
        self._no_bridges_warned: bool = False

        self._build_ui()
        self._connect_signals()
        self._load_bridges_cache()
        self._refresh_time_labels()
        QTimer.singleShot(800, self._check_auto_update)


    # ================================================================= UI build

    def _build_ui(self):
        self.setWindowTitle("TorProxy Manager")
        self.setMinimumWidth(580)
        self.setMinimumHeight(660)
        self.setStyleSheet(DARK_THEME)

        main_tab = QWidget()
        self.setCentralWidget(main_tab)
        self._build_main_tab(main_tab)

    def _build_main_tab(self, parent: QWidget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        root.addWidget(self._make_header())
        root.addSpacing(2)
        root.addWidget(self._make_status_card())
        root.addSpacing(2)
        root.addWidget(self._make_connect_btn())
        root.addSpacing(6)
        root.addWidget(self._make_app_proxy_block())
        root.addSpacing(2)
        root.addWidget(self._make_bridges_block())
        root.addSpacing(2)
        root.addWidget(self._make_log_block())
        root.addSpacing(4)
        root.addWidget(self._make_settings_row())
        root.addStretch()

        tab_lay = QVBoxLayout(parent)
        tab_lay.setContentsMargins(0, 0, 0, 0)
        tab_lay.addWidget(scroll)

    # ---- Header ----
    def _make_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setStyleSheet(CARD_DEFAULT)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(16, 12, 16, 12)

        icon_lbl = QLabel()
        from gui.tray_icon import create_app_icon
        icon_lbl.setPixmap(create_app_icon().pixmap(32, 32))
        lay.addWidget(icon_lbl)
        lay.addSpacing(8)

        title = QLabel("TorProxy Manager")
        title.setObjectName("lbl_title")
        title.setFont(QFont("Segoe UI", 17, QFont.Bold))
        lay.addWidget(title)
        lay.addStretch()

        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("lbl_version")
        lay.addWidget(ver)
        return frame

    # ---- Status card ----
    def _make_status_card(self) -> QFrame:
        self._status_card = QFrame()
        self._status_card.setObjectName("card")
        self._status_card.setStyleSheet(CARD_DEFAULT)
        lay = QVBoxLayout(self._status_card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self._dot = QLabel()
        self._dot.setFixedSize(14, 14)
        self._dot.setPixmap(dot_pixmap(COLOR_DISCONNECTED, 14))
        top.addWidget(self._dot)
        top.addSpacing(6)

        self._status_lbl = QLabel(tr("status.disconnected"))
        self._status_lbl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        top.addWidget(self._status_lbl)
        top.addStretch()

        self._uptime_lbl = QLabel("")
        self._uptime_lbl.setObjectName("lbl_secondary")
        self._uptime_lbl.setFont(QFont("JetBrains Mono", 11))
        top.addWidget(self._uptime_lbl)
        lay.addLayout(top)

        bottom = QHBoxLayout()
        badge = QLabel("SOCKS5")
        badge.setStyleSheet(BADGE_SOCKS)
        bottom.addWidget(badge)
        bottom.addSpacing(6)

        self._proxy_lbl = QLabel(f"127.0.0.1:{self.config.socks_port}")
        self._proxy_lbl.setFont(QFont("JetBrains Mono", 12))
        self._proxy_lbl.setStyleSheet("color:#6a6a8a;")
        bottom.addWidget(self._proxy_lbl)
        bottom.addStretch()

        btn_copy = QPushButton(tr("btn.copy"))
        btn_copy.setFixedHeight(30)
        btn_copy.setMinimumWidth(110)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.clicked.connect(self._copy_proxy)
        bottom.addWidget(btn_copy)
        lay.addLayout(bottom)

        self._boot_bar = QProgressBar()
        self._boot_bar.setRange(0, 100)
        self._boot_bar.setFixedHeight(4)
        self._boot_bar.setVisible(False)
        lay.addWidget(self._boot_bar)

        self._boot_lbl = QLabel("")
        self._boot_lbl.setObjectName("lbl_secondary")
        self._boot_lbl.setVisible(False)
        lay.addWidget(self._boot_lbl)

        return self._status_card

    # ---- Connect button ----
    def _make_connect_btn(self) -> QPushButton:
        self._btn_connect = QPushButton(tr("btn.connect"))
        self._btn_connect.setStyleSheet(BTN_CONNECT_STYLE)
        self._btn_connect.setCursor(Qt.PointingHandCursor)
        self._btn_connect.setFixedHeight(46)
        self._btn_connect.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn_connect.clicked.connect(self._toggle_connection)
        return self._btn_connect

    # ---- App proxy ----
    def _make_app_proxy_block(self):
        from gui.app_proxy_widget import AppProxyWidget
        self._app_proxy = AppProxyWidget(self.config, log_fn=self._log)
        return self._app_proxy

    # ---- Bridges block ----
    def _make_bridges_block(self) -> QGroupBox:
        group = QGroupBox(tr("bridge.group_title"))
        lay = QVBoxLayout(group)
        lay.setSpacing(8)

        row1 = QHBoxLayout()
        type_lbl = QLabel(tr("bridge.type_label"))
        type_lbl.setStyleSheet("color: #6a6a8a; font-weight: 600;")
        row1.addWidget(type_lbl)

        self._bridge_type = QComboBox()
        self._bridge_type.addItems(["obfs4", "vanilla", "webtunnel"])
        idx = self._bridge_type.findText(self.config.bridge_type)
        self._bridge_type.setCurrentIndex(idx if idx >= 0 else 0)
        self._bridge_type.setFixedWidth(120)
        self._bridge_type.currentTextChanged.connect(self._on_bridge_type_changed)
        row1.addWidget(self._bridge_type)
        row1.addSpacing(8)

        self._btn_update = QPushButton(tr("btn.update_bridges"))
        self._btn_update.setObjectName("btn_update")
        self._btn_update.setCursor(Qt.PointingHandCursor)
        self._btn_update.setMinimumWidth(110)
        self._btn_update.clicked.connect(self._start_bridge_update)
        row1.addWidget(self._btn_update)
        row1.addStretch()

        self._bridges_cnt = QLabel("0")
        self._bridges_cnt.setStyleSheet(
            f"color: {_ACCENT_LT}; font-weight: 700; font-size: 14px;"
            f"background: rgba(124, 92, 191, 0.1);"
            "border-radius: 6px; padding: 2px 10px;"
        )
        self._bridges_cnt.setToolTip(tr("bridge.count_tooltip"))
        row1.addWidget(self._bridges_cnt)
        lay.addLayout(row1)

        self._update_bar = QProgressBar()
        self._update_bar.setRange(0, 100)
        self._update_bar.setFixedHeight(4)
        self._update_bar.setVisible(False)
        lay.addWidget(self._update_bar)

        row2 = QHBoxLayout()
        self._last_update_lbl = QLabel(tr("bridge.last_update"))
        self._last_update_lbl.setObjectName("lbl_secondary")
        row2.addWidget(self._last_update_lbl)
        row2.addStretch()
        self._next_update_lbl = QLabel("")
        self._next_update_lbl.setObjectName("lbl_secondary")
        row2.addWidget(self._next_update_lbl)
        lay.addLayout(row2)

        self._bridge_log = QTextEdit()
        self._bridge_log.setReadOnly(True)
        self._bridge_log.setMaximumHeight(55)
        self._bridge_log.setPlaceholderText(tr("bridge.log_placeholder"))
        lay.addWidget(self._bridge_log)

        return group

    # ---- Log ----
    def _make_log_block(self) -> QGroupBox:
        group = QGroupBox(tr("log.group_title"))
        lay = QVBoxLayout(group)
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumHeight(90)
        self._log_view.setPlaceholderText(tr("log.placeholder"))
        lay.addWidget(self._log_view)
        return group

    # ---- Settings row ----
    def _make_settings_row(self) -> QFrame:
        frame = QFrame()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        btn = QPushButton(tr("btn.settings"))
        btn.setObjectName("btn_settings")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(34)
        btn.clicked.connect(self._open_settings)
        lay.addWidget(btn)

        self._settings_hint = QLabel("")
        self._settings_hint.setObjectName("lbl_secondary")
        self._settings_hint.setWordWrap(True)
        lay.addWidget(self._settings_hint, 1)

        self._update_settings_hint()
        return frame

    # ================================================================= signals

    def _connect_signals(self):
        self.tor_manager.status_changed.connect(self._on_tor_status)
        self.tor_manager.bootstrap_progress.connect(self._on_bootstrap)
        self.tor_manager.bootstrap_stalled.connect(self._on_bootstrap_stalled)
        self.tor_manager.tor_stale.connect(self._on_tor_stale)
        self.tor_manager.tor_recovered.connect(self._on_tor_recovered)
        self.tor_manager.bridge_rotate.connect(self._on_bridge_rotate)
        self.tor_manager.log_message.connect(self._on_tor_log)
        self.tor_manager.error.connect(self._on_tor_error)

    # ================================================================= actions

    def _toggle_connection(self):
        if self.tor_manager.is_running():
            self._disconnect()
        else:
            self._connect()

    _MIN_BRIDGES = 3  # минимум мостов для надёжного подключения

    def _connect(self):
        self._no_bridges_warned = False  # сброс при каждой попытке подключения
        if not self.config.tor_exe or not Path(self.config.tor_exe).exists():
            self._alert(tr("alert.tor_not_found_title"), tr("alert.tor_not_found_body"))
            return

        # Гарантия рабочего набора: если мостов < 3, сначала обновляем
        if len(self._bridges) < self._MIN_BRIDGES:
            self._log(tr("msg.few_bridges", n=len(self._bridges), min=self._MIN_BRIDGES))
            self._pending_connect_after_update = True
            self._user_requested_update = True
            self._start_bridge_update(background=False)
            return

        self._do_connect()

    def _do_connect(self):
        """Запускает Tor с текущими мостами (вызывается напрямую или после авто-обновления)."""
        bridges_strs = [b[0] if isinstance(b, tuple) else b for b in self._bridges]
        try:
            torrc_path = build_and_save_torrc(
                socks_port=self.config.socks_port,
                bridge_type=self.config.bridge_type,
                bridges=bridges_strs,
                lyrebird_exe=self.config.lyrebird_exe,
                tor_exe=self.config.tor_exe,
            )
        except Exception as e:
            self._alert(tr("alert.config_error_title"), tr("err.torrc_write", err=e))
            return

        self._log(tr("msg.torrc_written", path=torrc_path))
        self._start_connect_timeout()
        self.tor_manager.start(str(torrc_path))

    def _disconnect(self):
        self._connect_timeout.stop()
        self.tor_manager.stop()
        self._uptime_timer.stop()
        self._start_time = None
        self._uptime_lbl.setText("")

    def _open_settings(self):
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.config, self)
        if dlg.exec_():
            self._proxy_lbl.setText(f"127.0.0.1:{self.config.socks_port}")
            self._update_settings_hint()
            self._log(tr("msg.settings_saved"))

    def _copy_proxy(self):
        text = f"127.0.0.1:{self.config.socks_port}"
        QApplication.clipboard().setText(text)
        self._log(tr("msg.copied", text=text))

    # ================================================================= bridge update

    def _on_fetched(self, bridges: list):
        self._blog(f"Загружено {len(bridges)}. Тестирование...")
        self._update_bar.setValue(10)

        if self._test_thread and self._test_thread.isRunning():
            self._test_thread.cancel()
            self._test_thread.wait()

        self._test_thread = BridgeTesterThread(
            bridges,
            timeout=self.config.test_timeout,
            top_n=self.config.max_bridges,
        )
        self._test_thread.progress.connect(self._on_test_progress)
        self._test_thread.finished.connect(self._on_tested)
        self._test_thread.error.connect(self._on_test_error)
        self._test_thread.start()

    def _on_test_progress(self, pct: int, msg: str):
        self._update_bar.setValue(10 + int(pct * 0.9))
        self._blog(msg)

    def _on_tested(self, bridges: list):
        self._bridges = bridges
        self._save_bridges_cache()
        self._bridges_cnt.setText(f"{len(bridges)}")
        self._btn_update.setEnabled(True)
        self._update_bar.setValue(100)

        now_iso = datetime.now().isoformat()
        self.config.set("last_bridge_update", now_iso)
        self._refresh_time_labels()

        latencies = [f"{b[1]:.0f}мс" for b in bridges]
        self._blog(f"Готово: {len(bridges)} мостов ({', '.join(latencies)})")
        self._log(tr("msg.bridges_updated", n=len(bridges)))

        # Отложенный коннект: пользователь нажал «Подключить», но мостов было < 3
        if self._pending_connect_after_update:
            self._pending_connect_after_update = False
            self._user_requested_update = False
            if bridges:
                self._log(tr("msg.auto_connect_after_update"))
                self._do_connect()
            else:
                self._log(tr("msg.no_bridges_after_update"))
            return

        # Перезапускаем Tor только если он УЖЕ запущен — смена мостов "на лету"
        # НЕ перезапускаем автоматически при фоновом авто-обновлении:
        # это вызывало неожиданные отключения
        if self.tor_manager.is_running() and self._user_requested_update:
            self._log(tr("msg.tor_restart"))
            self._rebuild_and_restart()

        self._user_requested_update = False

    def _on_fetch_error(self, err: str):
        self._btn_update.setEnabled(True)
        self._update_bar.setVisible(False)
        self._blog(f"Ошибка: {err}")
        self._log(f"Ошибка загрузки мостов: {err}")
        self._user_requested_update = False

    def _on_test_error(self, err: str):
        self._btn_update.setEnabled(True)
        self._update_bar.setVisible(False)
        self._blog(f"Ошибка: {err}")
        self._user_requested_update = False

    def _on_bridge_type_changed(self, btype: str):
        self.config.set("bridge_type", btype)
        # Сбрасываем кеш — старые мосты другого типа не подходят
        self._bridges.clear()
        self._bridges_cnt.setText("0")
        self._log(tr("msg.type_changed", t=btype))

    # ================================================================= Tor status

    def _rebuild_and_restart(self):
        """Пересобирает torrc из текущих мостов и перезапускает Tor."""
        bridges_strs = [b[0] if isinstance(b, tuple) else b for b in self._bridges]
        try:
            torrc_path = build_and_save_torrc(
                socks_port=self.config.socks_port,
                bridge_type=self.config.bridge_type,
                bridges=bridges_strs,
                lyrebird_exe=self.config.lyrebird_exe,
                tor_exe=self.config.tor_exe,
            )
            self.tor_manager.restart(str(torrc_path))
        except Exception as e:
            self._log(tr("err.restart", err=e))

    def _on_tor_status(self, status: str):
        if status == "running":
            self._connect_timeout.stop()
            self._stall_retries = 0   # сброс счётчика после успешного подключения
            self._start_time = time.time()
            self._uptime_timer.start(1000)
            self._set_ui_connected()
        elif status == "starting":
            self._set_ui_connecting()
        else:
            self._connect_timeout.stop()
            self._uptime_timer.stop()
            self._start_time = None
            self._set_ui_disconnected()

    def _on_bootstrap(self, pct: int, msg: str):
        self._boot_bar.setValue(pct)
        self._boot_lbl.setText(f"Bootstrap {pct}%: {msg}")

    # Фразы из stdout Tor, означающие что ни один мост не отвечает
    _NO_BRIDGES_MARKERS = (
        "No running bridges",
        "Delaying directory fetches:",
        "We have no usable consensus",
    )

    def _on_tor_log(self, line: str):
        self._log(f"[tor] {line}")
        if any(m in line for m in self._NO_BRIDGES_MARKERS):
            self._on_no_bridges_in_log()

    def _on_tor_error(self, err: str):
        self._log(f"[ERR] {err}")
        self._alert(tr("alert.tor_error_title"), err)

    def _on_bootstrap_stalled(self):
        """Мосты не работают (bootstrap < 10% за 90с). Макс. 2 авто-попытки — защита от бесконечного цикла."""
        if self._stall_retries >= 2:
            self._log(tr("msg.stall_give_up"))
            self.tor_manager.stop()
            self._stall_retries = 0
            return

        self._stall_retries += 1
        self._log(tr("msg.stall_auto_retry", n=self._stall_retries))
        self.tor_manager.stop()
        # Пересобираем мосты и перезапустим Tor после обновления
        self._user_requested_update = True
        self._start_bridge_update(background=False)

    def _on_no_bridges_in_log(self):
        """Показываем пользователю сразу, не ждём 90с от watchdog. Один раз за сессию."""
        if self._no_bridges_warned:
            return
        self._no_bridges_warned = True
        self._log(tr("msg.no_running_bridges"))

    def _on_tor_stale(self):
        """Connectivity watchdog: SOCKS мёртв, NEWNYM не помог → рестарт."""
        self._log(tr("msg.tor_stale_restart"))
        self._rebuild_and_restart()

    def _on_tor_recovered(self):
        """NEWNYM помог — circuits пересозданы, рестарт не нужен."""
        self._log(tr("msg.tor_recovered"))

    def _on_bridge_rotate(self):
        """3+ SOCKS-неудач подряд — текущий мост скорее всего мёртв, сдвигаем в конец."""
        if len(self._bridges) < 2:
            # Нечего ротировать — делаем обычный рестарт
            self._log(tr("msg.tor_stale_restart"))
            self._on_tor_stale()
            return

        # Ротация: первый мост в конец
        old_first = self._bridges[0]
        old_name = old_first[0][:60] if isinstance(old_first, tuple) else str(old_first)[:60]
        self._bridges = self._bridges[1:] + [self._bridges[0]]
        new_first = self._bridges[0]
        new_name = new_first[0][:60] if isinstance(new_first, tuple) else str(new_first)[:60]

        self._log(tr("msg.bridge_rotated", old=old_name, new=new_name))
        self._save_bridges_cache()
        self._rebuild_and_restart()

    # ================================================================= UI state

    def _set_ui_connected(self):
        self._dot.setPixmap(dot_pixmap(COLOR_CONNECTED, 14))
        self._status_lbl.setText(tr("status.connected"))
        self._status_lbl.setStyleSheet(f"color:{COLOR_CONNECTED};")
        self._status_card.setStyleSheet(CARD_CONNECTED)
        self._boot_bar.setVisible(False)
        self._boot_lbl.setVisible(False)
        self._btn_connect.setText(tr("btn.disconnect"))
        self._btn_connect.setStyleSheet(BTN_DISCONNECT_STYLE)
        self._btn_connect.setEnabled(True)

    def _set_ui_connecting(self):
        self._dot.setPixmap(dot_pixmap(COLOR_CONNECTING, 14))
        self._status_lbl.setText(tr("status.connecting"))
        self._status_lbl.setStyleSheet(f"color:{COLOR_CONNECTING};")
        self._status_card.setStyleSheet(CARD_CONNECTING)
        self._boot_bar.setValue(0)
        self._boot_bar.setVisible(True)
        self._boot_lbl.setText(tr("boot.init"))
        self._boot_lbl.setVisible(True)
        self._btn_connect.setText(tr("btn.connecting"))
        self._btn_connect.setStyleSheet(BTN_CONNECTING_STYLE)
        self._btn_connect.setEnabled(False)

    def _set_ui_disconnected(self):
        self._dot.setPixmap(dot_pixmap(COLOR_DISCONNECTED, 14))
        self._status_lbl.setText(tr("status.disconnected"))
        self._status_lbl.setStyleSheet("")
        self._status_card.setStyleSheet(CARD_DEFAULT)
        self._boot_bar.setVisible(False)
        self._boot_lbl.setVisible(False)
        self._uptime_lbl.setText("")
        self._btn_connect.setText(tr("btn.connect"))
        self._btn_connect.setStyleSheet(BTN_CONNECT_STYLE)
        self._btn_connect.setEnabled(True)

    # ================================================================= timeout

    def _start_connect_timeout(self, seconds: int = 180):
        self._connect_timeout.start(seconds * 1000)

    def _on_connect_timeout(self):
        if self.tor_manager.is_running() or self.tor_manager.status == "running":
            return
        pct = self.tor_manager.get_bootstrap_progress()
        self._log(tr("msg.timeout", pct=pct))
        self.tor_manager.stop()
        bridge_type = self.config.bridge_type
        body = tr("alert.connect_timeout_body")
        if bridge_type == "webtunnel":
            body += tr("alert.connect_timeout_hint_webtunnel")
        elif bridge_type == "obfs4":
            body += tr("alert.connect_timeout_hint_obfs4")
        self._alert(tr("alert.connect_timeout_title"), body)

    # ================================================================= misc

    def _start_bridge_update(self, background: bool = False):
        """
        Запускает обновление мостов.
        background=True  → фоновое (авто), не перезапускает Tor после обновления.
        background=False → пользовательское, перезапускает Tor если запущен.
        """
        if not background:
            self._user_requested_update = True

        if self._fetch_thread and self._fetch_thread.isRunning():
            if not background:
                self._blog("Обновление уже выполняется...")
            return

        btype = self._bridge_type.currentText()
        self._blog(f"Загрузка ({btype})...")
        self._btn_update.setEnabled(False)
        self._update_bar.setValue(0)
        self._update_bar.setVisible(True)

        self._fetch_thread = BridgeFetcherThread(btype)
        self._fetch_thread.progress.connect(self._blog)
        self._fetch_thread.finished.connect(self._on_fetched)
        self._fetch_thread.error.connect(self._on_fetch_error)
        self._fetch_thread.start()

    def _tick_uptime(self):
        if self._start_time:
            s = int(time.time() - self._start_time)
            self._uptime_lbl.setText(f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}")

    def _refresh_time_labels(self):
        last = self.config.last_bridge_update
        if last:
            try:
                dt = datetime.fromisoformat(last)
                self._last_update_lbl.setText(dt.strftime("%d.%m %H:%M"))
                next_dt = dt + timedelta(hours=self.config.auto_update_hours)
                diff = next_dt - datetime.now()
                total_sec = int(diff.total_seconds())
                if total_sec > 0:
                    h, rem = divmod(total_sec, 3600)
                    m = rem // 60
                    self._next_update_lbl.setText(tr("bridge.next_update_in", h=h, m=m))
                else:
                    self._next_update_lbl.setText(tr("bridge.next_update_now"))
            except Exception:
                pass
        else:
            self._last_update_lbl.setText(tr("bridge.no_data"))

    def _check_auto_update(self):
        """Фоновое обновление по расписанию — НЕ перезапускает Tor (избегаем неожиданных разрывов)."""
        last = self.config.last_bridge_update
        needs_update = not last
        if not needs_update:
            try:
                dt = datetime.fromisoformat(last)
                needs_update = datetime.now() >= dt + timedelta(hours=self.config.auto_update_hours)
            except Exception:
                pass

        if not needs_update:
            return

        msg = tr("msg.first_run") if not last else tr("msg.auto_update")
        self._log(msg)
        # Фоновое — не перезапускаем Tor после обновления
        self._user_requested_update = False
        self._start_bridge_update(background=True)

    def _save_bridges_cache(self):
        try:
            data = [{"bridge": b[0], "latency": b[1]} for b in self._bridges]
            BRIDGES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Ошибка сохранения кеша: {e}")

    def _load_bridges_cache(self):
        if BRIDGES_FILE.exists():
            try:
                items = json.loads(BRIDGES_FILE.read_text(encoding="utf-8"))
                self._bridges = [(i["bridge"], i["latency"]) for i in items]
                self._bridges_cnt.setText(f"{len(self._bridges)}")
                self._log(tr("msg.bridges_loaded", n=len(self._bridges)))
            except Exception as e:
                logger.error(f"Ошибка загрузки кеша: {e}")

    def _update_settings_hint(self):
        tor = self.config.tor_exe
        if tor and Path(tor).exists():
            self._settings_hint.setText(tr("hint.tor_ok", name=Path(tor).name))
        else:
            self._settings_hint.setText(tr("hint.tor_not_found"))

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_view.append(
            f"<span style='color:#44445a'>[{ts}]</span> "
            f"<span style='color:#c8c8d8'>{msg}</span>"
        )
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _blog(self, msg: str):
        self._bridge_log.append(msg)
        sb = self._bridge_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _alert(self, title: str, text: str):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStyleSheet(DARK_THEME)
        msg.exec_()

    # ================================================================= close → tray

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def shutdown(self):
        """Полное завершение — останавливаем таймеры и процессы."""
        self._uptime_timer.stop()
        self._connect_timeout.stop()
        self._auto_update_timer.stop()
        self._next_update_timer.stop()
        if hasattr(self, "_app_proxy"):
            self._app_proxy.stop_all()
        self.tor_manager.stop()
