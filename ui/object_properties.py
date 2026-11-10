"""Панель «Свойства объекта» в стиле Smart IDesigner (QDockWidget + дерево свойств).

Заголовок на русском. Группы: База, Position, Border, Background, Шрифт, Фото, Поле,
Штрихкод / QR-код, Дополнительно. Laser нет.
Единственный путь записи свойств элемента (лента зовёт set_props → apply_values).
"""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDockWidget, QDoubleSpinBox, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .backend_api import (
    SIDE_NAMES, mm_to_stored, stored_to_mm, uses_grid_units,
    update_element_style_available,
)


BORDER_STYLES = (("none", "Нет"), ("solid", "Сплошная"), ("dash", "Пунктир"), ("dot", "Точки"))


def _mm_spin(lo=-500.0, hi=500.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(1)
    s.setSingleStep(0.1)
    s.setRange(lo, hi)
    s.setSuffix(" мм")
    s.setKeyboardTracking(False)
    s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
    s.setMaximumHeight(22)
    return s


def _deg_spin() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(1)
    s.setSingleStep(1.0)
    s.setRange(-360.0, 360.0)
    s.setSuffix("°")
    s.setKeyboardTracking(False)
    s.setMaximumHeight(22)
    return s


def _int_spin(lo, hi, suffix="") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    s.setMaximumHeight(22)
    return s


def _as_hex(value) -> str:
    """Только '#RRGGBB'. Пустое / невалидное → ''."""
    if not value:
        return ""
    c = QColor(str(value))
    if not c.isValid():
        return ""
    return c.name().upper()


def _style_of(el) -> dict:
    return dict(el.get("style") or {})


def _border_style(st):
    v = st.get("border_style")
    if v in ("none", "solid", "dash", "dot"):
        return v
    if st.get("stroke") or st.get("border_color") or st.get("border_width"):
        return "solid"
    return "none"


def _border_width_stored(st):
    if st.get("border_width") is not None:
        return int(st.get("border_width") or 0)
    return int(st.get("stroke_width") or 0)


def _border_color(st):
    return _as_hex(st.get("border_color") or st.get("stroke") or "#000000") or "#000000"


def _bg_fill(st):
    if "bg_fill" in st:
        return bool(st.get("bg_fill"))
    return bool(st.get("fill"))


def _bg_color(st):
    return _as_hex(st.get("bg_color") or st.get("fill") or "#FFFFFF") or "#FFFFFF"


def _warn(parent, title, text):
    from .layout_editor import _warn as _ed_warn
    _ed_warn(parent, title, text)


class ColorCell(QWidget):
    """Квадрат цвета + текст «R; G; B»; клик открывает QColorDialog."""
    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hex = "#000000"
        self.swatch = QLabel()
        self.swatch.setFixedSize(16, 16)
        self.swatch.setStyleSheet("border:1px solid #333;")
        self.text = QLabel("0; 0; 0")
        self.text.setStyleSheet("color:#222;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(6)
        lay.addWidget(self.swatch, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.text, 1, Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_color("#000000")

    def set_color(self, value):
        hx = _as_hex(value)
        if not hx:
            self._hex = ""
            self.text.setText("—")
            self.swatch.setStyleSheet("border:1px solid #333; background:#ffffff;")
            return
        c = QColor(hx)
        self._hex = c.name().upper()
        self.text.setText(f"{c.red()}; {c.green()}; {c.blue()}")
        self.swatch.setStyleSheet(f"border:1px solid #333; background:{c.name()};")

    def color_hex(self) -> str:
        return self._hex

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        start = QColor(self._hex) if self._hex else QColor(0, 0, 0)
        c = QColorDialog.getColor(start, self, "Цвет")
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit(c.name().upper())


class ObjectPropertiesPanel(QWidget):
    """Дерево свойств выбранного элемента. Это единственный write path панели."""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._loading = False

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(False)
        self.tree.setAnimated(False)
        self.tree.setColumnWidth(0, 150)
        self.tree.setStyleSheet(
            "QTreeWidget{border:none; background:#F3F3F3; font-size:11px; color:#222;}"
            "QTreeWidget::item{padding:1px 0; color:#222;}"
            "QTreeWidget::item:selected{background:#D0E4F5; color:#000;}"
            "QTreeWidget:disabled, QTreeWidget::item:!enabled{color:#333;}"
            "QComboBox,QDoubleSpinBox,QSpinBox,QLineEdit,QCheckBox,QPlainTextEdit{font-size:11px; min-height:18px;}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tree)

        self._build_tree()
        self._wire()
        self.sync()

    def _group(self, title, expanded=True) -> QTreeWidgetItem:
        g = QTreeWidgetItem([title, ""])
        f = QFont(g.font(0)); f.setBold(True); f.setPointSize(10)
        g.setFont(0, f)
        bg = QColor("#C0C0C0")
        g.setBackground(0, bg); g.setBackground(1, bg)
        # Явный цвет заголовка: при Disabled у палитры текст иначе сливается с #C0C0C0.
        fg = self.tree.palette().color(self.tree.palette().ColorGroup.Disabled,
                                       self.tree.palette().ColorRole.WindowText)
        if fg.value() > 180:  # слишком светлый — заголовок пропадёт
            fg = QColor("#333333")
        g.setForeground(0, fg)
        g.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.tree.addTopLevelItem(g)
        g.setExpanded(expanded)
        return g

    def _row(self, group, name, widget) -> QTreeWidgetItem:
        it = QTreeWidgetItem([name, ""])
        it.setFlags(Qt.ItemFlag.ItemIsEnabled)
        group.addChild(it)
        self.tree.setItemWidget(it, 1, widget)
        return it

    def _build_tree(self):
        self.g_base = self._group("База")
        self.w_type = QLabel("—")
        self.w_type.setWordWrap(True)
        self.w_page = QComboBox()
        self.w_page.addItem(SIDE_NAMES["front"], "front")
        self.w_page.addItem(SIDE_NAMES["back"], "back")
        self.w_panel = QLabel("—")
        self.w_lock = QCheckBox()
        self._row(self.g_base, "Элемент", self.w_type)
        self.w_text = QPlainTextEdit()
        self.w_text.setFixedHeight(64)
        self.w_text.setTabChangesFocus(True)
        self.w_text.setPlaceholderText("Текст на карточке")
        self.row_text = self._row(self.g_base, "Текст", self.w_text)
        self._row(self.g_base, "Страница", self.w_page)
        self._row(self.g_base, "Панель", self.w_panel)
        self._row(self.g_base, "Объект фиксирован", self.w_lock)

        self.g_pos = self._group("Position")
        self.w_left = _mm_spin(); self.w_top = _mm_spin()
        self.w_width = _mm_spin(0.0, 500.0); self.w_height = _mm_spin(0.0, 500.0)
        self.w_rot = _deg_spin()
        self._row(self.g_pos, "Левый", self.w_left)
        self._row(self.g_pos, "Вверх", self.w_top)
        self._row(self.g_pos, "Ширина", self.w_width)
        self._row(self.g_pos, "Высота", self.w_height)
        self._row(self.g_pos, "Вращать", self.w_rot)

        self.g_border = self._group("Border")
        self.w_bstyle = QComboBox()
        for key, lab in BORDER_STYLES:
            self.w_bstyle.addItem(lab, key)
        self.w_bwidth = _mm_spin(0.0, 20.0)
        self.w_bcolor = ColorCell()
        self._row(self.g_border, "Стиль", self.w_bstyle)
        self._row(self.g_border, "Ширина", self.w_bwidth)
        self._row(self.g_border, "Цвет", self.w_bcolor)
        self.w_radius = _mm_spin(0.0, 50.0)
        self.row_radius = self._row(self.g_border, "Радиус, мм", self.w_radius)

        self.g_bg = self._group("Background")
        self.w_fill_on = QComboBox(); self.w_fill_on.addItems(["Нет", "Да"])
        self.w_fill_color = ColorCell()
        self._row(self.g_bg, "Заполнить", self.w_fill_on)
        self._row(self.g_bg, "Цвет", self.w_fill_color)

        self.g_font = self._group("Шрифт")
        self.w_ffamily = QComboBox(); self.w_ffamily.setMinimumContentsLength(8)
        self.w_fsize = QDoubleSpinBox(); self.w_fsize.setRange(4, 200); self.w_fsize.setDecimals(0)
        self.w_fsize.setSuffix(" pt"); self.w_fsize.setMaximumHeight(22)
        self.w_fcolor = ColorCell()
        self._row(self.g_font, "Семейство", self.w_ffamily)
        self._row(self.g_font, "Размер", self.w_fsize)
        self._row(self.g_font, "Цвет", self.w_fcolor)

        self.g_photo = self._group("Фото")
        self.w_photo_link = QLabel("—"); self.w_photo_link.setWordWrap(True)
        self.w_photo_link.setStyleSheet("color:#1F4E8C;")
        self._row(self.g_photo, "Связь", self.w_photo_link)

        self.g_bind = self._group("Поле")
        self.w_field = QComboBox(); self.w_field.setEditable(True)
        self.w_static = QLineEdit()
        self.row_field = self._row(self.g_bind, "Поле записи", self.w_field)
        self.row_static = self._row(self.g_bind, "Значение/путь", self.w_static)

        from .layout_editor import FORMATS, EC_LEVELS
        self.g_barcode = self._group("Штрихкод")
        self.w_format = QComboBox()
        for k, v in FORMATS:
            self.w_format.addItem(v, k)
        self.w_show_text = QCheckBox("Показывать текст")
        self.w_hint = QLabel("")
        self.w_hint.setStyleSheet("color:#666;")
        self.w_hint.setWordWrap(True)
        self.w_quiet = _int_spin(0, 200)
        self._row(self.g_barcode, "Формат", self.w_format)
        self._row(self.g_barcode, "Текст", self.w_show_text)
        self._row(self.g_barcode, "Подсказка", self.w_hint)
        self._row(self.g_barcode, "Тихая зона", self.w_quiet)

        self.g_qr = self._group("QR-код")
        self.w_ec = QComboBox(); self.w_ec.addItems(EC_LEVELS)
        self.w_qborder = _int_spin(0, 50)
        self._row(self.g_qr, "Коррекция", self.w_ec)
        self._row(self.g_qr, "Поле QR, мод.", self.w_qborder)

        self.g_extra = self._group("Дополнительно", expanded=False)
        self.w_z = _int_spin(-1000, 1000)
        self.w_style = QPlainTextEdit()
        self.w_style.setFixedHeight(80)
        self.w_style.setTabChangesFocus(True)
        self._row(self.g_extra, "Слой (z)", self.w_z)
        self._row(self.g_extra, "Стиль (JSON)", self.w_style)

        self.groups = {
            "base": self.g_base, "pos": self.g_pos, "border": self.g_border,
            "bg": self.g_bg, "font": self.g_font, "photo": self.g_photo,
            "bind": self.g_bind, "barcode": self.g_barcode, "qr": self.g_qr,
            "extra": self.g_extra,
        }

    def _wire(self):
        for w in (self.w_left, self.w_top, self.w_width, self.w_height):
            w.editingFinished.connect(self._apply_geometry)
        self.w_rot.editingFinished.connect(self._apply_rotation)
        self.w_page.activated.connect(self._apply_page)
        self.w_lock.toggled.connect(self._apply_lock)
        self.w_bstyle.activated.connect(self._apply_border)
        self.w_bwidth.editingFinished.connect(self._apply_border)
        self.w_bcolor.changed.connect(lambda *_: self._apply_border())
        self.w_fill_on.activated.connect(self._apply_background)
        self.w_fill_color.changed.connect(lambda *_: self._apply_background())
        self._font_timer = QTimer(self, singleShot=True, interval=300, timeout=self._apply_font)
        self.w_fsize.valueChanged.connect(lambda: None if self._loading else self._font_timer.start())
        self._radius_timer = QTimer(self, singleShot=True, interval=300, timeout=self._apply_radius)
        self.w_radius.valueChanged.connect(lambda: None if self._loading else self._radius_timer.start())
        self.w_fcolor.changed.connect(lambda *_: self._apply_font())
        self.w_ffamily.activated.connect(self._apply_font)
        self.w_field.activated.connect(self._apply_binding)
        self.w_static.editingFinished.connect(self._apply_binding)
        self.w_format.activated.connect(self._apply_barcode)
        self.w_show_text.toggled.connect(self._apply_barcode)
        self.w_quiet.editingFinished.connect(self._apply_barcode)
        self.w_ec.activated.connect(self._apply_qr)
        self.w_qborder.editingFinished.connect(self._apply_qr)
        self.w_z.editingFinished.connect(self._apply_z)
        self._style_timer = QTimer(self, singleShot=True, interval=700, timeout=self._apply_json)
        self.w_style.textChanged.connect(lambda: None if self._loading else self._style_timer.start())
        self._text_timer = QTimer(self, singleShot=True, interval=300, timeout=self._apply_text)
        self.w_text.textChanged.connect(lambda: None if self._loading else self._text_timer.start())

    def expand_all(self, extra=False):
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            if g is self.g_extra:
                g.setExpanded(bool(extra))
            elif not g.isHidden():
                g.setExpanded(True)

    def expand_extra(self):
        self.g_extra.setExpanded(True)

    def _set_group_visible(self, group, visible):
        group.setHidden(not visible)

    def _el(self):
        cur = getattr(self.editor, "current", None)
        return None if cur is None else cur.el

    def _locked(self):
        el = self._el()
        return bool(el and (_style_of(el).get("locked")))

    def _can_move(self):
        return bool(getattr(self.editor, "template_mode", False)) and not self._locked()

    def _field_widgets(self):
        """Виджеты значений (не заголовки групп): их гасим, само дерево — нет."""
        out = []
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                w = self.tree.itemWidget(g.child(j), 1)
                if w is not None:
                    out.append(w)
        return out

    def _set_fields_enabled(self, on):
        for w in self._field_widgets():
            w.setEnabled(on)

    def sync(self):
        ed = self.editor
        cur = getattr(ed, "current", None)
        self._loading = True
        try:
            enabled = cur is not None
            # Дерево (заголовки База/Position/…) остаётся включённым и читаемым.
            self.tree.setEnabled(True)
            self._set_fields_enabled(enabled)
            if not enabled:
                self._font_timer.stop()
                self._radius_timer.stop()
                self._font_eid = None
                self.w_type.setText("—")
                return
            e = {**cur.el, **cur.geometry()}
            t = e.get("type")
            st = e.get("style") or {}
            eid = e.get("id")
            if getattr(self, "_font_eid", None) != eid:
                self._font_timer.stop()
                self._radius_timer.stop()
            self._font_eid = eid
            from .layout_editor import element_caption
            self.w_type.setText(element_caption(e, getattr(ed, "labels", {})))

            side = e.get("side") or ed.side
            i = self.w_page.findData(side)
            if i >= 0:
                self.w_page.setCurrentIndex(i)
            self.w_panel.setText("—")
            self.w_lock.setChecked(bool(st.get("locked")))

            self.w_left.setValue(stored_to_mm(e.get("x")))
            self.w_top.setValue(stored_to_mm(e.get("y")))
            self.w_width.setValue(stored_to_mm(e.get("w")))
            self.w_height.setValue(stored_to_mm(e.get("h")))
            try:
                rot = float(st.get("rotation") or 0)
            except (TypeError, ValueError):
                rot = 0.0
            self.w_rot.setValue(rot)

            tmpl = bool(getattr(ed, "template_mode", False))
            locked = bool(st.get("locked"))
            movable = tmpl and not locked
            is_line = t == "line"
            for w in (self.w_left, self.w_top, self.w_width, self.w_height):
                w.setReadOnly(not movable)
            self.w_rot.setEnabled(not is_line)
            self.w_rot.setReadOnly(is_line or not movable)
            self.w_page.setEnabled(movable)
            self.w_lock.setEnabled(tmpl)
            # Текст можно править вне режима шаблона; блокирует только style.locked
            self.w_text.setReadOnly(locked)
            if t != "text" or not (self.w_text.hasFocus() or self._text_timer.isActive()):
                self.w_text.setPlainText(e.get("static_value") or "")

            bs = _border_style(st)
            bi = self.w_bstyle.findData(bs)
            if bi >= 0:
                self.w_bstyle.setCurrentIndex(bi)
            self.w_bwidth.setValue(stored_to_mm(_border_width_stored(st)))
            self.w_bcolor.set_color(_border_color(st))
            if not self._radius_timer.isActive():
                self.w_radius.setValue(stored_to_mm(int(st.get("radius", 0) or 0)))
            self.row_radius.setHidden(t != "rect")
            self.w_radius.setEnabled(t == "rect")

            self.w_fill_on.setCurrentIndex(1 if _bg_fill(st) else 0)
            self.w_fill_color.set_color(_bg_color(st))

            self._fill_families(st)
            if not self._font_timer.isActive():
                self.w_fsize.setValue(int(st.get("font_size", 8 if t == "barcode" else 14)))
            self.w_fcolor.set_color(st.get("color") or "#000000")

            from .stage15 import PHOTO_FIELD_LABEL, PHOTO_FIELD_TYPE
            if t == "photo":
                fn = e.get("field_name")
                if fn:
                    self.w_photo_link.setText(f"Связан с полем «{fn}» (тип «{PHOTO_FIELD_TYPE}»)")
                else:
                    self.w_photo_link.setText(
                        f"Не связан — при вставке фото создаётся поле «{PHOTO_FIELD_LABEL}»"
                    )
            else:
                self.w_photo_link.setText("—")

            self._sync_field_combo(e.get("field_name") or "")
            self.w_static.setText(e.get("static_value") or "")

            fmt = str(st.get("format") or st.get("symbology") or "code128").lower()
            fi = self.w_format.findData(fmt)
            self.w_format.setCurrentIndex(max(fi, 0))
            self.w_show_text.setChecked(bool(st.get("show_text", True)))
            self.w_quiet.setValue(int(st.get("quiet_zone", 10) or 0))
            self._update_barcode_hint()
            self.w_ec.setCurrentText(str(st.get("error_correction", "M")).upper())
            self.w_qborder.setValue(int(st.get("border", 4) or 0))

            self.w_z.setValue(int(e.get("z_order") or 0))
            self.w_style.setPlainText(json.dumps(st, ensure_ascii=False, indent=2))

            show_border_bg = t in ("rect", "ellipse", "line", "text", "field", "photo", "image")
            self._set_group_visible(self.g_border, show_border_bg)
            self._set_group_visible(self.g_bg, show_border_bg and t != "line")
            self._set_group_visible(self.g_font, t in ("text", "field", "barcode"))
            self._set_group_visible(self.g_photo, t == "photo")
            self.row_text.setHidden(t != "text")
            self._set_group_visible(self.g_bind, t in ("field", "barcode", "qr", "photo", "image"))
            self.row_static.setHidden(t not in ("image", "barcode", "qr"))
            self._set_group_visible(self.g_barcode, t == "barcode")
            self._set_group_visible(self.g_qr, t == "qr")
            self._set_group_visible(self.g_extra, True)
            self._set_group_visible(self.g_base, True)
            self._set_group_visible(self.g_pos, True)

            for g in (self.g_base, self.g_pos, self.g_border, self.g_bg, self.g_font,
                      self.g_photo, self.g_bind, self.g_barcode, self.g_qr):
                if not g.isHidden():
                    g.setExpanded(True)
        finally:
            self._loading = False

    def _update_barcode_hint(self):
        ean = self.w_format.currentData() == "ean13"
        self.w_hint.setText("12 или 13 цифр" if ean else "Поле записи или статический текст")
        self.w_static.setPlaceholderText("12 или 13 цифр" if ean else "")

    def _fill_families(self, st=None):
        api = getattr(self.editor, "api", None)
        fams = []
        current = (st or {}).get("font_family") or ""
        if api is not None:
            fn = getattr(api, "list_fonts", None) or getattr(api, "list_font_families", None)
            try:
                fams = list(fn()) if callable(fn) else []
            except Exception:
                fams = []
            if not current:
                try:
                    current = (api.get_template_style() or {}).get("font_family") or ""
                except Exception:
                    current = ""
        self.w_ffamily.blockSignals(True)
        self.w_ffamily.clear()
        self.w_ffamily.addItems(fams)
        if current:
            i = self.w_ffamily.findText(current)
            if i >= 0:
                self.w_ffamily.setCurrentIndex(i)
        self.w_ffamily.blockSignals(False)

    def reload_fields(self, fields=None):
        cur = self.w_field.currentText() if self.w_field.count() else ""
        el = self._el()
        if el is not None:
            cur = el.get("field_name") or cur
        self._sync_field_combo(cur)

    def _sync_field_combo(self, current):
        ed = self.editor
        from .layout_editor import NEW_FIELD
        self.w_field.blockSignals(True)
        self.w_field.clear()
        self.w_field.addItem("")
        try:
            for f in ed.api.list_fields():
                self.w_field.addItem(f["name"])
        except Exception:
            pass
        self.w_field.addItem(NEW_FIELD)
        self.w_field.setCurrentText(current or "")
        self.w_field.blockSignals(False)

    def _write_element(self, **changes):
        ed = self.editor
        reload = changes.pop("reload", True)
        if not ed.current:
            return False
        blocked = {"x", "y", "w", "h", "side"}
        if self._locked() and blocked.intersection(changes):
            _warn(self, "Объект зафиксирован", "Снимите «Объект фиксирован», чтобы менять положение или сторону")
            self.sync()
            return False
        if not getattr(ed, "template_mode", False) and blocked.intersection(changes):
            self.sync()
            return False
        eid = ed.current.el["id"]
        try:
            ed.api.update_element(eid, **changes)
        except Exception as e:
            _warn(self, "Ошибка", f"Backend отклонил изменения: {e}")
            return False
        ed.current.el.update(changes)
        if reload:
            ed.load(changes.get("side", ed.side), eid)
        return True

    def _write_style(self, **keys):
        ed = self.editor
        if not ed.current:
            return False
        eid = ed.current.el["id"]
        fn = getattr(ed.api, "update_element_style", None)
        if callable(fn) and update_element_style_available():
            try:
                st = fn(eid, **keys)
            except Exception as e:
                _warn(self, "Ошибка", f"Backend отклонил стиль: {e}")
                return False
            if st is None:
                # TODO: update_element_style исчез — держим ключи только в памяти
                st = _style_of(ed.current.el)
                for k, v in keys.items():
                    if v is None:
                        st.pop(k, None)
                    else:
                        st[k] = v
                ed.current.el["style"] = st
                self._refresh_after_style(keys)
                return True
            ed.current.el["style"] = st
            self._refresh_after_style(keys)
            return True
        # TODO: Backend без update_element_style — только память панели
        st = _style_of(ed.current.el)
        for k, v in keys.items():
            if v is None:
                st.pop(k, None)
            else:
                st[k] = v
        ed.current.el["style"] = st
        self._refresh_after_style(keys)
        return True

    def _refresh_after_style(self, keys=None):
        """Один перерисов холста после записи стиля (без полной пересборки сцены)."""
        ed = self.editor
        if ed.current is not None and keys and "locked" in keys and hasattr(ed, "_apply_item_flags"):
            ed._apply_item_flags(ed.current)
        refresh = getattr(ed, "refresh_render", None)
        if callable(refresh):
            refresh()
        elif ed.current:
            ed.load(ed.side, ed.current.el["id"])

    def _style_payload_border(self):
        style = self.w_bstyle.currentData() or "none"
        width = mm_to_stored(self.w_bwidth.value())
        width = max(0, min(200 if uses_grid_units() else 10**9, int(width)))
        if uses_grid_units():
            width = max(0, min(200, width))
        color = self.w_bcolor.color_hex() or "#000000"
        keys = {"border_style": style, "border_width": int(width), "border_color": color}
        return keys

    def _style_payload_bg(self):
        on = self.w_fill_on.currentIndex() == 1
        color = self.w_fill_color.color_hex() or "#FFFFFF"
        keys = {"bg_fill": on, "bg_color": color}
        return keys

    def _apply_geometry(self):
        if self._loading or not self.editor.current:
            return False
        x, y = mm_to_stored(self.w_left.value()), mm_to_stored(self.w_top.value())
        w, h = mm_to_stored(self.w_width.value()), mm_to_stored(self.w_height.value())
        t = self.editor.current.el.get("type")
        err = self.editor.validate_size(t, w, h)
        if err:
            _warn(self, "Размер", err)
            self.sync()
            return False
        cur = self.editor.current.el
        if all(cur.get(k) == v for k, v in (("x", x), ("y", y), ("w", w), ("h", h))):
            return True
        return bool(self._write_element(x=x, y=y, w=w, h=h))

    def _apply_rotation(self):
        if self._loading or not self.editor.current:
            return
        if self.editor.current.el.get("type") == "line":
            return
        if not self._can_move():
            self.sync()
            return
        self._write_style(rotation=float(self.w_rot.value()))

    def _apply_page(self):
        if self._loading or not self.editor.current:
            return
        side = self.w_page.currentData()
        if self.editor.current.el.get("side") == side:
            return
        self._write_element(side=side)

    def _apply_lock(self, *_):
        if self._loading or not self.editor.current:
            return
        self._write_style(locked=bool(self.w_lock.isChecked()))

    def _apply_border(self, *_):
        if self._loading or not self.editor.current:
            return
        self._write_style(**self._style_payload_border())

    def _radius_stored(self):
        return max(0, int(mm_to_stored(self.w_radius.value())))

    def _apply_radius(self, *_):
        if self._loading or not self.editor.current:
            return
        if self.editor.current.el.get("type") != "rect":
            return
        val = self._radius_stored()
        if int(_style_of(self.editor.current.el).get("radius") or 0) == val:
            return
        self._write_style(radius=val)

    def _apply_background(self, *_):
        if self._loading or not self.editor.current:
            return
        # заливка объекта, не фон страницы (get_background/set_background)
        self._write_style(**self._style_payload_bg())

    def _apply_font(self, *_):
        if self._loading or not self.editor.current:
            return
        keys = {
            "font_size": int(self.w_fsize.value()),
            "color": self.w_fcolor.color_hex() or "#000000",
        }
        fam = self.w_ffamily.currentText()
        if fam:
            keys["font_family"] = fam
        st = _style_of(self.editor.current.el)
        if (int(st.get("font_size") or 0) == keys["font_size"]
                and _as_hex(st.get("color") or "#000000") == keys["color"]
                and (not fam or st.get("font_family") == fam)):
            return
        self._write_style(**keys)

    def _apply_binding(self, *_):
        if self._loading or not self.editor.current:
            return
        from .layout_editor import NEW_FIELD
        text = self.w_field.currentText()
        if text == NEW_FIELD:
            name = self.editor._new_field()
            if not name:
                self.sync()
                return
            text = name
        self._write_element(field_name=text or None, static_value=self.w_static.text() or None)

    def _apply_barcode(self, *_):
        if self._loading or not self.editor.current:
            return
        self._update_barcode_hint()
        self._write_style(
            format=self.w_format.currentData() or "code128",
            show_text=self.w_show_text.isChecked(),
            quiet_zone=int(self.w_quiet.value()),
            symbology=None,
        )

    def _apply_qr(self, *_):
        if self._loading or not self.editor.current:
            return
        # style.border у QR — модули поля, не рамка объекта
        self._write_style(
            error_correction=self.w_ec.currentText() or "M",
            border=int(self.w_qborder.value()),
        )

    def _apply_z(self):
        if self._loading or not self.editor.current:
            return
        self._write_element(z_order=int(self.w_z.value()))

    def _apply_json(self):
        if self._loading or not self.editor.current:
            return
        try:
            style = json.loads(self.w_style.toPlainText() or "{}")
        except ValueError as e:
            _warn(self, "Стиль", f"Некорректный JSON: {e}")
            return
        if not isinstance(style, dict):
            _warn(self, "Стиль", "стиль должен быть объектом JSON")
            return
        try:
            self.editor.api.update_element(self.editor.current.el["id"], style=style)
        except Exception as e:
            _warn(self, "Ошибка", f"Backend отклонил стиль: {e}")
            return
        self.editor.load(self.editor.side, self.editor.current.el["id"])

    def _apply_text(self):
        if self._loading or not self.editor.current:
            return
        if self.editor.current.el.get("type") != "text":
            return
        if self._locked():
            return
        val = self.w_text.toPlainText()
        cur = self.editor.current.el.get("static_value") or ""
        if cur == val:
            return
        eid = self.editor.current.el["id"]
        try:
            self.editor.api.update_element(eid, static_value=val or None)
        except Exception as e:
            _warn(self, "Ошибка", f"Backend отклонил текст: {e}")
            return
        self.editor.current.el["static_value"] = val or None
        refresh = getattr(self.editor, "refresh_render", None)
        if callable(refresh):
            refresh()
        else:
            self.editor.load(self.editor.side, eid)

    def focus_text(self):
        """Фокус в поле «Текст» (двойной щелчок по объекту на холсте)."""
        if self.row_text.isHidden():
            return
        self.g_base.setExpanded(True)
        self.w_text.setReadOnly(self._locked())
        if not self.w_text.isReadOnly():
            self.w_text.setFocus(Qt.FocusReason.OtherFocusReason)

    def apply_values(self, **values):
        """Запись со стороны ленты / set_props (x/y/w/h — единицы хранения сцены)."""
        if not self.editor.current:
            return False
        geom = {}
        style_keys = {}
        for k in ("x", "y", "w", "h", "side", "z_order", "field_name", "static_value"):
            if k in values:
                geom[k] = values[k]
        if "font_size" in values:
            style_keys["font_size"] = int(values["font_size"])
        if "color" in values:
            style_keys["color"] = _as_hex(values["color"]) or "#000000"
        if "fill" in values:
            hx = _as_hex(values["fill"]) or "#FFFFFF"
            style_keys["bg_fill"] = True
            style_keys["bg_color"] = hx
        if "stroke" in values:
            hx = _as_hex(values["stroke"]) or "#000000"
            style_keys["border_color"] = hx
            if (_style_of(self.editor.current.el).get("border_style") or "none") == "none":
                style_keys["border_style"] = "solid"
        if "stroke_width" in values:
            # лента/старые вызовы: значение уже в единицах хранения (как border_width)
            v = int(values["stroke_width"])
            if uses_grid_units():
                v = max(0, min(200, v))
            style_keys["border_width"] = v
        if "border_width" in values:
            style_keys["border_width"] = int(values["border_width"])
        if "radius" in values:
            style_keys["radius"] = max(0, int(values["radius"]))
        if "rotation" in values:
            style_keys["rotation"] = float(values["rotation"])
        if "locked" in values:
            style_keys["locked"] = bool(values["locked"])
        ok = True
        if geom:
            ok = bool(self._write_element(**geom)) and ok
        if style_keys:
            ok = bool(self._write_style(**style_keys)) and ok
        self.sync()
        return ok

    def flush(self):
        """Сразу применить отложенные правки (таймеры шрифта, радиуса, текста, JSON)."""
        for timer in (self._font_timer, self._radius_timer, self._text_timer, self._style_timer):
            if timer.isActive():
                timer.stop()
                timer.timeout.emit()

    def commit_all(self):
        """Применить текущие виджеты (совместимость с apply_props)."""
        if not self.editor.current:
            return False
        self.flush()
        ed = self.editor
        t = ed.current.el.get("type")
        x, y = mm_to_stored(self.w_left.value()), mm_to_stored(self.w_top.value())
        w, h = mm_to_stored(self.w_width.value()), mm_to_stored(self.w_height.value())
        err = ed.validate_size(t, w, h)
        if err:
            _warn(self, "Размер", err)
            self.sync()
            return False
        if t == "text":
            self._apply_text()
        geom = dict(x=x, y=y, w=w, h=h)
        if t in ("field", "barcode", "qr", "photo", "image"):
            from .layout_editor import NEW_FIELD
            name = self.w_field.currentText()
            if name == NEW_FIELD:
                name = ed._new_field()
                if not name:
                    self.sync()
                    return False
            geom["field_name"] = name or None
            geom["static_value"] = self.w_static.text() or None
        cur = ed.current.el
        need_geom = any(cur.get(k) != v for k, v in geom.items())
        if need_geom and not self._write_element(reload=False, **geom):
            return False
        style_keys = dict(
            locked=bool(self.w_lock.isChecked()),
            **self._style_payload_border(),
            **self._style_payload_bg(),
            font_size=int(self.w_fsize.value()),
            color=self.w_fcolor.color_hex() or "#000000",
        )
        fam = self.w_ffamily.currentText()
        if fam:
            style_keys["font_family"] = fam
        if t != "line":
            style_keys["rotation"] = float(self.w_rot.value())
        if t == "rect":
            style_keys["radius"] = self._radius_stored()
        if t == "barcode":
            style_keys.update(
                format=self.w_format.currentData() or "code128",
                show_text=self.w_show_text.isChecked(),
                quiet_zone=int(self.w_quiet.value()),
                symbology=None,
            )
        if t == "qr":
            style_keys.update(
                error_correction=self.w_ec.currentText() or "M",
                border=int(self.w_qborder.value()),
            )
        if not self._write_style(**style_keys):
            return False
        if ed.current:
            ed.load(ed.side, ed.current.el["id"])
        return True


class ObjectPropertiesDock(QDockWidget):
    def __init__(self, editor, parent=None):
        super().__init__("Свойства объекта", parent)
        self.setObjectName("objectPropertiesDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.panel = ObjectPropertiesPanel(editor)
        self.setWidget(self.panel)
        self.setMinimumWidth(280)
        self.resize(320, 640)

    def flush(self):
        """Прокси к панели: сразу применить отложенные правки."""
        self.panel.flush()
