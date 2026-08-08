"""
Диагностика последнего обновления мостов.

Технические подробности — статусы источников, зеркала, задержки, причины
отказа — нужны при разборе проблемы и мешают в обычной работе. Поэтому они
живут здесь, а на главном экране остаётся одна строка «4/4 источника».
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.i18n import current_language, tr
from gui import icons, theme
from gui.widgets import hline, label


def _grouped(n: int) -> str:
    """Разделитель разрядов по языку — как на главном экране."""
    g = f"{n:,}"
    return g if current_language() == "en" else g.replace(",", " ")


class DiagnosticsDialog(QDialog):
    """Разбор результата обновления: что ответило, что нет и как быстро."""

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("diag.title"))
        self.setStyleSheet(theme.THEME)
        self.setMinimumWidth(520)
        self._build(result)

    def _build(self, result):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_4)
        root.setSpacing(theme.SP_3)

        if result is None:
            root.addWidget(label(tr("diag.no_data"), "secondary"))
            self._add_buttons(root)
            return

        # Сводка одной строкой.
        ok = len(result.ok_providers)
        total = result.total_providers
        head = label(tr("diag.summary", ok=ok, total=total,
                        bridges=_grouped(len(result.bridges))),
                     "section")
        root.addWidget(head)
        root.addWidget(hline())

        # Заголовки таблицы.
        header = QHBoxLayout()
        header.setContentsMargins(theme.SP_2, 0, theme.SP_2, 0)
        header.addWidget(label(tr("diag.col_source"), "caption"), 3)
        header.addWidget(label(tr("diag.col_status"), "caption"), 2)
        header.addWidget(label(tr("diag.col_latency"), "caption"), 2)
        root.addLayout(header)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setMaximumHeight(320)
        body = QWidget()
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(2)

        # Источники в порядке приоритета — так же, как они сливаются.
        for s in sorted(result.sources, key=lambda x: -x.priority):
            rows.addWidget(self._row(s))
        rows.addStretch()

        area.setWidget(body)
        root.addWidget(area)

        if result.rejected:
            root.addWidget(label(tr("diag.rejected", n=result.rejected), "caption"))

        self._add_buttons(root)

    def _row(self, source) -> QFrame:
        frame = QFrame()
        frame.setObjectName("row")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(theme.SP_2, theme.SP_2, theme.SP_2, theme.SP_2)
        lay.setSpacing(theme.SP_2)

        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(label(source.name))
        # Хост показываем здесь, а не на главном экране: это техническая деталь.
        if source.host:
            left.addWidget(label(source.host, "caption"))
        holder = QWidget()
        holder.setLayout(left)
        lay.addWidget(holder, 3)

        if source.ok and source.empty:
            text, color, icon_name = tr("diag.status_empty"), theme.WARN, "warning"
        elif source.ok:
            text, color, icon_name = tr("diag.status_ok"), theme.OK, "check"
        else:
            text, color, icon_name = tr("diag.status_fail"), theme.ERR, "cross"

        status_box = QHBoxLayout()
        status_box.setSpacing(theme.SP_1)
        mark = QLabel()
        mark.setPixmap(icons.pixmap(icon_name, theme.ICON_SM, color))
        status_box.addWidget(mark)
        st = label(text)
        st.setStyleSheet(f"color: {color}; font-size: {theme.FS_SMALL}px;")
        status_box.addWidget(st)
        status_box.addStretch()
        sw = QWidget()
        sw.setLayout(status_box)
        lay.addWidget(sw, 2)

        latency = (f"{source.elapsed * 1000:.0f} ms"
                   if source.ok and source.elapsed else "—")
        lat = label(latency, "secondary")
        lat.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(lat, 2)

        # Причина отказа — только в подсказке, чтобы не ломать колонки.
        if not source.ok and source.error:
            frame.setToolTip(source.error)
        return frame

    def _add_buttons(self, root):
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).setText(tr("btn.close"))
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        root.addWidget(btns)
