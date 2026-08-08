"""
Переиспользуемые элементы интерфейса.

Интерфейс собирается из небольшого набора блоков, а не из уникальных
QFrame под каждую задачу. Это то, что делает разные экраны похожими друг
на друга без копирования стилей.
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from gui import icons, theme


class Select(QComboBox):
    """
    Выпадающий список с нарисованной стрелкой.

    Через стили Qt стрелку надёжно не задать: приём с border-треугольником
    в разных стилях отрисовывается как залитый прямоугольник. Рисуем сами —
    получается одинаково на любой платформе и в одном стиле с прочими иконками.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        px = icons.pixmap("chevron_down", 12, theme.TEXT_DIM)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        x = self.width() - 12 - 11
        y = (self.height() - 12) // 2
        p.drawPixmap(x, y, px)
        p.end()


def hline() -> QFrame:
    """Волосяной разделитель — замена рамке вокруг каждого блока."""
    line = QFrame()
    line.setObjectName("separator")
    line.setFixedHeight(1)
    return line


def label(text: str = "", role: str = "", color: str = "") -> QLabel:
    """
    role — имя из стилей темы: secondary / caption / section / mono /
    app_title / hero_status / big_number.
    """
    lbl = QLabel(text)
    if role:
        lbl.setObjectName(role)
    if color:
        lbl.setStyleSheet(f"color: {color};")
    return lbl


def icon_button(name: str, tooltip: str = "", size: int = theme.ICON_MD,
                color: str = theme.TEXT_DIM) -> QPushButton:
    btn = QPushButton()
    btn.setObjectName("icon_btn")
    btn.setIcon(icons.icon(name, size, color))
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFlat(True)
    btn.setFixedSize(size + 14, size + 14)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def text_button(text: str, icon_name: str = "", object_name: str = "ghost",
                color: str = theme.TEXT_DIM) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName(object_name)
    btn.setCursor(Qt.PointingHandCursor)
    if icon_name:
        btn.setIcon(icons.icon(icon_name, theme.ICON_SM, color))
    return btn


class Card(QFrame):
    """
    Плоская поверхность-секция.

    Заголовок — часть карточки, а не подпись, висящая снаружи: так секция
    читается как единый объект и не требует обводки, чтобы «собраться».
    """

    def __init__(self, title: str = "", elevated: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("hero" if elevated else "surface")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(theme.SP_5, theme.SP_4, theme.SP_5, theme.SP_4)
        self._root.setSpacing(theme.SP_3)

        self._header = QHBoxLayout()
        self._header.setSpacing(theme.SP_2)
        self.title_label = label(title, "section")
        self._header.addWidget(self.title_label)
        self._header.addStretch()
        if title:
            self._root.addLayout(self._header)

        self.body = QVBoxLayout()
        self.body.setSpacing(theme.SP_3)
        self._root.addLayout(self.body)

    def add_header_widget(self, widget: QWidget):
        """Правый край строки заголовка — для счётчиков и действий секции."""
        self._header.addWidget(widget)

    def add(self, widget: QWidget):
        self.body.addWidget(widget)

    def add_layout(self, lay):
        self.body.addLayout(lay)


class ResponsiveRow(QWidget):
    """
    Два блока рядом на широком окне и друг под другом на узком.

    Вертикальный столбец из одинаковых карточек — главная причина, по которой
    интерфейс выглядел «стопкой блоков», а окно приходилось делать высоким.
    Ширины на 900 px хватает на две колонки, и dashboard перестаёт быть лентой.
    """

    def __init__(self, breakpoint: int = 800, parent=None):
        super().__init__(parent)
        self._breakpoint = breakpoint
        self._two_columns: bool | None = None

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(theme.SP_3)
        self._grid.setVerticalSpacing(theme.SP_3)
        self._left = None
        self._right = None

    def set_widgets(self, left: QWidget, right: QWidget):
        self._left, self._right = left, right
        self._relayout(force=True)

    def _relayout(self, force: bool = False):
        if self._left is None or self._right is None:
            return
        wide = self.width() >= self._breakpoint
        if not force and wide == self._two_columns:
            return
        self._two_columns = wide

        self._grid.removeWidget(self._left)
        self._grid.removeWidget(self._right)
        if wide:
            self._grid.addWidget(self._left, 0, 0)
            self._grid.addWidget(self._right, 0, 1)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 1)
        else:
            self._grid.addWidget(self._left, 0, 0)
            self._grid.addWidget(self._right, 1, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()


class StatusPill(QLabel):
    """Компактный бейдж состояния: точка + подпись."""

    def __init__(self, text: str = "", color: str = theme.TEXT_DIM,
                 bg: str = "transparent", parent=None):
        super().__init__(text, parent)
        self.set_state(text, color, bg)

    def set_state(self, text: str, color: str, bg: str = "transparent"):
        self.setText(text)
        self.setStyleSheet(theme.pill(color, bg))


class Disclosure(QWidget):
    """
    Сворачиваемая секция «подробности».

    Технические детали не удаляются из интерфейса, а убираются на второй план:
    обычному пользователю они не нужны, при диагностике — нужны сразу.
    """

    toggled_open = pyqtSignal(bool)

    def __init__(self, summary: str = "", parent=None):
        super().__init__(parent)
        self._open = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SP_2)

        # Иконка Qt по умолчанию рисуется слева от текста — это и нужно.
        # Флаг RightToLeft здесь всё зеркалил и уводил блок к правому краю.
        self._btn = QPushButton()
        self._btn.setObjectName("ghost")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._btn.clicked.connect(self.toggle)
        root.addWidget(self._btn, 0, Qt.AlignLeft)

        self._content = QWidget()
        self.content_layout = QVBoxLayout(self._content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(theme.SP_1)
        self._content.setVisible(False)
        root.addWidget(self._content)

        self._summary = summary
        self._refresh()

    def set_summary(self, text: str):
        self._summary = text
        self._refresh()

    def _refresh(self):
        self._btn.setText(f" {self._summary}")
        self._btn.setIcon(icons.icon(
            "chevron_down" if self._open else "chevron_right",
            theme.ICON_SM, theme.TEXT_MUTE))

    def toggle(self):
        self.set_open(not self._open)

    def set_open(self, is_open: bool):
        self._open = is_open
        self._content.setVisible(is_open)
        self._refresh()
        self.toggled_open.emit(is_open)

    def is_open(self) -> bool:
        return self._open

    def clear(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def add(self, widget: QWidget):
        self.content_layout.addWidget(widget)


class SourceRow(QFrame):
    """Строка состояния одного поставщика мостов внутри Disclosure."""

    def __init__(self, name: str, ok: bool, detail: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SP_2, theme.SP_1, theme.SP_2, theme.SP_1)
        lay.setSpacing(theme.SP_2)

        mark = QLabel()
        mark.setPixmap(icons.pixmap(
            "check" if ok else "cross", theme.ICON_SM,
            theme.OK if ok else theme.TEXT_MUTE))
        lay.addWidget(mark)

        name_lbl = label(name, "secondary")
        name_lbl.setStyleSheet(
            f"font-size: {theme.FS_SMALL}px;"
            f"color: {theme.TEXT if ok else theme.TEXT_MUTE};"
        )
        lay.addWidget(name_lbl)
        lay.addStretch()

        if detail:
            lay.addWidget(label(detail, "caption"))


class EmptyState(QWidget):
    """Пустое состояние: объяснение и одно очевидное действие."""

    def __init__(self, title: str, hint: str = "", parent=None):
        super().__init__(parent)
        # Высота задаётся содержимым: фиксированная центровка накладывала
        # подпись на заголовок, когда текст переносился на две строки.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, theme.SP_3, 0, theme.SP_3)
        lay.setSpacing(theme.SP_1)

        t = label(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FS_BODY}px;")
        lay.addWidget(t)

        if hint:
            h = label(hint, "caption")
            h.setAlignment(Qt.AlignCenter)
            h.setWordWrap(True)
            h.setMinimumHeight(h.fontMetrics().height() + 2)
            lay.addWidget(h)

        self.action_slot = QHBoxLayout()
        self.action_slot.setAlignment(Qt.AlignCenter)
        lay.addLayout(self.action_slot)

    def set_action(self, button: QPushButton):
        self.action_slot.addWidget(button)
