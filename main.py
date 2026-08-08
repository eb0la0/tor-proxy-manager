"""
TorProxy Manager — точка входа.
Запуск: python main.py
Зависимости: PyQt5>=5.15
"""
import sys
import signal
import logging
import os
import ctypes
from pathlib import Path

# ---- настройка логирования до импорта Qt ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---- PyQt5 ----
from PyQt5.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from PyQt5.QtCore import Qt

from core.config import Config
from core.tor_manager import TorManager
from core.i18n import load_language, tr
from gui.main_window import MainWindow
from gui.tray_icon import TrayIcon, create_app_icon


def main() -> int:
    # Масштабирование для HiDPI-экранов
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("TorProxy Manager")

    # Защита от повторного запуска — именованный мьютекс Windows
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "TorProxyManager_SingleInstance_v1")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        load_language("ru")
        QMessageBox.information(
            None,
            tr("already_running_title"),
            tr("already_running_body"),
        )
        return 0
    app.setApplicationVersion("2.0.0")
    app.setQuitOnLastWindowClosed(False)

    # Иконка приложения (генерируется программно)
    app_icon = create_app_icon()
    app.setWindowIcon(app_icon)

    # Проверка трея
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "Ошибка",
            "Системный трей недоступен на этом устройстве.\n"
            "Приложение не может быть запущено.",
        )
        return 1

    # Инициализация ядра
    config = Config()
    load_language(config.language)   # загружаем язык из сохранённого конфига
    tor_manager = TorManager(config)

    # Главное окно
    window = MainWindow(config, tor_manager)
    window.setWindowIcon(app_icon)
    window.show()

    # Иконка в трее
    tray = TrayIcon(window, tor_manager)
    tray.show()

    # Корректное завершение — останавливаем таймеры, процессы и дочерние приложения
    app.aboutToQuit.connect(window.shutdown)

    def _sigint_handler(*_):
        logger.info("Получен сигнал прерывания, завершение...")
        window.shutdown()
        app.quit()

    signal.signal(signal.SIGINT, _sigint_handler)

    # Таймер, чтобы Python мог обработать сигналы (Qt блокирует GIL)
    from PyQt5.QtCore import QTimer
    sigcheck = QTimer()
    sigcheck.start(500)
    sigcheck.timeout.connect(lambda: None)

    logger.info("TorProxy Manager запущен")
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
