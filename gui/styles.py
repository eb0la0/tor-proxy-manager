"""
TorProxy Manager — Modern Dark UI Theme.
Refined palette, glassmorphism-inspired cards, smooth transitions.
"""

# ── Palette ──
_BG        = "#0f0f1a"      # deep background
_BG_CARD   = "#161625"      # card background
_BG_INPUT  = "#0c0c18"      # input fields
_BG_HOVER  = "#1c1c35"      # hover state

_BORDER    = "#252540"       # subtle border
_BORDER_LT = "#303055"       # lighter border (hover)

_TEXT      = "#e8e8f0"       # primary text
_TEXT_DIM  = "#6a6a8a"       # secondary text
_TEXT_MUTE = "#44445a"       # muted text

_ACCENT    = "#7c5cbf"       # primary accent (purple)
_ACCENT_LT = "#9370db"       # lighter accent
_ACCENT_DK = "#5a3d99"       # darker accent

_GREEN     = "#00d4aa"       # connected / success
_GREEN_DK  = "#00a888"
_RED       = "#ff4757"       # disconnected / error
_RED_DK    = "#cc3344"
_ORANGE    = "#ffa502"       # connecting / warning
_BLUE      = "#4a9eff"       # info accent


DARK_THEME = f"""
/* ===== Global ===== */
QWidget {{
    background-color: {_BG};
    color: {_TEXT};
    font-family: 'Segoe UI', 'SF Pro Display', Arial, sans-serif;
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {_BG};
}}

/* ===== Cards (QFrame#card) ===== */
QFrame#card {{
    background-color: {_BG_CARD};
    border-radius: 12px;
    border: 1px solid {_BORDER};
}}
QFrame#card:hover {{
    border-color: {_BORDER_LT};
}}

/* ===== Section headers (QGroupBox) ===== */
QGroupBox {{
    color: {_TEXT_DIM};
    border: 1px solid {_BORDER};
    border-radius: 12px;
    margin-top: 18px;
    padding: 14px 12px 10px 12px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: {_TEXT_DIM};
}}

/* ===== Buttons ===== */
QPushButton {{
    background-color: {_BG_CARD};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {_BG_HOVER};
    border-color: {_BORDER_LT};
}}
QPushButton:pressed {{
    background-color: {_BG_INPUT};
}}
QPushButton:disabled {{
    background-color: {_BG_INPUT};
    color: {_TEXT_MUTE};
    border-color: {_BORDER};
}}

/* -- Primary action: Connect -- */
QPushButton#btn_connect {{
    background-color: {_GREEN};
    color: #0a0a15;
    font-size: 14px;
    font-weight: 700;
    padding: 13px 36px;
    border-radius: 10px;
    border: none;
    letter-spacing: 0.8px;
}}
QPushButton#btn_connect:hover   {{ background-color: #00e8bb; }}
QPushButton#btn_connect:pressed {{ background-color: {_GREEN_DK}; }}
QPushButton#btn_connect:disabled {{ background-color: #1a2a25; color: #3a5a4a; border: none; }}

QPushButton#btn_disconnect {{
    background-color: {_RED};
    color: white;
    font-size: 14px;
    font-weight: 700;
    padding: 13px 36px;
    border-radius: 10px;
    border: none;
    letter-spacing: 0.8px;
}}
QPushButton#btn_disconnect:hover   {{ background-color: #ff6b7a; }}
QPushButton#btn_disconnect:pressed {{ background-color: {_RED_DK}; }}

/* -- Update button -- */
QPushButton#btn_update {{
    background-color: {_ACCENT};
    color: white;
    padding: 8px 20px;
    border-radius: 8px;
    border: none;
    font-weight: 600;
}}
QPushButton#btn_update:hover   {{ background-color: {_ACCENT_LT}; }}
QPushButton#btn_update:pressed {{ background-color: {_ACCENT_DK}; }}
QPushButton#btn_update:disabled {{ background-color: #2a2040; color: #5a4a70; border: none; }}

/* -- Settings button -- */
QPushButton#btn_settings {{
    background-color: transparent;
    color: {_TEXT_DIM};
    border: 1px solid {_BORDER};
    padding: 8px 20px;
    border-radius: 8px;
}}
QPushButton#btn_settings:hover {{
    background-color: {_BG_CARD};
    color: {_TEXT};
    border-color: {_BORDER_LT};
}}

/* -- Add app button -- */
QPushButton#btn_add_app {{
    background-color: transparent;
    color: {_ACCENT_LT};
    border: 1px dashed {_ACCENT_DK};
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
}}
QPushButton#btn_add_app:hover {{
    background-color: rgba(124, 92, 191, 0.1);
    border-style: solid;
    color: {_ACCENT_LT};
}}

/* ===== Inputs ===== */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {_BG_INPUT};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: {_ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {_ACCENT};
}}
QLineEdit:read-only {{ color: {_TEXT_DIM}; }}

QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {_BG_CARD};
    border: 1px solid {_BORDER};
    width: 24px;
    border-radius: 4px;
    margin: 1px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {_ACCENT_DK};
    border-color: {_ACCENT};
}}
QSpinBox::up-arrow {{
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-bottom: 6px solid {_TEXT};
    width: 0; height: 0;
}}
QSpinBox::up-arrow:hover {{
    border-bottom-color: white;
}}
QSpinBox::down-arrow {{
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {_TEXT};
    width: 0; height: 0;
}}
QSpinBox::down-arrow:hover {{
    border-top-color: white;
}}

QComboBox::drop-down   {{ border: none; width: 28px; }}
QComboBox::down-arrow  {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {_TEXT_DIM};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {_BG_INPUT};
    border: 1px solid {_BORDER};
    selection-background-color: {_ACCENT_DK};
    color: {_TEXT};
    outline: none;
    border-radius: 8px;
}}

/* ===== Progress bar ===== */
QProgressBar {{
    background-color: {_BG_INPUT};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {_ACCENT};
    border-radius: 4px;
}}

/* ===== Text areas (logs) ===== */
QTextEdit {{
    background-color: {_BG_INPUT};
    color: {_TEXT_DIM};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
    padding: 8px;
    selection-background-color: {_ACCENT_DK};
}}

/* ===== Labels ===== */
QLabel {{ color: {_TEXT}; background: transparent; }}
QLabel#lbl_title   {{ font-size: 18px; font-weight: 700; color: {_TEXT}; }}
QLabel#lbl_version {{ font-size: 10px; color: {_TEXT_MUTE}; font-weight: 500; letter-spacing: 0.5px; }}
QLabel#lbl_secondary {{ font-size: 11px; color: {_TEXT_DIM}; }}

/* ===== Checkbox ===== */
QCheckBox {{ color: {_TEXT}; spacing: 10px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 2px solid {_BORDER};
    border-radius: 4px;
    background-color: {_BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {_ACCENT};
    border-color: {_ACCENT};
}}
QCheckBox::indicator:hover {{
    border-color: {_ACCENT_LT};
}}

/* ===== Scrollbars ===== */
QScrollBar:vertical {{
    background-color: transparent;
    width: 6px;
    margin: 4px 0;
}}
QScrollBar::handle:vertical {{
    background-color: {_BORDER};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {_ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 6px;
    margin: 0 4px;
}}
QScrollBar::handle:horizontal {{
    background-color: {_BORDER};
    border-radius: 3px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {_ACCENT}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ===== Tooltips ===== */
QToolTip {{
    background-color: {_BG_CARD};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* ===== Tray menu ===== */
QMenu {{
    background-color: {_BG_CARD};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{ padding: 8px 28px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {_ACCENT_DK}; }}
QMenu::separator {{
    height: 1px;
    background-color: {_BORDER};
    margin: 4px 10px;
}}

/* ===== Dialog buttons ===== */
QDialogButtonBox QPushButton {{
    min-width: 100px;
    min-height: 32px;
    padding: 6px 20px;
}}

/* ===== Message boxes ===== */
QMessageBox {{ background-color: {_BG}; }}
QMessageBox QLabel {{ color: {_TEXT}; }}
QMessageBox QPushButton {{ min-width: 100px; min-height: 32px; }}

/* ===== App proxy rows ===== */
QFrame#app_row {{
    background-color: {_BG_CARD};
    border: 1px solid {_BORDER};
    border-radius: 10px;
}}
QFrame#app_row:hover {{
    border-color: {_BORDER_LT};
    background-color: {_BG_HOVER};
}}
"""

# ── Button variant stylesheets (applied via setStyleSheet) ──

BTN_CONNECT_STYLE = f"""
QPushButton {{
    background-color: {_GREEN};
    color: #0a0a15;
    font-size: 14px;
    font-weight: 700;
    padding: 13px 36px;
    border-radius: 10px;
    border: none;
    letter-spacing: 0.8px;
}}
QPushButton:hover    {{ background-color: #00e8bb; }}
QPushButton:pressed  {{ background-color: {_GREEN_DK}; }}
QPushButton:disabled {{ background-color: #1a2a25; color: #3a5a4a; border: none; }}
"""

BTN_DISCONNECT_STYLE = f"""
QPushButton {{
    background-color: {_RED};
    color: white;
    font-size: 14px;
    font-weight: 700;
    padding: 13px 36px;
    border-radius: 10px;
    border: none;
    letter-spacing: 0.8px;
}}
QPushButton:hover    {{ background-color: #ff6b7a; }}
QPushButton:pressed  {{ background-color: {_RED_DK}; }}
QPushButton:disabled {{ background-color: #2a1520; color: #5a3040; border: none; }}
"""

BTN_CONNECTING_STYLE = f"""
QPushButton {{
    background-color: {_ORANGE};
    color: #0a0a15;
    font-size: 14px;
    font-weight: 700;
    padding: 13px 36px;
    border-radius: 10px;
    border: none;
    letter-spacing: 0.8px;
}}
QPushButton:disabled {{ background-color: #2a2010; color: #5a4a20; border: none; }}
"""

# ── Card state stylesheets ──

CARD_DEFAULT = f"""
QFrame#card {{
    background-color: {_BG_CARD};
    border-radius: 12px;
    border: 1px solid {_BORDER};
}}
"""

CARD_CONNECTED = f"""
QFrame#card {{
    background-color: {_BG_CARD};
    border-radius: 12px;
    border: 1px solid rgba(0, 212, 170, 0.3);
    border-left: 3px solid {_GREEN};
}}
"""

CARD_CONNECTING = f"""
QFrame#card {{
    background-color: {_BG_CARD};
    border-radius: 12px;
    border: 1px solid rgba(255, 165, 2, 0.3);
    border-left: 3px solid {_ORANGE};
}}
"""

# ── App row styles ──

APP_ROW_STYLE = f"""
QFrame#app_row {{
    background-color: {_BG_CARD};
    border: 1px solid {_BORDER};
    border-radius: 10px;
    padding: 2px;
}}
QFrame#app_row:hover {{
    border-color: {_BORDER_LT};
    background-color: {_BG_HOVER};
}}
"""

APP_ROW_RUNNING_BTN = f"""
QPushButton {{
    background: {_RED};
    color: white;
    border-radius: 8px;
    padding: 6px 14px;
    border: none;
    font-weight: 600;
}}
QPushButton:hover {{ background: #ff6b7a; }}
"""

APP_ROW_LAUNCH_BTN = f"""
QPushButton {{
    background: {_BG_CARD};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background: {_BG_HOVER};
    border-color: {_BORDER_LT};
}}
"""

# ── Badge styles ──

BADGE_SOCKS = f"""
    color: {_ACCENT_LT};
    font-weight: 700;
    font-size: 9px;
    background: rgba(124, 92, 191, 0.15);
    border: 1px solid rgba(124, 92, 191, 0.3);
    border-radius: 4px;
    padding: 2px 8px;
    letter-spacing: 0.5px;
"""

BADGE_METHOD = f"""
    color: {_ACCENT_LT};
    font-size: 10px;
    font-weight: 600;
    background: rgba(124, 92, 191, 0.1);
    border: 1px solid rgba(124, 92, 191, 0.2);
    border-radius: 4px;
    padding: 2px 8px;
"""

# ── Status colors (for dot_pixmap) ──

COLOR_CONNECTED   = _GREEN
COLOR_DISCONNECTED = _RED
COLOR_CONNECTING  = _ORANGE
COLOR_ACCENT      = _ACCENT


def dot_pixmap(color: str, size: int = 12):
    """Цветной кружок-индикатор — используется в статусе и списке приложений."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QColor, QBrush, QPainter, QPixmap
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return pix
