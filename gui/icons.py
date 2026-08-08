"""
Иконки, рисуемые кодом.

Ради полутора десятков глифов не стоит тащить в проект иконочный шрифт или
SVG-библиотеку: это лишние мегабайты в сборке и ещё одна зависимость.
Иконки рисуются QPainter в едином стиле — линейные, скруглённые концы,
одинаковая толщина штриха, вписаны в квадрат 24×24 и масштабируются.

Кэш нужен потому, что иконки перерисовываются на каждой смене состояния.
"""
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from gui import theme

_GRID = 24.0
_STROKE = 2.0
_cache: dict = {}


def _pen(color: str, scale: float, width: float = _STROKE) -> QPen:
    p = QPen(QColor(color))
    p.setWidthF(width * scale)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def _draw(name: str, p: QPainter, s: float, color: str):
    """Все координаты — в сетке 24×24, затем умножаются на масштаб s."""
    p.setPen(_pen(color, s))
    p.setBrush(Qt.NoBrush)

    def path(points, close=False):
        pp = QPainterPath()
        pp.moveTo(points[0][0] * s, points[0][1] * s)
        for x, y in points[1:]:
            pp.lineTo(x * s, y * s)
        if close:
            pp.closeSubpath()
        p.drawPath(pp)

    if name == "power":
        p.drawArc(QRectF(5 * s, 5 * s, 14 * s, 14 * s), -60 * 16, 300 * 16)
        path([(12, 3), (12, 11)])

    elif name == "copy":
        p.drawRoundedRect(QRectF(9 * s, 9 * s, 11 * s, 11 * s), 2.5 * s, 2.5 * s)
        path([(15, 5.5), (5.5, 5.5), (5.5, 15)])

    elif name == "refresh":
        p.drawArc(QRectF(4 * s, 4 * s, 16 * s, 16 * s), 40 * 16, 280 * 16)
        path([(20, 4), (20, 10), (14, 10)], close=True)

    elif name == "settings":
        p.drawEllipse(QPointF(12 * s, 12 * s), 3.2 * s, 3.2 * s)
        p.drawEllipse(QPointF(12 * s, 12 * s), 8.0 * s, 8.0 * s)
        path([(12, 2.2), (12, 5)])
        path([(12, 19), (12, 21.8)])

    elif name == "plus":
        path([(12, 5), (12, 19)])
        path([(5, 12), (19, 12)])

    elif name == "check":
        path([(5, 12.5), (10, 17.5), (19, 6.5)])

    elif name == "cross":
        path([(6.5, 6.5), (17.5, 17.5)])
        path([(17.5, 6.5), (6.5, 17.5)])

    elif name == "warning":
        path([(12, 4), (21, 19.5), (3, 19.5)], close=True)
        path([(12, 10), (12, 14)])
        p.drawPoint(QPointF(12 * s, 17 * s))

    elif name == "shield":
        path([(12, 3), (20, 6.2), (20, 12), (12, 21), (4, 12), (4, 6.2)], close=True)

    elif name == "chevron_right":
        path([(9.5, 5.5), (16, 12), (9.5, 18.5)])

    elif name == "chevron_down":
        path([(5.5, 9.5), (12, 16), (18.5, 9.5)])

    elif name == "play":
        pp = QPainterPath()
        pp.moveTo(8 * s, 5.5 * s)
        pp.lineTo(19 * s, 12 * s)
        pp.lineTo(8 * s, 18.5 * s)
        pp.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(pp)

    elif name == "stop":
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(7 * s, 7 * s, 10 * s, 10 * s), 2 * s, 2 * s)

    elif name == "trash":
        path([(4.5, 6.5), (19.5, 6.5)])
        path([(9, 6.5), (9, 4.2), (15, 4.2), (15, 6.5)])
        path([(6.5, 6.5), (7.6, 20), (16.4, 20), (17.5, 6.5)])

    elif name == "download":
        path([(12, 3.5), (12, 14.5)])
        path([(7.5, 10), (12, 14.5), (16.5, 10)])
        path([(4.5, 19.5), (19.5, 19.5)])

    elif name == "link":
        p.drawArc(QRectF(3 * s, 9 * s, 11 * s, 6 * s), 90 * 16, 180 * 16)
        p.drawArc(QRectF(10 * s, 9 * s, 11 * s, 6 * s), -90 * 16, 180 * 16)
        path([(8.5, 12), (15.5, 12)])


def pixmap(name: str, size: int = theme.ICON_MD, color: str = theme.TEXT) -> QPixmap:
    key = (name, size, color)
    if key in _cache:
        return _cache[key]

    ratio = 2                       # рисуем в 2× — резко на HiDPI
    px = QPixmap(size * ratio, size * ratio)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    _draw(name, p, size * ratio / _GRID, color)
    p.end()
    px.setDevicePixelRatio(ratio)

    _cache[key] = px
    return px


def icon(name: str, size: int = theme.ICON_MD, color: str = theme.TEXT) -> QIcon:
    return QIcon(pixmap(name, size, color))


def dot(color: str, size: int = 10, glow: bool = False) -> QPixmap:
    """
    Индикатор состояния. Небольшой, с мягким ореолом в активном состоянии —
    вместо крупных ярких кругов, которые перетягивают внимание на себя.
    """
    key = ("dot", color, size, glow)
    if key in _cache:
        return _cache[key]

    ratio = 2
    total = size * 3 if glow else size
    px = QPixmap(total * ratio, total * ratio)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)

    c = QColor(color)
    center = QPointF(total * ratio / 2, total * ratio / 2)
    if glow:
        halo = QColor(color)
        halo.setAlpha(38)
        p.setBrush(halo)
        p.drawEllipse(center, total * ratio / 2, total * ratio / 2)
        halo.setAlpha(70)
        p.setBrush(halo)
        p.drawEllipse(center, total * ratio / 3.2, total * ratio / 3.2)

    p.setBrush(c)
    p.drawEllipse(center, size * ratio / 2, size * ratio / 2)
    p.end()
    px.setDevicePixelRatio(ratio)

    _cache[key] = px
    return px
