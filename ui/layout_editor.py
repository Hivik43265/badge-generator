"""Редактор макета: холст CR80 1011x638 px, стороны front/back.

Шаблон изначально пустой — UI никогда не создаёт демо-макеты. Фон холста — рендер Backend
(render_card выбранной записи или пустого шаблона); поверх — рамки элементов (UI-оформление)
для выбора, перемещения и изменения размера. Все изменения — через create_element /
update_element / delete_element / set_background.
"""
import json
import os
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QBrush, QColor, QPen, QPainter, QPixmap, QAction, QFont
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGraphicsView, QGraphicsScene,
                             QGraphicsRectItem, QGraphicsSimpleTextItem, QGraphicsItem, QGroupBox,
                             QFormLayout, QLabel, QComboBox, QPushButton, QSpinBox, QLineEdit,
                             QPlainTextEdit, QMessageBox, QCheckBox, QToolButton, QGridLayout,
                             QInputDialog, QFileDialog, QColorDialog, QScrollArea, QSizePolicy, QListWidget, QListWidgetItem)
from .stage15 import UNLINKED_COLOR, PHOTO_FIELD_LABEL, PHOTO_FIELD_TYPE
from .backend_api import BackendAPI, CARD_W_PX, CARD_H_PX, TYPE_NAMES, SIDE_NAMES, person_caption
from .preview_jobs import RenderCardJob, RenderSignals, render_pool

SIDE_LABELS = SIDE_NAMES
NEW_FIELD = "Новое поле…"


def fm_hook_active():
    from . import main_view
    return main_view.field_manager_hook is not None
TYPE_LABELS = TYPE_NAMES
MM_PER_PX = 85.6 / CARD_W_PX
# Типы, создаваемые инструментами ленты «Рисование» (ключ = тип элемента); фон — отдельное действие
TOOLS = [(t, TYPE_NAMES[t], t) for t in ("field", "photo", "barcode", "qr", "text", "rect", "ellipse", "line", "image")]
DEFAULT_SIZE = {"text": (400, 80), "field": (400, 80), "image": (200, 200), "photo": (300, 400), "rect": (400, 250),
                "ellipse": (300, 200), "line": (600, 0), "barcode": (420, 140), "qr": (220, 220)}
DEFAULT_STYLE = {"text": {"font_size": 14, "color": "#000000"}, "field": {"font_size": 14, "color": "#000000"},
                 "rect": {"stroke": "#1F4E8C", "stroke_width": 3},
                 "ellipse": {"stroke": "#1F4E8C", "stroke_width": 3}, "line": {"stroke": "#1F4E8C", "stroke_width": 3},
                 "barcode": {"format": "code128", "show_text": True, "quiet_zone": 10, "font_size": 8},
                 "qr": {"error_correction": "M", "border": 4}, "photo": {}, "image": {"fit": "contain"}}
FORMATS = [("code128", "Code128"), ("ean13", "EAN-13")]      # style["format"] (старый ключ symbology — только чтение)
EC_LEVELS = ["L", "M", "Q", "H"]
# Подписи типов для рамок, списка элементов и панели свойств (D8) — из TYPE_NAMES
KIND_NAMES = TYPE_NAMES


def _s(v):
    return "" if v is None else str(v).strip()


def element_caption(el, labels=None):
    """Человекочитаемая подпись элемента; никогда не содержит 'None'."""
    t = el.get("type"); name = KIND_NAMES.get(t, _s(t) or "Элемент")
    fn, sv = _s(el.get("field_name")), _s(el.get("static_value"))
    if t == "field":
        lab = _s((labels or {}).get(fn)) if fn else ""
        det = lab or fn
    elif t == "text":
        det = sv
    elif t in ("barcode", "qr"):
        det = fn and (_s((labels or {}).get(fn)) or fn) or sv
    else:
        det = ""
    return f"{name}: {det}" if det else name
EMPTY_HINT = "Добавьте элементы: вкладка ленты «Рисование»"
warn_hook = None   # хук для тестов: warn_hook(title, text) вместо модального QMessageBox


def _warn(parent, title, text):
    if warn_hook is not None:
        warn_hook(title, text)
    else:
        QMessageBox.warning(parent, title, text)
HANDLE = 14


def _intersects(a, b):
    """Пересечение с ненулевой площадью (касание краями — не пересечение)."""
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def find_overlaps(elements):
    """Пары пересекающихся элементов. Как в тестах Backend: подложка-rect с меньшим z_order не считается."""
    bad = []
    for i, a in enumerate(elements):
        for b in elements[i + 1:]:
            if not _intersects(a, b): continue
            lo, hi = sorted((a, b), key=lambda e: e["z_order"])
            if lo["type"] == "rect" and lo["z_order"] < hi["z_order"]: continue
            bad.append((a["id"], b["id"]))
    return bad


class _Bus(QObject):
    geometry_committed = pyqtSignal(object)
    text_edit_requested = pyqtSignal(object)


class ElementItem(QGraphicsRectItem):
    """Рамка элемента. Для 'line' w/h — вектор отрезка (могут быть 0 или <0, но не оба 0):
    рамка — нормализованный охватывающий прямоугольник (мин. толщина для выбора), ручка — в конце отрезка."""
    LINE_PAD = 6

    def __init__(self, el, bus, labels=None):
        super().__init__()
        self.el, self.bus, self._resizing = el, bus, False
        self.is_line = el["type"] == "line"
        self.lw, self.lh = el["w"], el["h"]
        self.setPos(el["x"], el["y"]); self.setZValue(1000 + (el.get("z_order") or 0))
        # этап 15 п.3: связываемый объект без поля — цвет «не связан»
        self.unlinked = el["type"] in ("field", "barcode", "qr", "photo") and not el.get("field_name") and not (
            el["type"] in ("barcode", "qr") and el.get("static_value"))
        self.setPen(QPen(QColor(UNLINKED_COLOR if self.unlinked else "#3070d0"), 2, Qt.PenStyle.DashLine))
        self.setBrush(QBrush(QColor(48, 112, 208, 25)))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.caption = QGraphicsSimpleTextItem(self)
        self.handle = QGraphicsRectItem(0, 0, HANDLE, HANDLE, self)
        self.handle.setBrush(QBrush(QColor("#3070d0")))
        self.caption.setText((element_caption(el, labels)[:48]) + ("  · не связан" if self.unlinked else ""))
        if self.unlinked: self.caption.setBrush(QBrush(QColor(UNLINKED_COLOR)))
        self._apply_geom(el["w"], el["h"])

    def _apply_geom(self, w, h):
        if self.is_line:
            self.lw, self.lh = w, h; p = self.LINE_PAD
            self.setRect(QRectF(min(0, w) - p, min(0, h) - p, abs(w) + 2 * p, abs(h) + 2 * p))
            self.handle.setPos(w - HANDLE / 2, h - HANDLE / 2)
        else:
            self.setRect(0, 0, w, h); self.handle.setPos(w - HANDLE, h - HANDLE)
        r = self.rect(); self.caption.setPos(r.left() + 4, r.top() - 18)

    def _place_handle(self):
        self._apply_geom(*((self.lw, self.lh) if self.is_line else (self.rect().width(), self.rect().height())))

    def set_size(self, w, h):
        self._apply_geom(w, h)

    def mousePressEvent(self, ev):
        self._resizing = bool(self.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable) and self.handle.contains(self.handle.mapFromParent(ev.pos()))
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._resizing:
            x, y = round(ev.pos().x()), round(ev.pos().y())
            if self.is_line:
                if x == 0 and y == 0: x = 1          # (0,0) запрещено
                self._apply_geom(x, y)
            else:
                self._apply_geom(max(4, x), max(4, y))
        else:
            super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev); self._resizing = False
        self.bus.geometry_committed.emit(self)

    def mouseDoubleClickEvent(self, ev):
        super().mouseDoubleClickEvent(ev)
        if self.el.get("type") == "text":
            self.bus.text_edit_requested.emit(self)

    def geometry(self):
        if self.is_line:
            w, h = int(round(self.lw)), int(round(self.lh))
        else:
            r = self.rect(); w, h = int(round(r.width())), int(round(r.height()))
        return {"x": int(round(self.x())), "y": int(round(self.y())), "w": w, "h": h}


class LayoutEditor(QWidget):
    status = pyqtSignal(str)

    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api, self.side, self.current = api, "front", None
        self.person_id = None          # запись, рендер которой показан под рамками
        self.canvas_image = None
        self.bus = _Bus(); self.bus.geometry_committed.connect(self._commit_geometry)
        self.scene = QGraphicsScene(0, 0, CARD_W_PX, CARD_H_PX, self)
        self.view = QGraphicsView(self.scene); self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.scene.selectionChanged.connect(self._on_select)
        self.overlaps, self.hint = [], None

        # Действия (инструменты, удаление, порядок, сторона) живут только в ленте главного окна.
        self.template_mode = False       # этап 15 п.2: вне режима шаблона элементы заблокированы
        self.show_render = True          # «Рендер под рамками» — переключается действием ленты
        self.person_label = QLabel("Запись на холсте: пустой шаблон"); self.person_label.setWordWrap(True)
        self._bg_item = None
        self._render_gen = 0
        self._render_signals = RenderSignals(self)
        self._render_signals.finished.connect(self._on_canvas_rendered)
        self.selection_actions = []      # действия ленты, активные только при выделенном объекте

        self.warn = QLabel(); self.warn.setWordWrap(True); self.warn.setStyleSheet("color:#c00;")

        props = QGroupBox("Свойства элемента"); pf = QFormLayout(props)
        self.p_type = QLabel("—"); self.p_type.setWordWrap(True)
        self.p_x, self.p_y, self.p_w, self.p_h = (self._spin(-CARD_W_PX * 2, CARD_W_PX * 2) for _ in range(4))
        for _w in (self.p_x, self.p_y, self.p_w, self.p_h): _w.setReadOnly(True)    # этап 15: вне режима шаблона — только чтение
        self.p_z = self._spin(-1000, 1000)
        self.p_field = QComboBox(); self.p_field.setEditable(True)
        self.p_static = QLineEdit()
        self.p_text = QPlainTextEdit()
        _fm = self.p_text.fontMetrics()
        self.p_text.setFixedHeight(_fm.lineSpacing() * 4 + 16)
        self.p_hint = QLabel(""); self.p_hint.setStyleSheet("color:#666;")
        self.p_font = self._spin(4, 200)
        self.p_color, self.p_bg, self.p_fill, self.p_stroke = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        for e in (self.p_color, self.p_bg, self.p_fill, self.p_stroke): e.setPlaceholderText("#RRGGBB")
        self.p_stroke_w = self._spin(0, 100); self.p_radius = self._spin(0, 300)
        self.p_format = QComboBox()
        for k, v in FORMATS: self.p_format.addItem(v, k)
        self.p_format.currentIndexChanged.connect(self._update_hint)
        self.p_show_text = QCheckBox("Показывать текст под штрихкодом")
        self.p_quiet = self._spin(0, 200)
        self.p_ec = QComboBox(); self.p_ec.addItems(EC_LEVELS)
        self.p_qborder = self._spin(0, 50)
        self.p_style = QPlainTextEdit(); self.p_style.setFixedHeight(70)
        self.rows = {}
        for key, lab, w in (("type", "Элемент:", self.p_type), ("x", "X, px:", self.p_x), ("y", "Y, px:", self.p_y),
                            ("w", "Ширина, px:", self.p_w), ("h", "Высота, px:", self.p_h), ("z", "Слой (z):", self.p_z),
                            ("field", "Поле записи:", self.p_field), ("static", "Значение/путь:", self.p_static),
                            ("text", "Текст:", self.p_text),
                            ("hint", "", self.p_hint), ("format", "Формат:", self.p_format),
                            ("show_text", "", self.p_show_text), ("quiet", "Тихая зона, px:", self.p_quiet),
                            ("ec", "Коррекция ошибок:", self.p_ec), ("qborder", "Поле QR, модулей:", self.p_qborder),
                            ("font", "Шрифт, pt:", self.p_font), ("color", "Цвет:", self.p_color),
                            ("bg", "Фон:", self.p_bg), ("fill", "Заливка:", self.p_fill),
                            ("stroke", "Цвет обводки:", self.p_stroke), ("stroke_w", "Толщина обводки, px:", self.p_stroke_w),
                            ("radius", "Скругление, px:", self.p_radius), ("style", "Стиль (JSON):", self.p_style)):
            pf.addRow(lab, w); self.rows[key] = (pf.labelForField(w), w)
        self._loading = False
        self._pending_text_keep = None
        self._text_bound_eid = None
        self.bus.text_edit_requested.connect(self._on_text_double_click)
        self._live_wiring()          # D11: свойства применяются сразу при изменении поля (кнопки «Применить» нет)
        self.props = props; props.setEnabled(False)

        right = QVBoxLayout()
        self.mode_banner = QLabel("Режим создания шаблона: расставьте элементы на карточке вручную и выберите поля; сохранение — «✓ Сохранить шаблон» на ленте"); self.mode_banner.setStyleSheet(
            "background:#2E7D6B; color:white; font-weight:600; padding:3px 8px;"); self.mode_banner.hide(); self.mode_banner.setWordWrap(True)
        # этап 15 п.1: индикатор связи фото-объекта с полем «Фото» (Изображение)
        self.photo_link = QLabel(); self.photo_link.setWordWrap(True); self.photo_link.hide()
        self.photo_link.setStyleSheet("background:#EAF3FF; border:1px solid #3070d0; padding:4px;")
        right.addWidget(self.photo_link)
        right.addWidget(self.person_label)
        # Список элементов — только для выбора (перекрытые объекты); своих кнопок нет,
        # контекстное меню строит главное окно на тех же QAction ленты.
        self.el_list = QListWidget(); self.el_list.setMaximumHeight(140)
        self.el_list.itemClicked.connect(lambda it: self.select(it.data(Qt.ItemDataRole.UserRole)))
        right.addWidget(QLabel("Элементы стороны:")); right.addWidget(self.el_list)
        right.addWidget(self.warn); right.addWidget(props); right.addStretch()
        inner = QWidget(); inner.setLayout(right)
        rw = QScrollArea(); rw.setWidget(inner); rw.setWidgetResizable(True); rw.setMinimumWidth(260)
        self.panel = rw
        self.view.setMouseTracking(True); self.view.viewport().setMouseTracking(True)
        self.view.viewport().installEventFilter(self)
        self.hruler, self.vruler = Ruler(self, True), Ruler(self, False)
        cw = QWidget(); g = QGridLayout(cw); g.setContentsMargins(0, 0, 0, 0); g.setSpacing(0)
        corner = QLabel("мм"); corner.setFixedSize(Ruler.T, Ruler.T); corner.setStyleSheet("font-size:8px; background:#F1F3F2;")
        g.addWidget(corner, 0, 0); g.addWidget(self.hruler, 0, 1); g.addWidget(self.vruler, 1, 0); g.addWidget(self.view, 1, 1)
        self.canvas_box = cw
        left = QVBoxLayout(); left.setContentsMargins(0, 0, 0, 0); left.setSpacing(0); left.addWidget(self.mode_banner); left.addWidget(cw, 1)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addLayout(left, 1); lay.addWidget(rw)
        self.load("front")

    cursor_moved = pyqtSignal(float, float)

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.view.viewport() and ev.type() == QEvent.Type.MouseMove:
            p = self.view.mapToScene(ev.position().toPoint())
            self.cursor_moved.emit(p.x() * MM_PER_PX, p.y() * MM_PER_PX)
        if obj is self.view.viewport() and ev.type() in (QEvent.Type.Paint,):
            self.hruler.update(); self.vruler.update()
        return False

    def set_rulers(self, on):
        self.hruler.setVisible(on); self.vruler.setVisible(on)

    def set_show_render(self, on):
        self.show_render = bool(on); self.load(self.side, self.current.el["id"] if self.current else None)

    def set_side(self, side):
        if side != self.side: self.load(side)

    def select(self, eid):
        """Выбор объекта по id (список элементов, панель полей): выделяет объект на холсте."""
        for i in self.items(): i.setSelected(i.el["id"] == eid)
        return self.current

    def set_prop(self, key, value):
        """Единый путь записи свойства: значение кладётся в панель свойств и применяется apply_props."""
        return self.set_props(**{key: value})

    def set_props(self, **values):
        """Несколько свойств за одно применение (один шаг истории «Отменить»)."""
        if not self.current: return False
        m = {"x": self.p_x, "y": self.p_y, "w": self.p_w, "h": self.p_h, "fill": self.p_fill, "stroke": self.p_stroke,
             "stroke_width": self.p_stroke_w, "color": self.p_color}
        for key, value in values.items():
            w = m[key]; (w.setText if isinstance(w, QLineEdit) else w.setValue)(value)
        return self.apply_props()

    @staticmethod
    def _spin(lo, hi):
        s = QSpinBox(); s.setRange(lo, hi); return s

    def reload(self):
        self.load(self.side)

    def load(self, side, select_id=None):
        self.side = side; self.current = None
        self._render_gen += 1
        self._bg_item = None
        self.scene.clear(); self.hint = None
        if self.show_render:
            pid = self.person_id if self.person_id is not None and self.api.get_person(self.person_id) else None
            self.person_id = pid
            ph = QPixmap(CARD_W_PX, CARD_H_PX); ph.fill(QColor("#FFFFFF"))
            self._bg_item = self.scene.addPixmap(ph)
            bg = self._bg_item
            self._start_canvas_render(pid, side)
        else:
            b = self.api.get_background(side) or {"color": "#FFFFFF"}
            bg = self.scene.addRect(QRectF(0, 0, CARD_W_PX, CARD_H_PX), QPen(Qt.PenStyle.NoPen), QBrush(QColor(b["color"])))
        bg.setZValue(-1)
        self.scene.addRect(QRectF(0, 0, CARD_W_PX, CARD_H_PX), QPen(QColor("#888888"))).setZValue(0)
        self._draw_grid()
        fields = self.api.list_fields()
        self.labels = {f["name"]: f.get("label") for f in fields}
        self._fill_fields(fields)
        els = self.api.list_elements(side)
        self.el_list.clear()
        for el in els:
            it = ElementItem(el, self.bus, self.labels); self.scene.addItem(it)
            it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.template_mode)   # этап 15: вне режима шаблона — заблокировано
            it.handle.setVisible(self.template_mode)
            li = QListWidgetItem(f"#{el['id']} {element_caption(el, self.labels)}"); li.setData(Qt.ItemDataRole.UserRole, el["id"])
            self.el_list.addItem(li)
            if el["id"] == select_id: it.setSelected(True); li.setSelected(True)
        if not els:   # подсказка — только оформление редактора, в рендер не попадает
            self.hint = QGraphicsSimpleTextItem(EMPTY_HINT)
            f = QFont(); f.setPointSize(22); self.hint.setFont(f); self.hint.setBrush(QBrush(QColor(120, 120, 120, 160)))
            r = self.hint.boundingRect(); self.hint.setPos((CARD_W_PX - r.width()) / 2, (CARD_H_PX - r.height()) / 2)
            self.hint.setZValue(500); self.scene.addItem(self.hint)
        self.view.fitInView(self.scene.sceneRect().adjusted(-20, -30, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)
        self._check_overlaps()
        self._on_select()

    def _check_overlaps(self):
        items = {i.el["id"]: i for i in self.items()}
        self.overlaps = find_overlaps([{**i.el, **i.geometry()} for i in items.values()])
        bad = {x for pair in self.overlaps for x in pair}
        for eid, it in items.items():
            if eid in bad:
                it.setPen(QPen(QColor("#d00000"), 3, Qt.PenStyle.SolidLine)); it.setBrush(QBrush(QColor(208, 0, 0, 45)))
        msg = ("Внимание: элементы пересекаются (" + ", ".join(f"#{a}×#{b}" for a, b in self.overlaps) + ")") if self.overlaps else ""
        self.warn.setText(msg)
        self.status.emit(msg or f"Макет ({SIDE_LABELS[self.side]}): пересечений нет")

    def _set_person_meta(self, person_id):
        """Запомнить выбранную запись и подпись, без пересборки элементов и без рендера."""
        p = self.api.get_person(person_id) if person_id is not None else None
        self.person_id = person_id if p is not None else None
        name = person_caption(self.api, p).strip() if p else "пустой шаблон"
        self.person_label.setText(f"Запись на холсте: {name}")
        return self.person_id

    def set_person(self, person_id):
        """Показать на холсте рендер выбранной записи (None — пустой шаблон).
        Элементы не пересобираются: load() только при смене шаблона/стороны."""
        pid = self._set_person_meta(person_id)
        if self.show_render and self.isVisible():
            self._start_canvas_render(pid, self.side)

    def _start_canvas_render(self, person_id, side):
        self._render_gen += 1
        gen = self._render_gen
        try:
            payload = self.api.gather_render_args(person_id, side)
        except KeyError:
            payload = self.api.gather_render_args(None, side)
        render_pool().start(RenderCardJob(gen, payload, self._render_signals))

    def _on_canvas_rendered(self, gen, result, side):
        if gen != self._render_gen or side != self.side:
            return
        if isinstance(result, Exception):
            return
        self.canvas_image = result
        if self._bg_item is not None:
            self._bg_item.setPixmap(QPixmap.fromImage(result))

    def items(self):
        return [i for i in self.scene.items() if isinstance(i, ElementItem)]

    def _commit_geometry(self, item):
        g = item.geometry()
        if all(g[k] == item.el[k] for k in g):
            return
        err = self.validate_size(item.el["type"], g["w"], g["h"])
        if err:
            _warn(self, "Размер", err); QTimer.singleShot(0, lambda: self.load(self.side, item.el["id"])); return
        self.api.update_element(item.el["id"], **g)
        item.el.update(g)
        QTimer.singleShot(0, lambda eid=item.el["id"]: self.load(self.side, eid))   # после выхода из обработчика мыши

    # --- свойства ---
    @staticmethod
    def validate_size(t, w, h):
        if t == "line":
            return "У линии ширина и высота не могут быть одновременно 0" if w == 0 and h == 0 else None
        return "Ширина и высота должны быть больше 0" if w <= 0 or h <= 0 else None

    VIS = {"field": ("field", "barcode", "qr"), "static": ("image", "barcode", "qr"),
           "text": ("text",),
           "hint": ("barcode",), "format": ("barcode",), "show_text": ("barcode",), "quiet": ("barcode",),
           "ec": ("qr",), "qborder": ("qr",), "font": ("text", "field", "barcode"),
           "color": ("text", "field", "barcode", "qr"), "bg": ("barcode", "qr"), "fill": ("rect", "ellipse", "text", "field"),
           "stroke": ("rect", "ellipse", "line"), "stroke_w": ("rect", "ellipse", "line"), "radius": ("rect",)}

    def _show_rows(self, t):
        for key, (lab, w) in self.rows.items():
            v = t in self.VIS[key] if key in self.VIS else True
            w.setVisible(v)
            if lab: lab.setVisible(v)
        self.rows["w"][0].setText("Δx, px:" if t == "line" else "Ширина, px:")
        self.rows["h"][0].setText("Δy, px:" if t == "line" else "Высота, px:")

    def _update_hint(self, *_):
        ean = self.p_format.currentData() == "ean13"
        self.p_hint.setText("12 или 13 цифр" if ean else "Значение: поле записи или статический текст")
        self.p_static.setPlaceholderText("12 или 13 цифр" if ean else "")

    def _live_wiring(self):
        from PyQt6.QtCore import QTimer
        live = self._live_apply
        for w in (self.p_x, self.p_y, self.p_w, self.p_h, self.p_z, self.p_stroke_w, self.p_radius,
                  self.p_quiet, self.p_qborder, self.p_static, self.p_color, self.p_bg, self.p_fill, self.p_stroke):
            w.editingFinished.connect(live)
        self.p_field.activated.connect(lambda *_: self._field_chosen() and live()); self.p_field.lineEdit().editingFinished.connect(live)
        self.p_format.activated.connect(lambda *_: live()); self.p_ec.activated.connect(lambda *_: live())
        self.p_show_text.toggled.connect(lambda *_: live())
        self._style_timer = QTimer(self, singleShot=True, interval=700, timeout=live)
        self.p_style.textChanged.connect(lambda: None if self._loading else self._style_timer.start())
        self._text_timer = QTimer(self, singleShot=True, interval=300, timeout=self._apply_text)
        self.p_text.textChanged.connect(lambda: None if self._loading else self._text_timer.start())
        self._font_timer = QTimer(self, singleShot=True, interval=300, timeout=self._apply_font_size)
        self.p_font.valueChanged.connect(lambda *_: None if self._loading else self._font_timer.start())

    def _live_apply(self):
        if self._loading or not self.current: return None
        return self.apply_props()

    def _apply_text(self):
        """Записать static_value текстового объекта (рабочая копия) после паузы ввода."""
        if self._loading or not self.current or self.current.el.get("type") != "text":
            return None
        new = self.p_text.toPlainText() or None
        if (self.current.el.get("static_value") or None) == new:
            return True
        self._pending_text_keep = self.current.el["id"]
        self._text_bound_eid = self.current.el["id"]
        r = self.apply_props()
        if not self.p_text.hasFocus():
            self.p_text.setFocus(Qt.FocusReason.OtherFocusReason)
        return r

    def _apply_font_size(self):
        if self._loading or not self.current:
            return None
        t = self.current.el.get("type")
        if t not in ("text", "field", "barcode"):
            return None
        st = self.current.el.get("style") or {}
        default = 8 if t == "barcode" else 14
        if int(self.p_font.value()) == int(st.get("font_size", default)):
            return True
        return self.apply_props()

    def _on_text_double_click(self, item):
        """Двойной щелчок по объекту «Текст»: выделить и перейти в поле «Текст» (выделить всё)."""
        if item is None or item.el.get("type") != "text":
            return
        for i in self.items():
            i.setSelected(i is item)
        self.p_text.setFocus(Qt.FocusReason.OtherFocusReason)
        self.p_text.selectAll()

    def _on_select(self):
        self._loading = True
        try: self._on_select_inner()
        finally: self._loading = False

    def _on_select_inner(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, ElementItem)]
        new_id = sel[0].el["id"] if sel else None
        keep_text = new_id is not None and (self.p_text.hasFocus() or self._pending_text_keep == new_id)
        self.current = sel[0] if sel else None
        self.props.setEnabled(bool(sel))
        for a in self.selection_actions: a.setEnabled(bool(sel))
        cur = self.current.el["id"] if sel else None
        for r in range(self.el_list.count()):
            it = self.el_list.item(r); it.setSelected(it.data(Qt.ItemDataRole.UserRole) == cur)
        self._show_photo_link(self.current.el if sel else None)
        if not sel: return
        e = {**sel[0].el, **sel[0].geometry()}; st = e.get("style") or {}; t = e["type"]
        self.p_type.setText(element_caption(e, getattr(self, "labels", {}))); self._show_rows(t)
        for w, k in ((self.p_x, "x"), (self.p_y, "y"), (self.p_w, "w"), (self.p_h, "h"), (self.p_z, "z_order")):
            w.setValue(int(e[k] or 0))
        self.p_field.setCurrentText(e.get("field_name") or "")
        if t == "text":
            if not keep_text:
                self.p_text.blockSignals(True)
                self.p_text.setPlainText(e.get("static_value") or "")
                self.p_text.blockSignals(False)
                self._text_bound_eid = new_id
            self._pending_text_keep = None
        else:
            self.p_static.setText(e.get("static_value") or "")
        self.p_font.setValue(int(st.get("font_size", 8 if t == "barcode" else 14)))
        self.p_color.setText(st.get("color") or ""); self.p_bg.setText(st.get("background") or "")
        self.p_fill.setText(st.get("fill") or "")
        self.p_stroke.setText(st.get("stroke") or st.get("border_color") or "")
        self.p_stroke_w.setValue(int(st.get("stroke_width", st.get("border_width", 1)) or 0))
        self.p_radius.setValue(int(st.get("radius", 0) or 0))
        fmt = str(st.get("format") or st.get("symbology") or "code128").lower()
        self.p_format.setCurrentIndex(max(self.p_format.findData(fmt), 0))
        self.p_show_text.setChecked(bool(st.get("show_text", True)))
        self.p_quiet.setValue(int(st.get("quiet_zone", 10)))
        self.p_ec.setCurrentText(str(st.get("error_correction", "M")).upper())
        self.p_qborder.setValue(int(st.get("border", 4)))
        self._update_hint()
        self.p_style.setPlainText(json.dumps(st, ensure_ascii=False))

    def collect_style(self, t):
        style = json.loads(self.p_style.toPlainText() or "{}")
        if not isinstance(style, dict): raise ValueError("стиль должен быть объектом JSON")
        put = lambda k, v: style.__setitem__(k, v) if v not in ("", None) else style.pop(k, None)
        if t in ("text", "field", "barcode"): style["font_size"] = self.p_font.value()
        if t in ("text", "field", "barcode", "qr"): put("color", self.p_color.text().strip())
        if t in ("barcode", "qr"): put("background", self.p_bg.text().strip())
        if t in ("rect", "ellipse", "text", "field"): put("fill", self.p_fill.text().strip())
        if t in ("rect", "ellipse", "line"):
            for k in ("border_color", "border_width", "color", "width"): style.pop(k, None)   # старые ключи → новые
            put("stroke", self.p_stroke.text().strip()); style["stroke_width"] = self.p_stroke_w.value()
        if t == "rect": style["radius"] = self.p_radius.value()
        if t == "barcode":
            style.pop("symbology", None); style["format"] = self.p_format.currentData()
            style["show_text"] = self.p_show_text.isChecked(); style["quiet_zone"] = self.p_quiet.value()
        if t == "qr":
            style["error_correction"] = self.p_ec.currentText(); style["border"] = self.p_qborder.value()
        return style

    def apply_props(self):
        if not self.current: return False
        t = self.current.el["type"]
        err = self.validate_size(t, self.p_w.value(), self.p_h.value())
        if err:
            _warn(self, "Размер", err); return False
        try:
            style = self.collect_style(t)
        except ValueError as e:
            _warn(self, "Стиль", f"Некорректный JSON: {e}"); return False
        if not self.template_mode and self.current is not None:      # этап 15: геометрия вне режима шаблона не меняется
            g = self.current.el
            for _w, k in ((self.p_x, "x"), (self.p_y, "y"), (self.p_w, "w"), (self.p_h, "h")):
                _w.blockSignals(True); _w.setValue(g[k]); _w.blockSignals(False)
        changes = dict(x=self.p_x.value(), y=self.p_y.value(), w=self.p_w.value(), h=self.p_h.value(),
                       z_order=self.p_z.value(), field_name=(self.p_field.currentText() if self.p_field.currentText() != NEW_FIELD else None) or None,
                       static_value=((self.p_text.toPlainText() if t == "text" else self.p_static.text()) or None), style=style)
        el = self.current.el
        changes = {k: v for k, v in changes.items() if el.get(k) != v}
        if not changes: return True              # ничего не изменилось — шага истории нет
        try:
            self.api.update_element(self.current.el["id"], **changes)
        except Exception as e:  # noqa: BLE001 (IntegrityError из CHECK Backend)
            _warn(self, "Ошибка", f"Backend отклонил изменения: {e}"); return False
        self.load(self.side, self.current.el["id"])
        return True

    # --- добавление ---
    def run_tool(self, key):
        """Обработчик кнопки/действия: интерактивные вопросы (поле, файл, цвет) задаются здесь."""
        try:
            return self.add_background() if key == "background" else self.add_element(key)
        except _Cancelled:
            return None

    def set_template_mode_banner(self, on):
        """Этап 15 п.2: в режиме — добавление/перемещение/связывание; вне — блокировка и данные выбранной записи."""
        self.template_mode = bool(on)
        for _w in (self.p_x, self.p_y, self.p_w, self.p_h): _w.setReadOnly(not self.template_mode)
        if hasattr(self, "mode_banner"): self.mode_banner.setVisible(self.template_mode)
        if not self.template_mode: self.show_render = True          # карточка показывает данные выбранной записи
        for it in self.items():
            it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.template_mode); it.handle.setVisible(self.template_mode)
        if not self.template_mode and self.show_render: self.load(self.side, self.current.el["id"] if self.current else None)

    def _locked(self, title):
        if self.template_mode: return False
        _warn(self, title, "Включите «Режим шаблона» на ленте, чтобы изменять шаблон"); return True

    def _show_photo_link(self, el):
        """Этап 15 п.1 (макет): у фото-объекта — состояние связи с полем «Фото» типа «Изображение»."""
        if not el or el.get("type") != "photo": self.photo_link.hide(); return
        fn = el.get("field_name")
        if fn: t = f"🔗 Связан с полем «{fn}» (тип «{PHOTO_FIELD_TYPE}»)"
        else:
            t = f"Объект не связан — при вставке фото создаётся поле «{PHOTO_FIELD_LABEL}» типа «{PHOTO_FIELD_TYPE}»"
        self.photo_link.setText(t); self.photo_link.show()

    def _fill_fields(self, fields=None):
        """Комбо поля объекта: только list_fields() + последний пункт «Новое поле…» (D24)."""
        fields = self.api.list_fields() if fields is None else fields
        cur = self.p_field.currentText(); self.p_field.blockSignals(True); self.p_field.clear(); self.p_field.addItem("")
        for f in fields: self.p_field.addItem(f["name"]); self.p_field.setItemData(self.p_field.count() - 1, f["label"] or f["name"], Qt.ItemDataRole.ToolTipRole)
        self.p_field.addItem(NEW_FIELD); self.p_field.setCurrentText(cur); self.p_field.blockSignals(False)

    def _field_chosen(self):
        if self._locked("Связать поле"): return False
        if self.p_field.currentText() == NEW_FIELD:
            name = self._new_field(); self.p_field.setCurrentText(name or "")
            return bool(name)
        return True

    def _ask_field(self):
        names = [f["name"] for f in self.api.list_fields()] + [NEW_FIELD]
        name, ok = QInputDialog.getItem(self, "Поле", "Поле записи:", names, 0, False)
        if not ok or not name: raise _Cancelled
        if name == NEW_FIELD:
            name = self._new_field()
            if not name: raise _Cancelled
        return name

    def _new_field(self):
        """«Новое поле…» → Менеджер полей; возвращает имя только что созданного поля (или None)."""
        from .main_view import FieldManager
        before = {f["name"] for f in self.api.list_fields()}
        fm = FieldManager(self.api, self); fm.add_field()
        if not fm_hook_active(): fm.exec()
        new = [f["name"] for f in self.api.list_fields() if f["name"] not in before]
        self._fill_fields(); return new[0] if new else None

    def _ask_file(self, title):
        p, _ = QFileDialog.getOpenFileName(self, title, self.api.base_dir, "Изображения (*.png *.jpg *.jpeg *.bmp *.svg)")
        if not p: raise _Cancelled
        return self._rel(p)

    def _rel(self, path):
        try:
            rel = os.path.relpath(path, self.api.base_dir)
            return path if rel.startswith("..") else rel
        except ValueError:
            return path

    def add_element(self, kind="text", *, field_name=None, image_path=None, static_value=None):
        """Создать элемент по центру холста, выделить его. Возвращает id (None — Backend отклонил)."""
        if self._locked("Добавить элемент"): return None
        t = dict((k, tt) for k, _l, tt in TOOLS)[kind]
        if t == "field" and field_name is None: field_name = self._ask_field()
        if t == "image" and image_path is None: image_path = self._ask_file("Изображение (логотип)")
        w, h = DEFAULT_SIZE[t]
        if self.validate_size(t, w, h): raise ValueError("недопустимый размер по умолчанию")
        kw = dict(type=t, x=(CARD_W_PX - w) // 2, y=(CARD_H_PX - h) // 2, w=w, h=h, side=self.side,
                  z_order=max([i.el.get("z_order") or 0 for i in self.items()] + [0]) + 1,
                  style=dict(DEFAULT_STYLE.get(t, {})))
        if t == "text": kw["static_value"] = static_value or "Текст"
        elif t == "field": kw["field_name"] = field_name
        elif t == "image": kw["static_value"] = image_path
        elif t == "barcode": kw["static_value"] = static_value or "123456789012"
        elif t == "qr": kw["static_value"] = static_value or "https://example.org"
        try:
            eid = self.api.create_element(**kw)
        except Exception as e:  # noqa: BLE001 (например, тип ещё не поддержан схемой Backend)
            self.last_error = str(e)
            _warn(self, "Добавление элемента", f"Backend не принял элемент «{TYPE_LABELS[t]}»: {e}")
            return None
        self.load(self.side, eid)
        return eid

    def add_background(self, color=None, image_path=None):
        """Фон стороны через template_backgrounds (set_background)."""
        if self._locked("Фон"): return None
        cur = self.api.get_background(self.side) or {"color": "#FFFFFF", "image_path": None}
        if color is None and image_path is None:
            choice, ok = QInputDialog.getItem(self, "Фон стороны", "Фон:", ["Цвет", "Изображение", "Сбросить"], 0, False)
            if not ok: return None
            if choice == "Цвет":
                c = QColorDialog.getColor(QColor(cur.get("color") or "#FFFFFF"), self, "Цвет фона")
                if not c.isValid(): return None
                color, image_path = c.name(), cur.get("image_path")
            elif choice == "Изображение":
                image_path, color = self._ask_file("Изображение фона"), cur.get("color") or "#FFFFFF"
            else:
                color, image_path = "#FFFFFF", None
        self.api.set_background(self.side, color or cur.get("color") or "#FFFFFF", image_path)
        self.load(self.side)
        return self.api.get_background(self.side)

    def move_z(self, delta):
        if not self.current: return
        eid = self.current.el["id"]
        self.api.update_element(eid, z_order=(self.current.el.get("z_order") or 0) + delta)
        self.load(self.side, eid)

    def delete_element(self):
        if self.current:
            self.api.delete_element(self.current.el["id"]); self.load(self.side)

    def zoom(self, factor):
        """factor None — вписать в окно."""
        self._zoom = None if factor is None else (getattr(self, "_zoom", None) or 1.0) * factor
        if factor is None: self._fit()
        else: self.view.scale(factor, factor)

    def set_grid(self, on, step=20):
        self.grid_on, self.grid_step = bool(on), max(2, int(step)); self.load(self.side, self.current.el["id"] if self.current else None)

    def _draw_grid(self):
        if not getattr(self, "grid_on", False): return
        pen = QPen(QColor(49, 130, 206, 50)); st = self.grid_step
        for x in range(0, CARD_W_PX + 1, st): self.scene.addLine(x, 0, x, CARD_H_PX, pen).setZValue(1)
        for y in range(0, CARD_H_PX + 1, st): self.scene.addLine(0, y, CARD_W_PX, y, pen).setZValue(1)

    def _fit(self):
        self.view.resetTransform()
        self.view.fitInView(self.scene.sceneRect().adjusted(-20, -30, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.view.fitInView(self.scene.sceneRect().adjusted(-20, -30, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)


class _Cancelled(Exception):
    pass


class Ruler(QWidget):
    """Линейка в мм по сцене холста (1011 px = 85,6 мм)."""
    T = 20

    def __init__(self, editor, horizontal):
        super().__init__(editor); self.ed, self.h = editor, horizontal
        (self.setFixedHeight if horizontal else self.setFixedWidth)(self.T)

    def paintEvent(self, ev):
        p = QPainter(self); p.fillRect(self.rect(), QColor("#F1F3F2")); p.setPen(QColor("#555555"))
        f = QFont(); f.setPixelSize(9); p.setFont(f)
        view = self.ed.view
        o = view.mapFromScene(0, 0); e = view.mapFromScene(CARD_W_PX, CARD_H_PX)
        px_per_mm = ((e.x() - o.x()) / 85.6) if self.h else ((e.y() - o.y()) / (CARD_H_PX * MM_PER_PX))
        if px_per_mm <= 0: return
        base = o.x() if self.h else o.y(); length = self.width() if self.h else self.height()
        for mm in range(int(-base / px_per_mm) - 1, int((length - base) / px_per_mm) + 2):
            v = int(base + mm * px_per_mm); t = 9 if mm % 10 == 0 else (6 if mm % 5 == 0 else 3)
            if self.h:
                p.drawLine(v, self.T - t, v, self.T)
                if mm % 10 == 0: p.drawText(v + 2, 9, str(mm))
            else:
                p.drawLine(self.T - t, v, self.T, v)
                if mm % 10 == 0: p.drawText(1, v + 10, str(mm))
