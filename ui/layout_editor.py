"""Редактор макета: холст CR80 1011x638 px, стороны front/back.

Шаблон изначально пустой — UI никогда не создаёт демо-макеты. Фон холста — рендер Backend
(render_card выбранной записи или пустого шаблона); поверх — рамки элементов (UI-оформление)
для выбора, перемещения и изменения размера. Все изменения — через create_element /
update_element / delete_element / set_background.
"""
import json
import os
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QObject, QTimer, QEvent
from PyQt6.QtGui import QBrush, QColor, QPen, QPainter, QPixmap, QAction, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QGraphicsView, QGraphicsScene,
                             QGraphicsRectItem, QGraphicsSimpleTextItem, QGraphicsItem, QGroupBox,
                             QFormLayout, QLabel, QComboBox, QPushButton, QSpinBox, QLineEdit,
                             QPlainTextEdit, QMessageBox, QCheckBox, QToolButton, QGridLayout,
                             QInputDialog, QFileDialog, QColorDialog, QSizePolicy)
from .stage15 import UNLINKED_COLOR, PHOTO_FIELD_LABEL, PHOTO_FIELD_TYPE
from .backend_api import (
    BackendAPI, CARD_W_PX, CARD_H_PX, TYPE_NAMES, SIDE_NAMES,
    scene_width, scene_height, uses_grid_units, px_to_units, units_to_mm, snap_scene,
)

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
        self.handle = QGraphicsRectItem(0, 0, HANDLE, HANDLE, self)
        self.handle.setBrush(QBrush(QColor("#3070d0")))
        self._apply_geom(el["w"], el["h"])

    def _apply_geom(self, w, h):
        if self.is_line:
            self.lw, self.lh = w, h; p = self.LINE_PAD
            self.setRect(QRectF(min(0, w) - p, min(0, h) - p, abs(w) + 2 * p, abs(h) + 2 * p))
            self.handle.setPos(w - HANDLE / 2, h - HANDLE / 2)
        else:
            self.setRect(0, 0, w, h); self.handle.setPos(w - HANDLE, h - HANDLE)

    def _place_handle(self):
        self._apply_geom(*((self.lw, self.lh) if self.is_line else (self.rect().width(), self.rect().height())))

    def set_size(self, w, h):
        self._apply_geom(w, h)

    def mousePressEvent(self, ev):
        self._resizing = bool(self.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable) and self.handle.contains(self.handle.mapFromParent(ev.pos()))
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._resizing:
            x, y = snap_scene(ev.pos().x()), snap_scene(ev.pos().y())
            if self.is_line:
                if x == 0 and y == 0: x = 1          # (0,0) запрещено
                self._apply_geom(x, y)
            else:
                self._apply_geom(max(4, x), max(4, y))
        else:
            super().mouseMoveEvent(ev)
            if uses_grid_units():
                self.setPos(snap_scene(self.x()), snap_scene(self.y()))

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
        self.bus.text_edit_requested.connect(self._focus_text_prop)
        self.scene = QGraphicsScene(0, 0, scene_width(), scene_height(), self)
        self.view = QGraphicsView(self.scene); self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.scene.selectionChanged.connect(self._on_select)
        self.overlaps, self.hint = [], None

        # Действия (инструменты, удаление, порядок, сторона) живут только в ленте главного окна.
        self.template_mode = False       # этап 15 п.2: вне режима шаблона элементы заблокированы
        self.show_render = True          # «Рендер под рамками» — переключается действием ленты
        self.selection_actions = []      # действия ленты, активные только при выделенном объекте

        self._loading = False

        self.mode_banner = QLabel("Режим создания шаблона: расставьте элементы на карточке вручную и выберите поля; сохранение — «✓ Сохранить шаблон» на ленте"); self.mode_banner.setStyleSheet(
            "background:#2E7D6B; color:white; font-weight:600; padding:3px 8px;"); self.mode_banner.hide(); self.mode_banner.setWordWrap(True)
        self.view.setMouseTracking(True); self.view.viewport().setMouseTracking(True)
        self.view.viewport().installEventFilter(self)
        self.hruler, self.vruler = Ruler(self, True), Ruler(self, False)
        cw = QWidget(); g = QGridLayout(cw); g.setContentsMargins(0, 0, 0, 0); g.setSpacing(0)
        corner = QLabel("мм"); corner.setFixedSize(Ruler.T, Ruler.T); corner.setStyleSheet("font-size:8px; background:#F1F3F2;")
        g.addWidget(corner, 0, 0); g.addWidget(self.hruler, 0, 1); g.addWidget(self.vruler, 1, 0); g.addWidget(self.view, 1, 1)
        self.canvas_box = cw
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self.mode_banner); lay.addWidget(cw, 1)
        self.load("front")

    cursor_moved = pyqtSignal(float, float)

    def eventFilter(self, obj, ev):
        if obj is self.view.viewport() and ev.type() == QEvent.Type.MouseMove:
            p = self.view.mapToScene(ev.position().toPoint())
            if uses_grid_units():
                self.cursor_moved.emit(units_to_mm(p.x()), units_to_mm(p.y()))
            else:
                self.cursor_moved.emit(p.x() * MM_PER_PX, p.y() * MM_PER_PX)
        if obj is self.view.viewport() and ev.type() in (QEvent.Type.Paint,):
            self.hruler.update(); self.vruler.update()
        if (obj is self.view.viewport()
                and ev.type() == QEvent.Type.MouseButtonPress
                and ev.button() == Qt.MouseButton.LeftButton
                and ev.modifiers() & Qt.KeyboardModifier.AltModifier):
            self.cycle_select_at(self.view.mapToScene(ev.position().toPoint()))
            return True
        return False

    def elements_at(self, pos):
        """Элементы под точкой сцены, сверху вниз по z (для Alt+клика)."""
        return sorted(
            (i for i in self.scene.items(pos) if isinstance(i, ElementItem)),
            key=lambda i: (-i.zValue(), -(i.el.get("z_order") or 0), i.el["id"]),
        )

    def cycle_select_at(self, pos):
        """Выбрать следующий элемент под точкой (по кругу)."""
        hits = self.elements_at(pos)
        if not hits:
            return None
        cur = self.current
        nxt = hits[(hits.index(cur) + 1) % len(hits)] if cur in hits else hits[0]
        return self.select(nxt.el["id"])

    def set_rulers(self, on):
        self.hruler.setVisible(on); self.vruler.setVisible(on)

    def set_show_render(self, on):
        self.show_render = bool(on); self.load(self.side, self.current.el["id"] if self.current else None)

    def set_side(self, side):
        if side != self.side: self.load(side)

    def select(self, eid):
        """Выбор объекта по id (холст, панель полей, Alt+клик): выделяет объект на холсте."""
        for i in self.items(): i.setSelected(i.el["id"] == eid)
        return self.current

    def set_prop(self, key, value):
        """Единый путь записи свойства: значение кладётся в панель свойств и применяется apply_props."""
        return self.set_props(**{key: value})

    def set_props(self, **values):
        """Несколько свойств за одно применение. Пишет панель «Свойства объекта»."""
        if not self.current: return False
        op = getattr(self, "object_props", None)
        if op is None: return False
        return op.apply_values(**values)

    @staticmethod
    def _spin(lo, hi):
        s = QSpinBox(); s.setRange(lo, hi); return s

    def reload(self):
        self.load(self.side)

    def load(self, side, select_id=None):
        self.side = side; self.current = None
        self.scene.clear(); self.hint = None
        sw, sh = scene_width(), scene_height()
        self.scene.setSceneRect(0, 0, sw, sh)
        if self.show_render:
            pid = self.person_id if self.person_id is not None and self.api.get_person(self.person_id) else None
            self.person_id = pid
            self.canvas_image = self.api.render_card(pid, side)          # рендер Backend
            pm = QPixmap.fromImage(self.canvas_image)
            bg = self.scene.addPixmap(pm)
            if uses_grid_units() and pm.width():
                bg.setScale(sw / pm.width())
        else:
            b = self.api.get_background(side) or {"color": "#FFFFFF"}
            bg = self.scene.addRect(QRectF(0, 0, sw, sh), QPen(Qt.PenStyle.NoPen), QBrush(QColor(b["color"])))
        bg.setZValue(-1)
        self._bg_item = bg
        self.scene.addRect(QRectF(0, 0, sw, sh), QPen(QColor("#888888"))).setZValue(0)
        self._draw_grid()
        fields = self.api.list_fields()
        self.labels = {f["name"]: f.get("label") for f in fields}
        self._fill_fields(fields)
        els = self.api.list_elements(side)
        for el in els:
            it = ElementItem(el, self.bus, self.labels); self.scene.addItem(it)
            self._apply_item_flags(it)
            if el["id"] == select_id: it.setSelected(True)
        if not els:   # подсказка — только оформление редактора, в рендер не попадает
            self.hint = QGraphicsSimpleTextItem(EMPTY_HINT)
            f = QFont(); f.setPointSize(22); self.hint.setFont(f); self.hint.setBrush(QBrush(QColor(120, 120, 120, 160)))
            r = self.hint.boundingRect(); self.hint.setPos((sw - r.width()) / 2, (sh - r.height()) / 2)
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
            elif (it.el.get("style") or {}).get("locked"):
                it.setPen(QPen(QColor("#B8860B"), 2, Qt.PenStyle.DashLine))
        msg = ("Внимание: элементы пересекаются (" + ", ".join(f"#{a}×#{b}" for a, b in self.overlaps) + ")") if self.overlaps else ""
        self.status.emit(msg or f"Макет ({SIDE_LABELS[self.side]}): пересечений нет")

    def refresh_render(self):
        """Обновить рисунок карточки под рамками, не сбрасывая выделение (ввод текста)."""
        if not self.show_render:
            return
        pid = self.person_id if self.person_id is not None and self.api.get_person(self.person_id) else None
        self.person_id = pid
        self.canvas_image = self.api.render_card(pid, self.side)
        pm = QPixmap.fromImage(self.canvas_image)
        bg = getattr(self, "_bg_item", None)
        from PyQt6.QtWidgets import QGraphicsPixmapItem
        if isinstance(bg, QGraphicsPixmapItem):
            bg.setPixmap(pm)
            if uses_grid_units() and pm.width():
                bg.setScale(scene_width() / pm.width())
        else:
            self.load(self.side, self.current.el["id"] if self.current else None)

    def _focus_text_prop(self, item):
        if item is None:
            return
        self.select(item.el["id"])
        op = getattr(self, "object_props", None)
        if op is not None:
            QTimer.singleShot(0, op.focus_text)

    def set_person(self, person_id):
        """Показать на холсте рендер выбранной записи (None — пустой шаблон).
        Подпись «Запись на холсте» убрана: это была только метка, не селектор.
        Выбор записи по-прежнему через таблицу БД → person_id → render_card.
        """
        self.person_id = person_id
        self.load(self.side, self.current.el["id"] if self.current else None)

    def items(self):
        return [i for i in self.scene.items() if isinstance(i, ElementItem)]

    def _apply_item_flags(self, it):
        locked = bool((it.el.get("style") or {}).get("locked"))
        movable = bool(self.template_mode) and not locked
        it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, movable)
        it.handle.setVisible(movable)

    def _commit_geometry(self, item):
        if (item.el.get("style") or {}).get("locked"):
            QTimer.singleShot(0, lambda: self.load(self.side, item.el["id"])); return
        g = {k: snap_scene(v) for k, v in item.geometry().items()}
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

    def _on_select(self):
        self._loading = True
        try: self._on_select_inner()
        finally: self._loading = False

    def _on_select_inner(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, ElementItem)]
        self.current = sel[0] if sel else None
        for a in self.selection_actions: a.setEnabled(bool(sel))
        op = getattr(self, "object_props", None)
        if op is not None: op.sync()

    def apply_props(self):
        """Совместимость с лентой: пишет панель «Свойства объекта»."""
        if not self.current: return False
        op = getattr(self, "object_props", None)
        if op is None: return False
        return op.commit_all()

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
        if hasattr(self, "mode_banner"): self.mode_banner.setVisible(self.template_mode)
        if not self.template_mode: self.show_render = True          # карточка показывает данные выбранной записи
        for it in self.items():
            self._apply_item_flags(it)
        op = getattr(self, "object_props", None)
        if op is not None: op.sync()
        if not self.template_mode and self.show_render: self.load(self.side, self.current.el["id"] if self.current else None)

    def _locked(self, title):
        if self.template_mode: return False
        _warn(self, title, "Включите «Режим шаблона» на ленте, чтобы изменять шаблон"); return True

    def _fill_fields(self, fields=None):
        """Обновить комбо поля на панели «Свойства объекта»."""
        op = getattr(self, "object_props", None)
        if op is not None:
            op.reload_fields(fields)

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
        if uses_grid_units():
            w, h = px_to_units(w), px_to_units(h)
        if self.validate_size(t, w, h): raise ValueError("недопустимый размер по умолчанию")
        sw, sh = scene_width(), scene_height()
        kw = dict(type=t, x=(sw - w) // 2, y=(sh - h) // 2, w=w, h=h, side=self.side,
                  z_order=max([i.el.get("z_order") or 0 for i in self.items()] + [0]) + 1,
                  style=dict(DEFAULT_STYLE.get(t, {})))
        if t == "text": kw["static_value"] = static_value or "Текст"
        elif t == "field": kw["field_name"] = field_name
        elif t == "photo" and field_name: kw["field_name"] = field_name
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
        if not self.current: return
        if (self.current.el.get("style") or {}).get("locked"):
            _warn(self, "Удаление", "Объект зафиксирован — сначала снимите фиксацию в свойствах")
            return
        self.api.delete_element(self.current.el["id"]); self.load(self.side)

    def zoom(self, factor):
        """factor None — вписать в окно."""
        self._zoom = None if factor is None else (getattr(self, "_zoom", None) or 1.0) * factor
        if factor is None: self._fit()
        else: self.view.scale(factor, factor)

    def set_grid(self, on, step=None):
        if step is None:
            step = 10 if uses_grid_units() else 20
        lo = 1 if uses_grid_units() else 2
        self.grid_on, self.grid_step = bool(on), max(lo, int(step))
        self.load(self.side, self.current.el["id"] if self.current else None)

    def _draw_grid(self):
        if not getattr(self, "grid_on", False): return
        pen = QPen(QColor(49, 130, 206, 50)); st = self.grid_step
        sw, sh = scene_width(), scene_height()
        for x in range(0, sw + 1, st): self.scene.addLine(x, 0, x, sh, pen).setZValue(1)
        for y in range(0, sh + 1, st): self.scene.addLine(0, y, sw, y, pen).setZValue(1)

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
        o = view.mapFromScene(0, 0); e = view.mapFromScene(scene_width(), scene_height())
        h_mm = 54.0 if uses_grid_units() else (CARD_H_PX * MM_PER_PX)
        px_per_mm = ((e.x() - o.x()) / 85.6) if self.h else ((e.y() - o.y()) / h_mm)
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
