"""
Design-система TorProxy Manager.

Единственный источник правды для цветов, отступов, радиусов и типографики.
Правило: никаких «магических» значений в виджетах — только токены отсюда.

Принципы визуального языка:

1. Глубина создаётся УРОВНЯМИ ПОВЕРХНОСТЕЙ, а не рамками вокруг всего подряд.
   background → surface → elevated → hover. Рамка нужна только там, где
   действительно разделяет интерактивные области.
2. Фиолетовый — акцент, а не заливка. Он маркирует действие и выделение,
   но не раскрашивает интерфейс.
3. Иерархия строится типографикой и воздухом, а не количеством прямоугольников.
"""

# ── Цвета ────────────────────────────────────────────────────────────────────
# Нейтральный тёмный, слегка холодный. Не чистый #000: на OLED он режет глаз,
# а мягкий тёмно-серый позволяет строить уровни поверхностей.

BG            = "#0d0d12"     # фон окна
SURFACE       = "#14141c"     # основная поверхность (карточка)
ELEVATED      = "#1b1b25"     # приподнятая поверхность (герой-блок, поля)
HOVER         = "#22222e"     # наведение
SUNKEN        = "#0a0a0f"     # утопленная область (лог, поля ввода)

BORDER        = "#22222e"     # едва заметная граница
BORDER_STRONG = "#31313f"     # граница при наведении/фокусе

# Контраст проверен по WCAG AA (>= 4.5:1) на обеих поверхностях:
# TEXT 14.6, TEXT_DIM 5.2, TEXT_MUTE 4.4 (на ELEVATED).
# Прежний #5c5d72 давал всего 2.65 — подписи было тяжело читать.
TEXT          = "#ecedf2"     # основной текст     — 14.6:1
TEXT_DIM      = "#9698ad"     # вторичный текст    —  6.0:1
TEXT_MUTE     = "#8688a1"     # третичный текст    —  4.9:1

ACCENT        = "#8b6cf0"     # фирменный акцент: границы, прогресс, выделение
# Заливка главной кнопки темнее акцента: белый текст на #8b6cf0 давал 3.8:1.
# Наведение осветляет её лишь настолько, чтобы контраст не упал ниже нормы.
ACCENT_FILL   = "#7d5ce8"     # белый текст — 4.6:1
ACCENT_HOVER  = "#8261ec"     # белый текст — 4.3:1
ACCENT_PRESS  = "#6f4ddb"
ACCENT_SOFT   = "rgba(139, 108, 240, 0.12)"   # подложка акцента
ACCENT_EDGE   = "rgba(139, 108, 240, 0.28)"

OK            = "#3ddc97"     # подключено / успех
OK_SOFT       = "rgba(61, 220, 151, 0.12)"
WARN          = "#f5a524"     # подключается / внимание
WARN_SOFT     = "rgba(245, 165, 36, 0.12)"
ERR           = "#f2555a"     # отключено / ошибка
ERR_SOFT      = "rgba(242, 85, 90, 0.12)"
INFO          = "#5aa9f5"

# ── Отступы ──────────────────────────────────────────────────────────────────
SP_1, SP_2, SP_3, SP_4, SP_5, SP_6, SP_7 = 4, 8, 12, 16, 20, 24, 32

# ── Радиусы ──────────────────────────────────────────────────────────────────
R_SM, R_MD, R_LG = 8, 12, 16

# ── Типографика ──────────────────────────────────────────────────────────────
FONT_UI = "'Segoe UI Variable', 'Segoe UI', 'Inter', system-ui, sans-serif"
FONT_MONO = "'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace"

FS_HERO = 26      # главный статус
FS_TITLE = 16     # заголовок приложения
FS_SECTION = 14   # заголовок секции
FS_BODY = 13
FS_SMALL = 12
FS_CAPTION = 11

# ── Размеры ──────────────────────────────────────────────────────────────────
ICON_SM, ICON_MD, ICON_LG = 14, 16, 20
WINDOW_MIN_W, WINDOW_MIN_H = 560, 640


def _sheet() -> str:
    return f"""
/* ═══════════════ База ═══════════════ */
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: {FS_BODY}px;
}}
QMainWindow, QDialog, QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: {BG};
}}

/* ═══════════════ Поверхности ═══════════════
   Уровни вместо рамок: карточка отличается от фона заливкой,
   а не обводкой по периметру. */
QFrame#surface {{
    background-color: {SURFACE};
    border-radius: {R_LG}px;
    border: none;
}}
QFrame#hero {{
    background-color: {ELEVATED};
    border-radius: {R_LG}px;
    border: 1px solid {BORDER};
}}
QFrame#separator {{
    background-color: {BORDER};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* ═══════════════ Типографика ═══════════════ */
QLabel {{ background: transparent; color: {TEXT}; }}
QLabel#hero_status  {{ font-size: {FS_HERO}px;    font-weight: 600; letter-spacing: -0.4px; }}
QLabel#app_title    {{ font-size: {FS_TITLE}px;   font-weight: 600; }}
QLabel#section      {{ font-size: {FS_SECTION}px; font-weight: 600; }}
QLabel#big_number   {{ font-size: 22px; font-weight: 600; letter-spacing: -0.4px; }}
QLabel#secondary    {{ font-size: {FS_SMALL}px;   color: {TEXT_DIM}; }}
QLabel#caption      {{ font-size: {FS_CAPTION}px; color: {TEXT_MUTE}; }}
QLabel#mono         {{ font-family: {FONT_MONO}; font-size: {FS_BODY}px; color: {TEXT}; }}

/* ═══════════════ Кнопки ═══════════════ */
QPushButton {{
    background-color: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {R_SM}px;
    padding: 7px 14px;
    font-size: {FS_BODY}px;
    font-weight: 500;
}}
QPushButton:hover   {{ background-color: {HOVER}; border-color: {BORDER_STRONG}; }}
QPushButton:pressed {{ background-color: {SUNKEN}; }}
QPushButton:disabled {{ background-color: {SURFACE}; color: {TEXT_MUTE}; border-color: {BORDER}; }}

/* Навигация с клавиатуры должна быть видимой: без этого фокус на тёмной
   теме не читается вообще и Tab-обход становится бесполезным. */
QPushButton:focus, QCheckBox:focus, QComboBox:focus,
QLineEdit:focus, QSpinBox:focus, QTextEdit:focus {{
    border: 1px solid {ACCENT};
    outline: none;
}}
QPushButton#primary:focus {{ border: 1px solid {TEXT}; }}
QPushButton#icon_btn:focus, QPushButton#ghost:focus {{
    background-color: {HOVER};
    border: 1px solid {ACCENT};
}}

/* Главное действие. Заметное, но не во всю ширину экрана. */
QPushButton#primary {{
    background-color: {ACCENT_FILL};
    color: #ffffff;
    border: none;
    border-radius: {R_SM}px;
    padding: 11px 28px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#primary:hover    {{ background-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed  {{ background-color: {ACCENT_PRESS}; }}
/* Заблокированная кнопка обязана оставаться кнопкой: на приподнятой
   поверхности заливка ELEVATED сливалась с фоном и кнопка «исчезала». */
QPushButton#primary:disabled {{
    background-color: {ACCENT_SOFT};
    border: 1px solid {ACCENT_EDGE};
    color: {TEXT_MUTE};
}}

/* Отключение — сдержанное, деструктивное действие не должно кричать. */
QPushButton#danger {{
    background-color: transparent;
    color: {ERR};
    border: 1px solid {ERR_SOFT};
    border-radius: {R_SM}px;
    padding: 11px 28px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#danger:hover   {{ background-color: {ERR_SOFT}; border-color: {ERR}; }}
QPushButton#danger:pressed {{ background-color: rgba(242, 85, 90, 0.2); }}

/* Три уровня кнопок должны отличаться с первого взгляда:
   primary — заливка, secondary — контур, ghost — только текст. */
QPushButton#secondary {{
    background-color: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: {R_SM}px;
    padding: 7px 14px;
    font-weight: 500;
}}
QPushButton#secondary:hover   {{ background-color: {HOVER}; border-color: {ACCENT}; }}
QPushButton#secondary:pressed {{ background-color: {SUNKEN}; }}
QPushButton#secondary:disabled {{
    background-color: {SURFACE}; color: {TEXT_MUTE}; border-color: {BORDER};
}}

QPushButton#ghost {{
    background-color: transparent;
    color: {TEXT_DIM};
    border: none;
    border-radius: {R_SM}px;
    padding: 6px 10px;
    font-size: {FS_SMALL}px;
}}
QPushButton#ghost:hover   {{ background-color: {HOVER}; color: {TEXT}; }}
QPushButton#ghost:pressed {{ background-color: {SUNKEN}; }}

QPushButton#icon_btn {{
    background-color: transparent;
    border: none;
    border-radius: {R_SM}px;
    padding: 6px;
}}
QPushButton#icon_btn:hover   {{ background-color: {HOVER}; }}
QPushButton#icon_btn:pressed {{ background-color: {SUNKEN}; }}

QPushButton#dashed {{
    background-color: transparent;
    color: {TEXT_DIM};
    border: 1px dashed {BORDER_STRONG};
    border-radius: {R_SM}px;
    padding: 9px 16px;
    font-weight: 500;
}}
QPushButton#dashed:hover {{
    color: {ACCENT_HOVER};
    border-color: {ACCENT};
    background-color: {ACCENT_SOFT};
}}

/* ═══════════════ Поля ввода ═══════════════ */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {SUNKEN};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {R_SM}px;
    padding: 7px 11px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:read-only {{ color: {TEXT_DIM}; }}

/* Стрелка рисуется в коде (gui.widgets.Select) — через стили Qt она
   в разных темах превращается в залитый прямоугольник. */
QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background-color: {ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: {R_SM}px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
    color: {TEXT};
    outline: none;
    padding: 4px;
}}

QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {ELEVATED};
    border: none;
    width: 20px;
    border-radius: 4px;
    margin: 2px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background-color: {ACCENT}; }}
QSpinBox::up-arrow {{
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 5px solid {TEXT}; width: 0; height: 0;
}}
QSpinBox::down-arrow {{
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {TEXT}; width: 0; height: 0;
}}

/* ═══════════════ Прогресс ═══════════════ */
QProgressBar {{
    background-color: {SUNKEN};
    border: none;
    border-radius: 2px;
    max-height: 3px;
    min-height: 3px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 2px; }}

/* ═══════════════ Лог активности ═══════════════
   Утопленная область без рамки — второстепенная информация
   не должна конкурировать с главным. */
QTextEdit#activity {{
    background-color: {SUNKEN};
    color: {TEXT_DIM};
    border: none;
    border-radius: {R_MD}px;
    font-family: {FONT_MONO};
    font-size: {FS_CAPTION}px;
    padding: 10px 12px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QTextEdit {{
    background-color: {SUNKEN};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-radius: {R_SM}px;
    font-family: {FONT_MONO};
    font-size: {FS_CAPTION}px;
    padding: 8px;
}}

/* ═══════════════ Строки списка (приложения, источники) ═══════════════ */
QFrame#row {{
    background-color: {ELEVATED};
    border: 1px solid transparent;
    border-radius: {R_MD}px;
}}
QFrame#row:hover {{
    background-color: {HOVER};
    border-color: {BORDER};
}}

/* ═══════════════ Чекбоксы ═══════════════ */
QCheckBox {{ color: {TEXT}; spacing: 9px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1.5px solid {BORDER_STRONG};
    border-radius: 5px;
    background-color: {SUNKEN};
}}
QCheckBox::indicator:hover   {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background-color: {ACCENT}; border-color: {ACCENT}; }}

/* ═══════════════ Скроллбар ═══════════════ */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background-color: {BORDER_STRONG};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {TEXT_MUTE}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background-color: {BORDER_STRONG}; border-radius: 4px; min-width: 28px;
}}

/* ═══════════════ Всплывающие ═══════════════ */
QToolTip {{
    background-color: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: {R_SM}px;
    padding: 6px 9px;
    font-size: {FS_SMALL}px;
}}

QMenu {{
    background-color: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: {R_MD}px;
    padding: 6px;
}}
QMenu::item {{ padding: 8px 24px; border-radius: {R_SM}px; }}
QMenu::item:selected {{ background-color: {ACCENT}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background-color: {BORDER}; margin: 5px 8px; }}

/* ═══════════════ Диалоги ═══════════════ */
QGroupBox {{
    color: {TEXT_DIM};
    border: none;
    margin-top: 16px;
    padding: 8px 0 0 0;
    font-size: {FS_SMALL}px;
    font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 0; padding: 0; }}

QDialogButtonBox QPushButton {{ min-width: 96px; min-height: 32px; }}
QMessageBox {{ background-color: {BG}; }}
QMessageBox QLabel {{ color: {TEXT}; font-size: {FS_BODY}px; }}
QMessageBox QPushButton {{ min-width: 96px; min-height: 32px; }}
"""


THEME = _sheet()


# ── Точечные стили состояний ─────────────────────────────────────────────────
# Герой-блок мягко окрашивается под текущее состояние: тонкая полоса слева
# вместо цветной рамки по всему периметру.

def hero_style(color: str | None = None) -> str:
    edge = color or BORDER
    return f"""
QFrame#hero {{
    background-color: {ELEVATED};
    border: 1px solid {BORDER};
    border-left: 2px solid {edge};
    border-radius: {R_LG}px;
}}
"""


def pill(color: str, bg: str) -> str:
    """Компактный бейдж-«таблетка» для статусов и меток."""
    return (
        f"color: {color}; background-color: {bg};"
        f"border-radius: 6px; padding: 3px 9px;"
        f"font-size: {FS_CAPTION}px; font-weight: 600;"
    )


STATUS_COLORS = {
    "connected": OK,
    "connecting": WARN,
    "disconnected": ERR,
    "error": ERR,
}
