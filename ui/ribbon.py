"""Лента (ribbon) главного окна: собственные иконки и вкладки с группами.
Правило этапа 12: каждое действие — один QAction и одно место в ленте (Ribbon.places)."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QPen, QColor, QIcon, QPixmap, QFont, QAction
from PyQt6.QtWidgets import (QMenu, QTabWidget, QWidget, QHBoxLayout, QVBoxLayout, QToolButton, QLabel, QFrame,
                             QScrollArea, QWidgetAction, QSizePolicy)

ACCENT = "#2E7D6B"
TABS = ["Файл", "Главная", "Рисование", "Редактировать", "Просмотр", "База данных", "Помощь"]


def glyph(kind, size=32):
    """Собственные простые пиктограммы (QPainter)."""
    pm = QPixmap(size, size); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(ACCENT); p.setPen(QPen(c, 2)); s = size
    if kind in ("save", "new", "open", "print", "export", "import"):
        p.drawRoundedRect(6, 4, s-12, s-8, 3, 3)
        if kind == "save": p.fillRect(10, 6, s-20, 8, c)
        if kind == "print": p.fillRect(8, s//2, s-16, 6, c)
        if kind in ("open", "import"): p.drawLine(s//2, 8, s//2, s-10); p.drawLine(s//2-5, s-15, s//2, s-10); p.drawLine(s//2+5, s-15, s//2, s-10)
        if kind == "export": p.drawLine(s//2, s-10, s//2, 8); p.drawLine(s//2-5, 13, s//2, 8); p.drawLine(s//2+5, 13, s//2, 8)
    elif kind == "text": p.setFont(QFont("Sans", int(s*0.5), QFont.Weight.Bold)); p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "Т")
    elif kind == "rect": p.drawRect(6, 9, s-12, s-18)
    elif kind == "ellipse": p.drawEllipse(6, 9, s-12, s-18)
    elif kind == "line": p.drawLine(6, s-6, s-6, 6)
    elif kind in ("photo", "image"): p.drawRect(5, 7, s-10, s-14); p.drawEllipse(s//2-4, 11, 8, 8); p.drawLine(9, s-9, s-9, s-9)
    elif kind == "barcode":
        for i, x in enumerate(range(7, s-7, 3)): p.drawLine(x, 8, x, s-8 - (i % 2) * 3)
    elif kind == "qr":
        for x, y in ((6, 6), (s-15, 6), (6, s-15)): p.drawRect(x, y, 9, 9)
        p.fillRect(s//2, s//2, 6, 6, c)
    elif kind in ("front", "back"):
        p.drawRoundedRect(4, 8, s-8, s-16, 3, 3)
        if kind == "front": p.fillRect(8, 12, 7, 8, c)
        else: [p.drawLine(8, y, s-8, y) for y in (14, 19, 24)]
    elif kind in ("undo", "redo"):
        p.drawArc(8, 8, s-16, s-16, 0, 180*16)
        x = 8 if kind == "undo" else s-8; p.drawLine(x, s//2, x-4 if kind=="undo" else x+4, s//2-5)
    elif kind in ("copy", "paste", "delete", "group", "align", "front_z", "back_z"):
        p.drawRect(6, 6, s-16, s-16); p.drawRect(10, 10, s-16, s-16)
        if kind == "delete": p.setPen(QPen(QColor("#B23A3A"), 3)); p.drawLine(8, 8, s-8, s-8); p.drawLine(s-8, 8, 8, s-8)
    elif kind in ("zoom_in", "zoom_out", "fit"):
        p.drawEllipse(5, 5, s-16, s-16); p.drawLine(s-12, s-12, s-5, s-5)
        if kind != "fit": p.drawLine(10, s//2-3, s-15, s//2-3)
        if kind == "zoom_in": p.drawLine(s//2-3, 10, s//2-3, s-15)
    elif kind in ("grid", "ruler"):
        if kind == "grid":
            for v in range(6, s, 7): p.drawLine(v, 4, v, s-4); p.drawLine(4, v, s-4, v)
        else:
            p.drawRect(3, s//2-6, s-6, 12); [p.drawLine(x, s//2-6, x, s//2) for x in range(7, s-4, 4)]
    elif kind in ("db", "connect", "disconnect", "table", "filter", "mark"):
        p.drawEllipse(7, 4, s-14, 7); p.drawLine(7, 8, 7, s-8); p.drawLine(s-7, 8, s-7, s-8); p.drawArc(7, s-12, s-14, 7, 180*16, 180*16)
        if kind == "disconnect": p.setPen(QPen(QColor("#B23A3A"), 3)); p.drawLine(5, s-5, s-5, 5)
        if kind == "filter": p.drawLine(10, 16, s-10, 16)
    elif kind in ("help", "about"):
        p.drawEllipse(4, 4, s-8, s-8); p.setFont(QFont("Sans", int(s*0.4), QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?" if kind == "help" else "i")
    elif kind in ("printed", "unprinted"):
        p.drawRect(6, 6, s-12, s-12)
        if kind == "printed": p.drawLine(10, s//2, s//2-2, s-11); p.drawLine(s//2-2, s-11, s-9, 10)
        else: p.drawLine(11, 11, s-11, s-11); p.drawLine(s-11, 11, 11, s-11)
    elif kind == "add": p.drawLine(s//2, 6, s//2, s-6); p.drawLine(6, s//2, s-6, s//2)
    elif kind == "edit_card": p.drawRoundedRect(4, 8, s-8, s-16, 3, 3); p.drawLine(10, s-6, s-6, 10)
    elif kind == "goto": p.drawLine(5, s//2, s-7, s//2); p.drawLine(s-12, s//2-6, s-6, s//2); p.drawLine(s-12, s//2+6, s-6, s//2)
    elif kind == "settings":
        p.drawEllipse(9, 9, s-18, s-18)
        for a in range(0, 360, 45):
            p.save(); p.translate(s/2, s/2); p.rotate(a); p.drawLine(0, -s//2+3, 0, -s//2+8); p.restore()
    elif kind == "exit": p.drawRect(5, 5, s//2, s-10); p.drawLine(s//2, s//2, s-5, s//2); p.drawLine(s-10, s//2-5, s-5, s//2); p.drawLine(s-10, s//2+5, s-5, s//2)
    elif kind == "cut": p.drawEllipse(5, s-13, 8, 8); p.drawEllipse(s-13, s-13, 8, 8); p.drawLine(10, s-13, s-8, 5); p.drawLine(s-10, s-13, 8, 5)
    elif kind == "capture": p.drawRoundedRect(4, 9, s-8, s-15, 3, 3); p.drawRect(s//2-5, 5, 10, 4); p.drawEllipse(s//2-6, 13, 12, 12)
    elif kind == "position": p.drawRect(7, 7, s-14, s-14); p.drawLine(s//2, 2, s//2, s-2); p.drawLine(2, s//2, s-2, s//2)
    elif kind == "render": p.drawRoundedRect(4, 8, s-8, s-16, 3, 3); p.fillRect(8, 12, 7, 8, QColor(ACCENT)); p.drawLine(18, 14, s-8, 14)
    elif kind == "reset": p.drawRect(4, 4, s-8, s-8); p.drawLine(s//2, 4, s//2, s-4)
    elif kind in ("fill", "stroke"):
        p.setBrush(QColor(ACCENT) if kind == "fill" else Qt.BrushStyle.NoBrush); p.drawRoundedRect(5, 7, s-10, s-14, 3, 3)
    elif kind == "background": p.fillRect(4, 8, s-8, s-16, QColor("#D7E9E3")); p.drawRect(4, 8, s-8, s-16)
    elif kind == "duplicate": p.drawRect(5, 5, s-15, s-15); p.drawRect(10, 10, s-15, s-15); p.drawLine(s-12, s-8, s-12, s-16)
    else: p.drawEllipse(8, 8, s-16, s-16)
    p.end(); return QIcon(pm)



class RibbonGroup(QWidget):
    """Группа ленты: полный вид (кнопки) или свёрнутый — одна кнопка с выпадающим меню из ТЕХ ЖЕ QAction."""

    def __init__(self, tab, title, actions, parent=None):
        super().__init__(parent)
        self.tab, self.title, self.actions_ = tab, title, actions
        self.full = QWidget(); v = QVBoxLayout(self.full); v.setContentsMargins(2, 0, 2, 0); v.setSpacing(0)
        self.row = QHBoxLayout(); self.row.setSpacing(1); v.addLayout(self.row, 1)
        lab = QLabel(title); lab.setAlignment(Qt.AlignmentFlag.AlignCenter); lab.setStyleSheet("color:#667; font-size:10px;")
        v.addWidget(lab)
        self.menu = QMenu(title, self)
        for act in actions: self.menu.addAction(act)
        self.button = QToolButton(); self.button.setText(f"{title} ▾"); self.button.setMenu(self.menu)
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon); self.button.setIconSize(QSize(28, 28))
        self.button.setAutoRaise(True); self.button.setToolTip(f"Группа «{title}»")
        ic = next((a.icon() for a in actions if not a.icon().isNull()), None)
        if ic: self.button.setIcon(ic)
        self.button.setFixedWidth(max(56, self.button.fontMetrics().horizontalAdvance(title) + 16))
        h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0); h.addWidget(self.full); h.addWidget(self.button)
        self.button.hide(); self.collapsed = False

    def full_width(self): return self.full.sizeHint().width()
    def collapsed_width(self): return self.button.width()

    def set_collapsed(self, on):
        self.collapsed = bool(on); self.full.setVisible(not on); self.button.setVisible(on)


class Ribbon(QTabWidget):
    """Вкладки ленты; группы с кнопками-QAction. Повторное размещение действия — ошибка.
    Если группы вкладки не помещаются по ширине, они сворачиваются справа налево (§4 п.2)."""
    BTN_W = 72
    SMALL_H = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ribbon"); self.setDocumentMode(True)
        self.places, self.pages, self.buttons, self.groups = {}, {}, {}, {t: [] for t in TABS}
        self.scrolls = {}
        for t in TABS:
            inner = QWidget(); h = QHBoxLayout(inner); h.setContentsMargins(4, 2, 4, 0); h.setSpacing(2); h.addStretch(1)
            sc = QScrollArea(); sc.setWidget(inner); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.Shape.NoFrame)
            sc.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            sc.setMinimumWidth(100)
            self.pages[t] = h; self.scrolls[t] = sc; self.addTab(sc, t)
        self.setFixedHeight(112)
        self.currentChanged.connect(lambda *_: self.relayout())

    def _button(self, it, small=False):
        b = QToolButton(); b.setDefaultAction(it); b.setAutoRaise(True)
        if it.menu() is not None: b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if small:
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); b.setIconSize(QSize(16, 16))
            one = lambda b=b, it=it: b.setText(it.iconText().replace("\n", " "))
            one(); it.changed.connect(one)          # QToolButton сбрасывает текст из iconText при changed
            b.setFixedHeight(max(self.SMALL_H, b.sizeHint().height()))
        else:
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon); b.setIconSize(QSize(26, 26))
            lines = it.iconText().split("\n")
            b.setFixedWidth(max(44, b.sizeHint().width()))
        self.buttons[it] = b; return b

    def _place(self, it, tab, title):
        if it in self.places: raise ValueError(f"действие «{it.text()}» уже размещено в {self.places[it]}")
        self.places[it] = (tab, title)

    def add_group(self, tab, title, items):
        """items: QAction (большая кнопка), QWidgetAction (виджет) или список QAction — столбик маленьких кнопок."""
        flat = [a for it in items for a in (it if isinstance(it, (list, tuple)) else [it])]
        for a in flat:
            if a in self.places: raise ValueError(f"действие «{a.text()}» уже размещено в {self.places[a]}")
        g = RibbonGroup(tab, title, flat)
        for it in items:
            if isinstance(it, (list, tuple)):
                col = QVBoxLayout(); col.setSpacing(0); col.setContentsMargins(0, 0, 0, 0)
                for a in it: self._place(a, tab, title); col.addWidget(self._button(a, small=True))
                col.addStretch(1); g.row.addLayout(col)
            elif isinstance(it, QWidgetAction):
                self._place(it, tab, title); w = it.requestWidget(g.full); g.row.addWidget(w); w.setVisible(True); self.buttons[it] = w
            else:
                self._place(it, tab, title); g.row.addWidget(self._button(it))
        h = self.pages[tab]; h.insertWidget(h.count() - 1, g)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine); sep.setStyleSheet("color:#D5DCDA;"); h.insertWidget(h.count() - 1, sep)
        self.groups[tab].append(g)
        return g

    def available_width(self, tab=None):
        return self.scrolls[tab or self.tabText(self.currentIndex())].viewport().width() or self.width()

    def needed_width(self, tab):
        h = self.pages[tab]; m = h.contentsMargins()
        gs = self.groups[tab]
        return (m.left() + m.right() + sum(g.collapsed_width() if g.collapsed else g.full_width() for g in gs)
                + len(gs) * (h.spacing() * 2 + 2))

    def relayout(self, tab=None, avail=None):
        """Развернуть все группы, затем сворачивать справа налево, пока не поместится."""
        tab = tab or self.tabText(self.currentIndex()); avail = avail or self.available_width(tab)
        for g in self.groups[tab]: g.set_collapsed(False)
        for g in reversed(self.groups[tab]):
            if self.needed_width(tab) <= avail: break
            g.set_collapsed(True)
        return [g.title for g in self.groups[tab] if g.collapsed]

    def resizeEvent(self, ev):
        super().resizeEvent(ev); self.relayout()

    def actions_of(self, tab):
        return [a for a, (t, _g) in self.places.items() if t == tab]

    def select(self, tab):
        self.setCurrentIndex(TABS.index(tab))
