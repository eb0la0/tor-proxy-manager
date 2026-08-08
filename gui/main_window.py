import html
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QTextEdit,
    QApplication, QFrame, QScrollArea, QMessageBox,
)

from core.config import Config
from core.i18n import current_language, tr
from core import bridge_cache
from core.bridge_fetcher import BridgeFetcherThread
from core.bridge_tester import BridgeTesterThread
from core.torrc_builder import build_and_save_torrc
from core.tor_manager import TorManager
from gui import icons, theme
from gui.widgets import (
    Card, EmptyState, ResponsiveRow, Select,
    hline, icon_button, label, text_button,
)

logger = logging.getLogger(__name__)

APP_VERSION = "2.0"

# Сколько ждать штатного завершения рабочих потоков при выходе.
# Держать пользователя дольше пары секунд нельзя.
_SHUTDOWN_GRACE_MS = 2000

# Потоки, не успевшие завершиться к моменту выхода. Ссылка на уровне модуля
# не даёт сборщику мусора разрушить работающий QThread (это фатально для Qt).
_LINGERING_THREADS: list = []


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
        self._last_fetch_result = None
        self._retired_threads: list = []
        self._updating_type: str = ""
        self._using_cache: bool = False
        self._stall_retries: int = 0
        self._no_bridges_warned: bool = False

        self._build_ui()
        self._connect_signals()
        self._load_bridges_cache()
        self._refresh_time_labels()
        self._btn_connect.setFocus()
        QTimer.singleShot(800, self._check_auto_update)


    # ================================================================= UI build

    def _build_ui(self):
        self.setWindowTitle("TorProxy Manager")
        self.setMinimumWidth(theme.WINDOW_MIN_W)
        self.setMinimumHeight(theme.WINDOW_MIN_H)
        # Дефолт рассчитан так, чтобы весь dashboard был виден без прокрутки.
        self.resize(940, 660)
        self.setStyleSheet(theme.THEME)

        root_widget = QWidget()
        self.setCentralWidget(root_widget)

        outer = QVBoxLayout(root_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Шапка закреплена: она не должна уезжать при прокрутке содержимого.
        outer.addWidget(self._make_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        container = QWidget()
        scroll.setWidget(container)

        col = QVBoxLayout(container)
        col.setSpacing(theme.SP_3)
        col.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_4, theme.SP_4)

        # Герой во всю ширину — статус Tor остаётся главным акцентом.
        col.addWidget(self._make_hero())

        # Мосты и приложения — рядом на широком окне, друг под другом на узком.
        self._columns = ResponsiveRow(breakpoint=800)
        self._columns.set_widgets(self._make_bridges_card(), self._make_apps_card())
        col.addWidget(self._columns, 1)

        col.addWidget(self._make_activity_card())

    # ---- Header ----
    def _make_header(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {theme.BG};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_3, theme.SP_3)
        lay.setSpacing(theme.SP_3)

        mark = QLabel()
        mark.setPixmap(icons.pixmap("shield", 22, theme.ACCENT))
        lay.addWidget(mark)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("TorProxy Manager", "app_title"))
        titles.addWidget(label(tr("app.subtitle"), "caption"))
        lay.addLayout(titles)
        lay.addStretch()

        # Версия переехала в «Настройки»: в шапке она висела без назначения.
        self._btn_settings = icon_button("settings", tr("btn.settings"), theme.ICON_LG)
        self._btn_settings.clicked.connect(self._open_settings)
        lay.addWidget(self._btn_settings)

        wrap = QWidget()
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.setSpacing(0)
        wrap_lay.addWidget(bar)
        wrap_lay.addWidget(hline())
        return wrap

    # ---- Hero: состояние подключения ----
    def _make_hero(self) -> QFrame:
        """
        Одна плотная строка вместо трёх ярусов: статус слева, адрес прокси
        по центру, действие справа. Раньше блок занимал треть экрана.
        """
        self._status_card = QFrame()
        self._status_card.setObjectName("hero")
        self._status_card.setStyleSheet(theme.hero_style())

        lay = QVBoxLayout(self._status_card)
        lay.setContentsMargins(theme.SP_5, theme.SP_4, theme.SP_5, theme.SP_4)
        lay.setSpacing(theme.SP_3)

        row = QHBoxLayout()
        row.setSpacing(theme.SP_4)

        self._dot = QLabel()
        self._dot.setFixedSize(28, 28)
        self._dot.setAlignment(Qt.AlignCenter)
        self._dot.setPixmap(icons.dot(theme.ERR, 9, glow=True))
        row.addWidget(self._dot, 0, Qt.AlignVCenter)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self._status_lbl = label(tr("status.disconnected"), "hero_status")
        texts.addWidget(self._status_lbl)
        self._status_hint = label(tr("status.hint.disconnected"), "secondary")
        texts.addWidget(self._status_hint)
        row.addLayout(texts)
        row.addStretch()

        # Адрес прокси рядом со статусом: это то, что копируют чаще всего.
        addr = QVBoxLayout()
        addr.setSpacing(1)
        addr_head = QHBoxLayout()
        addr_head.setSpacing(theme.SP_1)
        addr_head.addWidget(label(tr("proxy.label"), "caption"))
        self._uptime_lbl = label("", "caption")
        addr_head.addWidget(self._uptime_lbl)
        addr_head.addStretch()
        addr.addLayout(addr_head)

        addr_row = QHBoxLayout()
        addr_row.setSpacing(theme.SP_1)
        self._proxy_lbl = label(f"127.0.0.1:{self.config.socks_port}", "mono")
        addr_row.addWidget(self._proxy_lbl)
        self._btn_copy = icon_button("copy", tr("btn.copy"), theme.ICON_SM)
        self._btn_copy.clicked.connect(self._copy_proxy)
        addr_row.addWidget(self._btn_copy)
        addr.addLayout(addr_row)
        row.addLayout(addr)
        row.addSpacing(theme.SP_3)

        self._btn_connect = QPushButton(tr("btn.connect"))
        self._btn_connect.setObjectName("primary")
        self._btn_connect.setCursor(Qt.PointingHandCursor)
        self._btn_connect.setMinimumWidth(180)
        self._btn_connect.setFixedHeight(40)
        self._btn_connect.clicked.connect(self._toggle_connection)
        row.addWidget(self._btn_connect, 0, Qt.AlignVCenter)
        lay.addLayout(row)

        # Прогресс bootstrap — только во время подключения.
        self._boot_bar = QProgressBar()
        self._boot_bar.setRange(0, 100)
        self._boot_bar.setVisible(False)
        lay.addWidget(self._boot_bar)

        self._boot_lbl = label("", "caption")
        self._boot_lbl.setVisible(False)
        lay.addWidget(self._boot_lbl)

        # Предупреждение о ненайденном tor.exe: молчит, пока всё в порядке.
        self._warn_row = QFrame()
        warn_lay = QHBoxLayout(self._warn_row)
        warn_lay.setContentsMargins(0, 0, 0, 0)
        warn_lay.setSpacing(theme.SP_2)
        warn_icon = QLabel()
        warn_icon.setPixmap(icons.pixmap("warning", theme.ICON_SM, theme.WARN))
        warn_lay.addWidget(warn_icon, 0, Qt.AlignTop)
        self._settings_hint = label("", "caption")
        self._settings_hint.setWordWrap(True)
        self._settings_hint.setStyleSheet(
            f"color: {theme.WARN}; font-size: {theme.FS_CAPTION}px;")
        warn_lay.addWidget(self._settings_hint, 1)
        lay.addWidget(self._warn_row)
        self._update_settings_hint()

        return self._status_card

    # ---- Мосты ----
    def _make_bridges_card(self) -> Card:
        card = Card(tr("bridge.group_title"))

        # Крупное число + подпись: главный факт секции читается мгновенно.
        count_row = QHBoxLayout()
        count_row.setSpacing(theme.SP_2)
        self._bridges_cnt = label("0", "big_number")
        count_row.addWidget(self._bridges_cnt, 0, Qt.AlignBottom)
        self._bridges_cnt_unit = label(tr("bridge.available"), "secondary")
        count_row.addWidget(self._bridges_cnt_unit, 0, Qt.AlignBottom)
        count_row.addStretch()
        card.add_layout(count_row)

        # Транспорт и свежесть данных одной строкой.
        self._last_update_lbl = label("", "secondary")
        self._last_update_lbl.setWordWrap(True)
        card.add(self._last_update_lbl)

        controls = QHBoxLayout()
        controls.setSpacing(theme.SP_2)

        self._bridge_type = Select()
        self._bridge_type.addItems(["obfs4", "vanilla", "webtunnel"])
        idx = self._bridge_type.findText(self.config.bridge_type)
        self._bridge_type.setCurrentIndex(idx if idx >= 0 else 0)
        self._bridge_type.setFixedWidth(124)
        self._bridge_type.currentTextChanged.connect(self._on_bridge_type_changed)
        controls.addWidget(self._bridge_type)

        self._btn_update = text_button(tr("btn.update_bridges"), "refresh",
                                       object_name="secondary", color=theme.TEXT)
        self._btn_update.setCursor(Qt.PointingHandCursor)
        self._btn_update.setFixedHeight(34)
        self._btn_update.clicked.connect(self._start_bridge_update)
        controls.addWidget(self._btn_update)
        controls.addStretch()
        card.add_layout(controls)

        self._update_bar = QProgressBar()
        self._update_bar.setRange(0, 100)
        self._update_bar.setVisible(False)
        card.add(self._update_bar)

        # Здоровье источников — одна строка; подробности в отдельном окне.
        health = QHBoxLayout()
        health.setSpacing(theme.SP_2)
        self._sources_icon = QLabel()
        self._sources_icon.setVisible(False)
        health.addWidget(self._sources_icon, 0, Qt.AlignVCenter)

        self._sources_lbl = label("", "secondary")
        health.addWidget(self._sources_lbl, 0, Qt.AlignVCenter)
        health.addStretch()

        self._btn_diag = text_button(tr("btn.details"))
        self._btn_diag.setCursor(Qt.PointingHandCursor)
        self._btn_diag.setVisible(False)
        self._btn_diag.clicked.connect(self._open_diagnostics)
        health.addWidget(self._btn_diag, 0, Qt.AlignVCenter)

        self._next_update_lbl = label("", "caption")
        health.addWidget(self._next_update_lbl, 0, Qt.AlignVCenter)
        card.add_layout(health)

        self._bridges_empty = EmptyState(tr("bridge.empty_title"))
        card.add(self._bridges_empty)
        card.body.addStretch()

        self._bridges_card = card
        return card

    # ---- Приложения ----
    def _make_apps_card(self) -> QWidget:
        from gui.app_proxy_widget import AppProxyWidget
        self._app_proxy = AppProxyWidget(self.config, log_fn=self._log)
        return self._app_proxy

    # ---- Активность ----
    def _make_activity_card(self) -> Card:
        card = Card(tr("activity.title"))

        btn_clear = text_button(tr("btn.clear"))
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(lambda: self._log_view.clear())
        card.add_header_widget(btn_clear)

        # Журнал — фоновая информация: низкий, неконтрастный, без рамки.
        self._log_view = QTextEdit()
        self._log_view.setObjectName("activity")
        self._log_view.setReadOnly(True)
        self._log_view.setFixedHeight(84)
        self._log_view.setPlaceholderText(tr("log.placeholder"))
        card.add(self._log_view)

        self._activity_card = card
        return card

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

    def _on_fetched(self, result):
        """
        Приходит FetchResult. Ни один недоступный источник не является ошибкой,
        пока хотя бы один ответил. Если не ответил никто — остаёмся на кеше.
        """
        self._last_fetch_result = result
        self._update_source_status(result)

        if self._updating_type and self._updating_type != self.config.bridge_type:
            # Транспорт переключили во время загрузки — тестировать эти мосты
            # уже незачем, они относятся к прежнему типу.
            self._log(tr("msg.update_type_changed", t=self._updating_type))
            self._set_update_busy(False)
            self._update_bar.setVisible(False)
            self._user_requested_update = False
            self._pending_connect_after_update = False
            return

        if not result.bridges:
            # Все источники недоступны либо не дали ни одного валидного моста.
            # Кеш НЕ трогаем — у пользователя остаются прошлые мосты.
            self._on_update_failed(result)
            return

        self._blog(tr("bridge.fetched_testing", n=len(result.bridges)))
        self._update_bar.setValue(10)

        self._retire_test_thread()

        self._test_thread = BridgeTesterThread(
            result.bridges,
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
        self._set_update_busy(False)
        self._update_bar.setValue(100)

        if not bridges:
            # Мосты скачались, но ни один не отвечает по сети.
            # Прошлый рабочий набор ценнее пустого — сохраняем его.
            self._on_update_failed(getattr(self, "_last_fetch_result", None),
                                   tested_empty=True)
            return

        fetched_type = self._updating_type or self.config.bridge_type
        if fetched_type != self.config.bridge_type:
            # Пользователь переключил транспорт, пока шло обновление.
            # Принять эти мосты как текущие нельзя — они другого типа.
            self._log(tr("msg.update_type_changed", t=fetched_type))
            self._user_requested_update = False
            self._pending_connect_after_update = False
            return

        self._bridges = bridges
        self._using_cache = False
        self._save_bridges_cache(fetched_type)
        self._set_bridge_count(len(bridges))

        now_iso = datetime.now().isoformat()
        self.config.set("last_bridge_update", now_iso)
        self._refresh_time_labels()

        fastest = min(b[1] for b in bridges)
        self._log(tr("bridge.ready", n=len(bridges), ms=f"{fastest:.0f}"), "ok")
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

    def _retire_test_thread(self):
        """
        Отменяет предыдущий поток тестирования, не блокируя UI ожиданием.

        Ссылку сохраняем: сборка мусора работающего QThread роняет приложение,
        а wait() в GUI-потоке подвешивает интерфейс на время таймаутов.
        Досчитавшие потоки выкидываются здесь же.
        """
        self._retired_threads = [
            t for t in getattr(self, "_retired_threads", []) if not t.isFinished()
        ]
        old = self._test_thread
        if old and old.isRunning():
            old.cancel()
            for sig in (old.progress, old.finished, old.error):
                try:
                    sig.disconnect()
                except TypeError:
                    pass          # уже отключён
            self._retired_threads.append(old)

    def _update_source_status(self, result):
        """
        Показываем число независимых ПОСТАВЩИКОВ, а не файлов.

        «Проверенный» и «полный» списки одного репозитория — не две
        независимые точки отказа: они недоступны одновременно. Показывать
        «6/6» там, где реально 4 поставщика, значит внушать пользователю
        ложное чувство запаса прочности.
        """
        ok = len(result.ok_providers)
        total = result.total_providers
        healthy = ok == total

        # На главном экране — одна строка. Список источников, хосты и задержки
        # переехали в окно диагностики: на дашборде это лишний шум.
        self._sources_icon.setVisible(True)
        self._sources_icon.setPixmap(icons.pixmap(
            "check" if healthy else "warning", theme.ICON_SM,
            theme.OK if healthy else theme.WARN))
        self._sources_lbl.setText(tr("bridge.sources_status", ok=ok, total=total))
        self._sources_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM if healthy else theme.WARN};"
            f"font-size: {theme.FS_SMALL}px;")
        self._btn_diag.setVisible(True)

        dead_providers = sorted(result.all_providers - result.ok_providers)
        if ok and dead_providers:
            # Часть поставщиков недоступна — это норма, не ошибка.
            self._log(tr("msg.some_sources_down",
                         names=", ".join(dead_providers[:3]), ok=ok))

        # Технические подробности — только в лог-файл
        for s in result.failed_sources:
            logger.info(f"Источник недоступен [{s.name}]: {s.error}")
        for s in result.empty_sources:
            logger.info(f"Источник пуст [{s.name}]: мостов не содержит")

    def _open_diagnostics(self):
        from gui.diagnostics_dialog import DiagnosticsDialog
        DiagnosticsDialog(self._last_fetch_result, self).exec_()

    def _describe_zero_bridges(self, result, tested_empty: bool) -> str:
        """
        «0 мостов» бывает по четырём разным причинам, и пользователю нужно
        сообщать именно ту, что произошла: от неё зависит, что ему делать.
        """
        if tested_empty:
            # Мосты получены, но ни один не отвечает по сети.
            return tr("bridge.none_reachable")
        if result is None or not result.any_success:
            # Ни один источник не ответил — это проблема сети/блокировки.
            return tr("bridge.all_sources_down")
        if result.rejected:
            # Источники ответили, но содержимое не является валидными мостами.
            return tr("bridge.all_rejected")
        # Источники ответили и честно вернули пустые списки.
        return tr("bridge.sources_empty")

    def _on_update_failed(self, result, tested_empty: bool = False):
        """
        Обновление не дало мостов. Показываем понятное сообщение и опираемся
        на кеш, если он есть. Приложение остаётся работоспособным.
        """
        self._set_update_busy(False)
        self._update_bar.setVisible(False)
        # Запоминаем ДО сброса флагов: диалог показываем только пользователю,
        # фоновое авто-обновление молча уходит в лог.
        was_user_initiated = self._user_requested_update or self._pending_connect_after_update
        self._user_requested_update = False

        cache = bridge_cache.load()
        have_local = bool(self._bridges) or bool(cache)

        self._blog(self._describe_zero_bridges(result, tested_empty))

        if have_local:
            self._using_cache = True
            self._refresh_time_labels()
            if not self._bridges and cache:
                self._bridges = cache.bridges
                self._set_bridge_count(len(self._bridges))
            self._log(tr("msg.using_cached_bridges",
                         n=len(self._bridges), age=cache.age_text()))
        else:
            self._log(tr("msg.update_failed_no_cache"))
            if was_user_initiated:
                self._alert(tr("alert.bridges_unavailable_title"),
                            tr("alert.bridges_unavailable_body"))

        if self._pending_connect_after_update:
            self._pending_connect_after_update = False
            if self._bridges:
                self._log(tr("msg.auto_connect_after_update"))
                self._do_connect()
            else:
                self._log(tr("msg.no_bridges_after_update"))

    def _on_fetch_error(self, err: str):
        self._set_update_busy(False)
        self._update_bar.setVisible(False)
        self._blog(tr("bridge.all_sources_down"))
        logger.error(f"Ошибка загрузки мостов: {err}")
        self._on_update_failed(None)

    def _on_test_error(self, err: str):
        """
        Сбой самого тестировщика (не «мосты не отвечают», а исключение внутри).
        Рабочий набор при этом трогать нельзя — он ни в чём не виноват.
        """
        logger.error(f"Ошибка тестирования мостов: {err}")
        self._on_update_failed(getattr(self, "_last_fetch_result", None),
                               tested_empty=True)

    def _on_bridge_type_changed(self, btype: str):
        self.config.set("bridge_type", btype)
        # Сбрасываем кеш — старые мосты другого типа не подходят
        self._bridges.clear()
        self._set_bridge_count(0)
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

    def _apply_state(self, state: str, status_key: str, hint_key: str):
        """
        Единая точка смены визуального состояния.

        Цветом окрашиваются только индикатор, подпись статуса и тонкая полоса
        слева от герой-блока — не вся карточка целиком.
        """
        color = theme.STATUS_COLORS[state]
        self._dot.setPixmap(icons.dot(color, 9, glow=(state != "disconnected")))
        self._status_lbl.setText(tr(status_key))
        self._status_lbl.setStyleSheet(f"color: {color};")
        self._status_hint.setText(tr(hint_key))
        self._status_card.setStyleSheet(theme.hero_style(color))

    def _set_ui_connected(self):
        self._apply_state("connected", "status.connected", "status.hint.connected")
        self._boot_bar.setVisible(False)
        self._boot_lbl.setVisible(False)
        self._btn_connect.setText(tr("btn.disconnect"))
        self._btn_connect.setObjectName("danger")
        self._btn_connect.setIcon(icons.icon("power", theme.ICON_SM, theme.ERR))
        self._restyle(self._btn_connect)
        self._btn_connect.setEnabled(True)

    def _set_ui_connecting(self):
        self._apply_state("connecting", "status.connecting", "status.hint.connecting")
        self._boot_bar.setValue(0)
        self._boot_bar.setVisible(True)
        self._boot_lbl.setText(tr("boot.init"))
        self._boot_lbl.setVisible(True)
        self._btn_connect.setText(tr("btn.connecting"))
        self._btn_connect.setObjectName("primary")
        self._btn_connect.setIcon(QIcon())
        self._restyle(self._btn_connect)
        self._btn_connect.setEnabled(False)

    def _set_ui_disconnected(self):
        self._apply_state("disconnected", "status.disconnected",
                          "status.hint.disconnected")
        self._boot_bar.setVisible(False)
        self._boot_lbl.setVisible(False)
        self._uptime_lbl.setText("")
        self._btn_connect.setText(tr("btn.connect"))
        self._btn_connect.setObjectName("primary")
        self._btn_connect.setIcon(icons.icon("power", theme.ICON_SM, "#ffffff"))
        self._restyle(self._btn_connect)
        self._btn_connect.setEnabled(True)

    @staticmethod
    def _restyle(widget: QWidget):
        """Qt не перечитывает стиль сам после смены objectName."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)

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
                self._blog(tr("bridge.already_updating"))
            return

        btype = self._bridge_type.currentText()
        # Тип фиксируется на всё время обновления. Пользователь может
        # переключить транспорт, пока идёт загрузка, — результат обязан
        # остаться привязанным к тому типу, для которого его запрашивали.
        self._updating_type = btype
        self._blog(tr("bridge.fetching", transport=btype))
        self._set_update_busy(True)
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

    @staticmethod
    def _humanize_age(dt: datetime) -> str:
        """«2 минуты назад» вместо «08.08 05:36» — так понятнее без вычислений."""
        secs = int((datetime.now() - dt).total_seconds())
        if secs < 90:
            return tr("time.just_now")
        if secs < 3600:
            return tr("time.minutes_ago", n=secs // 60)
        if secs < 86400:
            return tr("time.hours_ago", n=secs // 3600)
        if secs < 7 * 86400:
            return tr("time.days_ago", n=secs // 86400)
        return dt.strftime("%d.%m.%Y")

    def _refresh_time_labels(self):
        """
        Строка вида «obfs4 · обновлены 5 минут назад».

        Если последнее обновление не удалось, здесь же честно сообщается,
        что показываются сохранённые мосты — это важнее, чем таймер.
        """
        transport = self.config.bridge_type
        last = self.config.last_bridge_update

        if not last:
            self._last_update_lbl.setText(
                tr("bridge.meta_never", transport=transport))
            self._next_update_lbl.setText("")
            return

        try:
            dt = datetime.fromisoformat(last)
        except Exception:
            self._last_update_lbl.setText(
                tr("bridge.meta_never", transport=transport))
            self._next_update_lbl.setText("")
            return

        age = self._humanize_age(dt)
        if self._using_cache:
            self._last_update_lbl.setText(
                tr("bridge.meta_cached", transport=transport, age=age))
            self._last_update_lbl.setStyleSheet(
                f"color: {theme.WARN}; font-size: {theme.FS_SMALL}px;")
        else:
            self._last_update_lbl.setText(
                tr("bridge.meta", transport=transport, age=age))
            self._last_update_lbl.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: {theme.FS_SMALL}px;")

        total_sec = int((dt + timedelta(hours=self.config.auto_update_hours)
                         - datetime.now()).total_seconds())
        if total_sec > 0:
            h, rem = divmod(total_sec, 3600)
            self._next_update_lbl.setText(
                tr("bridge.next_update_in", h=h, m=rem // 60))
        else:
            self._next_update_lbl.setText(tr("bridge.next_update_now"))

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

    def _save_bridges_cache(self, bridge_type: str | None = None):
        bridge_cache.save(self._bridges, bridge_type or self.config.bridge_type)

    def _load_bridges_cache(self):
        """
        Кеш применяется, только если он относится к текущему типу мостов —
        иначе после смены типа приложение подключалось бы старыми мостами
        другого транспорта.
        """
        cache = bridge_cache.load()
        if not cache:
            return

        if not cache.matches_type(self.config.bridge_type):
            logger.info(
                f"Кеш относится к типу {cache.bridge_type}, "
                f"текущий {self.config.bridge_type} — пропускаем"
            )
            return

        self._bridges = cache.bridges
        self._set_bridge_count(len(self._bridges))
        self._log(tr("msg.bridges_loaded_age",
                     n=len(self._bridges), age=cache.age_text()))

    def _set_update_busy(self, busy: bool):
        """Кнопка обновления сообщает о ходе работы, а не просто гаснет."""
        self._btn_update.setEnabled(not busy)
        self._btn_update.setText(
            tr("btn.updating") if busy else tr("btn.update_bridges"))
        if not busy:
            self._update_bar.setVisible(False)

    @staticmethod
    def _group_number(n: int) -> str:
        """
        Разделитель разрядов по языку: «5 194» для русского, «5,194» для
        английского. Узкий неразрывный пробел не даёт числу разорваться.
        """
        grouped = f"{n:,}"
        return grouped if current_language() == "en" else grouped.replace(",", " ")

    def _set_bridge_count(self, n: int):
        """Счётчик и пустое состояние всегда меняются вместе."""
        self._bridges_cnt.setText(self._group_number(n))
        self._bridges_cnt.setStyleSheet(
            f"color: {theme.TEXT if n else theme.TEXT_MUTE};")
        self._bridges_empty.setVisible(n == 0)

    def _update_settings_hint(self):
        """Показываем только проблему: исправное состояние не требует подписи."""
        tor = self.config.tor_exe
        ok = bool(tor) and Path(tor).exists()
        self._warn_row.setVisible(not ok)
        if not ok:
            self._settings_hint.setText(tr("hint.tor_not_found"))

    def _log(self, msg: str, tone: str = ""):
        """
        Единый журнал активности. tone подсвечивает строку, но приглушённо:
        журнал — второстепенная информация и не должен спорить со статусом.
        """
        color = {
            "ok": theme.OK,
            "warn": theme.WARN,
            "err": theme.ERR,
        }.get(tone, theme.TEXT_DIM)

        ts = datetime.now().strftime("%H:%M")
        safe = html.escape(str(msg))
        self._log_view.append(
            f"<span style='color:{theme.TEXT_MUTE}'>{ts}</span>&nbsp;&nbsp;"
            f"<span style='color:{color}'>{safe}</span>"
        )
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _blog(self, msg: str):
        """
        Раньше сообщения об обновлении мостов шли в отдельное текстовое поле.
        Два журнала рядом — лишний визуальный блок; теперь запись одна.
        """
        text = str(msg)
        tone = ""
        if text.startswith("[OK]"):
            tone, text = "ok", text[4:].strip()
        elif text.startswith("[--]"):
            tone, text = "warn", text[4:].strip()
        self._log(text, tone)

    def _alert(self, title: str, text: str):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStyleSheet(theme.THEME)
        msg.exec_()

    # ================================================================= close → tray

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def shutdown(self):
        """Полное завершение — останавливаем таймеры, потоки и процессы."""
        self._uptime_timer.stop()
        self._connect_timeout.stop()
        self._auto_update_timer.stop()
        self._next_update_timer.stop()

        # Рабочие потоки нужно завершить: уничтожение работающего QThread
        # роняет приложение ("QThread: Destroyed while thread is still running").
        #
        # cancel() проверяется между запросами, но прервать уже начатое
        # блокирующее чтение сокета переносимо нельзя — поток может висеть
        # до истечения сетевого таймаута.
        #
        # QThread.terminate() здесь применять НЕЛЬЗЯ: поток исполняет Python и
        # в момент снятия почти наверняка держит GIL. TerminateThread оставляет
        # его захваченным, и интерпретатор падает с access violation уже на
        # выходе. Проверено — именно так и происходит.
        #
        # Поэтому: ждём ограниченное время, а не дождавшись — оставляем поток
        # доживать, но удерживаем на него ссылку, чтобы Qt не разрушил
        # работающий объект. Процесс всё равно завершается, сокеты закроет ОС.
        threads = [self._fetch_thread, self._test_thread]
        threads += getattr(self, "_retired_threads", [])
        for thread in threads:
            if not (thread and thread.isRunning()):
                continue
            thread.cancel()
            if not thread.wait(_SHUTDOWN_GRACE_MS):
                logger.warning(
                    "Поток не завершился за %d мс — оставлен дорабатывать",
                    _SHUTDOWN_GRACE_MS,
                )
                _LINGERING_THREADS.append(thread)

        if hasattr(self, "_app_proxy"):
            self._app_proxy.stop_all()
        self.tor_manager.stop()
