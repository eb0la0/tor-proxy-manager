import logging
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QBrush, QPixmap, QPainter, QPainterPath, QIcon, QPen, QFont
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QApplication

from gui import theme

COLOR_CONNECTED = theme.OK
COLOR_DISCONNECTED = theme.ERR
COLOR_CONNECTING = theme.WARN
from core.i18n import tr

logger = logging.getLogger(__name__)


def _circle_icon(color: str, size: int = 32) -> QIcon:
    """Иконка — цветной круг с тёмным фоном."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(theme.BG)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, size, size)
    r = 5
    p.setBrush(QBrush(QColor(color)))
    p.drawEllipse(r, r, size - 2 * r, size - 2 * r)
    p.end()
    return QIcon(pix)


def create_app_icon() -> QIcon:
    """Генерирует иконку приложения (щит с буквой T) через QPainter."""
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    # Фон — скруглённый квадрат
    p.setBrush(QBrush(QColor(theme.BG)))
    p.setPen(QPen(QColor(theme.ACCENT), 2))
    p.drawRoundedRect(2, 2, size - 4, size - 4, 12, 12)

    # Щит
    cx = size / 2
    path = QPainterPath()
    path.moveTo(cx, size - 10)         # низ
    path.lineTo(10, size / 2 + 6)      # левый бок
    path.lineTo(10, 16)                # левый верх
    path.quadTo(cx, 8, size - 10, 16)  # верхняя дуга
    path.lineTo(size - 10, size / 2 + 6)  # правый бок
    path.closeSubpath()

    p.setBrush(QBrush(QColor(theme.ACCENT)))
    p.setPen(Qt.NoPen)
    p.drawPath(path)

    # Буква «T»
    p.setPen(QPen(QColor(theme.TEXT)))
    font = QFont("Arial", 20, QFont.Bold)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignCenter, "T")

    p.end()
    return QIcon(pix)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, main_window, tor_manager, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.tor_manager = tor_manager

        self.setIcon(_circle_icon(COLOR_DISCONNECTED))
        self.setToolTip(tr("tray.tooltip_disconnected"))

        self._build_menu()
        self.activated.connect(self._on_activated)
        tor_manager.status_changed.connect(self._on_status_changed)

    # ------------------------------------------------------------------ menu

    def _build_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e2a3a;
                color: #e0e0e0;
                border: 1px solid #2a3a4a;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item { padding: 7px 28px; border-radius: 4px; }
            QMenu::item:selected { background-color: #0f3460; }
            QMenu::separator {
                height: 1px;
                background-color: #253545;
                margin: 4px 8px;
            }
        """)

        self._act_connect = QAction(tr("btn.connect"), self)
        self._act_connect.triggered.connect(self._toggle)
        menu.addAction(self._act_connect)

        act_update = QAction(tr("tray.update_bridges"), self)
        act_update.triggered.connect(lambda: self.main_window._start_bridge_update())
        menu.addAction(act_update)

        act_settings = QAction(tr("btn.settings"), self)
        act_settings.triggered.connect(lambda: self.main_window._open_settings())
        menu.addAction(act_settings)

        menu.addSeparator()

        act_show = QAction(tr("tray.show_window"), self)
        act_show.triggered.connect(self._show_window)
        menu.addAction(act_show)

        menu.addSeparator()

        act_exit = QAction(tr("tray.quit"), self)
        act_exit.triggered.connect(self._exit)
        menu.addAction(act_exit)

        self.setContextMenu(menu)

    # ------------------------------------------------------------------ slots

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.main_window.isVisible():
                self.main_window.hide()
            else:
                self._show_window()

    def _show_window(self):
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _toggle(self):
        if self.tor_manager.is_running():
            self.main_window._disconnect()
        else:
            self.main_window._connect()

    def _on_status_changed(self, status: str):
        if status == "running":
            self.setIcon(_circle_icon(COLOR_CONNECTED))
            self.setToolTip(tr("tray.tooltip_connected"))
            self._act_connect.setText(tr("btn.disconnect"))
        elif status == "starting":
            self.setIcon(_circle_icon(COLOR_CONNECTING))
            self.setToolTip(tr("tray.tooltip_connecting"))
            self._act_connect.setText(tr("btn.connecting"))
        else:
            self.setIcon(_circle_icon(COLOR_DISCONNECTED))
            self.setToolTip(tr("tray.tooltip_disconnected"))
            self._act_connect.setText(tr("btn.connect"))

    def _exit(self):
        # Полное завершение через shutdown() главного окна
        self.main_window.shutdown()
        QApplication.quit()
