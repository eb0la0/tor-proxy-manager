import logging
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QCheckBox,
    QFileDialog, QDialogButtonBox, QGroupBox, QMessageBox,
)

from gui import theme
from gui.widgets import Select
from core.config import (
    find_tor_exe, find_lyrebird_exe,
    get_windows_autostart, set_windows_autostart,
)
from core.i18n import tr, load_language, SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)



class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(580)
        self.setStyleSheet(theme.THEME)
        self._build_ui()
        self._load_values()

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(18, 18, 18, 18)

        # ---- Пути ----
        paths_group = QGroupBox(tr("settings.paths_group"))
        paths_layout = QGridLayout(paths_group)
        paths_layout.setSpacing(10)
        paths_layout.setColumnStretch(1, 1)

        paths_layout.addWidget(QLabel(tr("settings.tor_path_label")), 0, 0)
        row0 = QHBoxLayout()
        self._tor_path = QLineEdit()
        self._tor_path.setPlaceholderText(tr("settings.tor_path_placeholder"))
        row0.addWidget(self._tor_path)
        btn_tor = QPushButton(tr("btn.browse"))
        btn_tor.setFixedWidth(80)
        btn_tor.clicked.connect(lambda: self._browse(self._tor_path, "tor.exe (tor.exe)"))
        row0.addWidget(btn_tor)
        paths_layout.addLayout(row0, 0, 1)

        paths_layout.addWidget(QLabel(tr("settings.lyrebird_path_label")), 1, 0)
        row1 = QHBoxLayout()
        self._lyrebird_path = QLineEdit()
        self._lyrebird_path.setPlaceholderText(tr("settings.lyrebird_path_placeholder"))
        row1.addWidget(self._lyrebird_path)
        btn_lyre = QPushButton(tr("btn.browse"))
        btn_lyre.setFixedWidth(80)
        btn_lyre.clicked.connect(lambda: self._browse(self._lyrebird_path, "lyrebird.exe (lyrebird.exe)"))
        row1.addWidget(btn_lyre)
        paths_layout.addLayout(row1, 1, 1)

        btn_detect = QPushButton(tr("btn.auto_detect"))
        btn_detect.setMinimumWidth(200)
        btn_detect.clicked.connect(self._auto_detect)
        paths_layout.addWidget(btn_detect, 2, 0, 1, 2)

        layout.addWidget(paths_group)

        # ---- Параметры ----
        params_group = QGroupBox(tr("settings.params_group"))
        params_layout = QGridLayout(params_group)
        params_layout.setSpacing(10)
        params_layout.setColumnStretch(1, 1)

        params_layout.addWidget(QLabel(tr("settings.socks_port_label")), 0, 0)
        self._port = QSpinBox()
        self._port.setRange(1024, 65535)
        self._port.setFixedWidth(120)
        params_layout.addWidget(self._port, 0, 1, Qt.AlignLeft)

        params_layout.addWidget(QLabel(tr("settings.max_bridges_label")), 1, 0)
        self._max_bridges = QSpinBox()
        self._max_bridges.setRange(3, 50)
        self._max_bridges.setFixedWidth(120)
        params_layout.addWidget(self._max_bridges, 1, 1, Qt.AlignLeft)

        params_layout.addWidget(QLabel(tr("settings.timeout_label")), 2, 0)
        self._timeout = QSpinBox()
        self._timeout.setRange(1, 30)
        self._timeout.setFixedWidth(120)
        params_layout.addWidget(self._timeout, 2, 1, Qt.AlignLeft)

        params_layout.addWidget(QLabel(tr("settings.update_interval_label")), 3, 0)
        self._update_interval = QSpinBox()
        self._update_interval.setRange(1, 168)
        self._update_interval.setFixedWidth(120)
        params_layout.addWidget(self._update_interval, 3, 1, Qt.AlignLeft)

        layout.addWidget(params_group)

        # ---- Автозапуск ----
        startup_group = QGroupBox(tr("settings.startup_group"))
        startup_layout = QVBoxLayout(startup_group)
        startup_layout.setSpacing(8)

        self._autostart_windows = QCheckBox(tr("settings.autostart_label"))
        self._autostart_windows.setToolTip(tr("settings.autostart_hint"))
        startup_layout.addWidget(self._autostart_windows)

        hint = QLabel(tr("settings.autostart_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_MUTE}; font-size: {theme.FS_CAPTION}px;")
        startup_layout.addWidget(hint)

        layout.addWidget(startup_group)

        # ---- Язык ----
        lang_group = QGroupBox(tr("settings.language_label"))
        lang_layout = QHBoxLayout(lang_group)
        lang_layout.setSpacing(10)

        self._lang_combo = Select()
        self._lang_combo.setFixedWidth(160)
        for code, name in SUPPORTED_LANGUAGES.items():
            self._lang_combo.addItem(name, code)
        lang_layout.addWidget(self._lang_combo)
        lang_layout.addStretch()

        layout.addWidget(lang_group)

        # ---- Кнопки диалога ----
        # Версия живёт здесь, а не в шапке главного окна: там она была
        # метаданными без назначения.
        from gui.main_window import APP_VERSION
        ver_row = QHBoxLayout()
        ver = QLabel(tr("settings.version", v=APP_VERSION))
        ver.setStyleSheet(
            f"color: {theme.TEXT_MUTE}; font-size: {theme.FS_CAPTION}px;")
        ver_row.addWidget(ver)
        ver_row.addStretch()
        layout.addLayout(ver_row)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText(tr("btn.save"))
        btns.button(QDialogButtonBox.Cancel).setText(tr("btn.cancel"))
        btns.accepted.connect(self._save_and_close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------ helpers

    def _load_values(self):
        self._tor_path.setText(self.config.tor_exe)
        self._lyrebird_path.setText(self.config.lyrebird_exe)
        self._port.setValue(self.config.socks_port)
        self._max_bridges.setValue(self.config.max_bridges)
        self._timeout.setValue(self.config.test_timeout)
        self._update_interval.setValue(self.config.auto_update_hours)
        self._autostart_windows.setChecked(get_windows_autostart())
        # Выбираем сохранённый язык
        saved_lang = self.config.language
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == saved_lang:
                self._lang_combo.setCurrentIndex(i)
                break

    def _browse(self, target: QLineEdit, flt: str):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите файл", "", f"{flt};;Все файлы (*)")
        if path:
            target.setText(path)

    def _auto_detect(self):
        tor = find_tor_exe()
        lyre = find_lyrebird_exe()
        found = []
        if tor:
            self._tor_path.setText(tor)
            found.append(f"tor.exe: {tor}")
        if lyre:
            self._lyrebird_path.setText(lyre)
            found.append(f"lyrebird.exe: {lyre}")
        if not found:
            QMessageBox.information(
                self, tr("settings.autodetect_title"),
                tr("settings.autodetect_fail"),
            )
        else:
            QMessageBox.information(
                self, tr("settings.autodetect_title"),
                tr("settings.autodetect_success", paths="\n".join(found)),
            )

    def _save_and_close(self):
        new_lang = self._lang_combo.currentData()

        self.config.update({
            "tor_exe":            self._tor_path.text().strip(),
            "lyrebird_exe":       self._lyrebird_path.text().strip(),
            "socks_port":         self._port.value(),
            "max_bridges":        self._max_bridges.value(),
            "test_timeout":       self._timeout.value(),
            "auto_update_hours":  self._update_interval.value(),
            "language":           new_lang,
        })

        # Применяем язык немедленно — следующий tr() вызов уже использует новый
        load_language(new_lang)

        ok = set_windows_autostart(self._autostart_windows.isChecked())
        if self._autostart_windows.isChecked() and not ok:
            QMessageBox.warning(
                self, tr("settings.autostart_error_title"),
                tr("settings.autostart_error"),
            )

        self.accept()
