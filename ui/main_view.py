"""Главный вид: собственные простые иконки, панель «Предпросмотр / Поля», диалоги
«Очередь печати», «Положение», «Настройка», «Захват изображения».
Весь рендер — только через Backend (render_card); SQL нет."""
import os
from PyQt6.QtCore import Qt, QPointF, QRectF, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QPolygonF, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox, QFormLayout,
                             QLineEdit, QPushButton, QSpinBox, QGridLayout, QFileDialog, QSplitter, QSizePolicy,
                             QAbstractItemView, QDoubleSpinBox, QMessageBox, QComboBox)
from .backend_api import BackendAPI, CARD_W_PX, CARD_H_PX
from .layout_editor import element_caption
from .records_table import format_printed_at

from .backend_api import TYPE_NAMES, SIDE_NAMES, field_desync, desync_text, FIELD_TYPES, FIELD_TYPE_NAMES, field_type, new_field_name, display_value
from .backend_api import _UPSERT_HAS_TYPE as BACKEND_HAS_TYPE
EMPTY_VALUE = "(пусто)"
from .ribbon import glyph


class PreviewPanel(QWidget):
    """Вкладка «База данных», справа: «Предпросмотр / Поля».
    Сверху вкладки Сторона 1 / Сторона 2 (рендер Backend), снизу — «Поле шаблона | Значение из БД»."""

    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api, self.person_id, self.side = api, None, "front"
        self.title = QLabel("Предпросмотр / Поля"); self.title.setStyleSheet("font-weight:600;")
        self.sides = QTabWidget(); self.images, self.pixmaps = {}, {}
        for side, name in (("front", "Сторона 1"), ("back", "Сторона 2")):
            lab = QLabel(); lab.setAlignment(Qt.AlignmentFlag.AlignCenter); lab.setMinimumSize(260, 165)
            lab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.images[side] = lab; self.sides.addTab(lab, name)
        self.sides.currentChanged.connect(lambda i: self._fit())
        self.caption = QLabel(); self.caption.setStyleSheet("color:#4A5568;")
        self.warning = QLabel(); self.warning.setWordWrap(True); self.warning.setStyleSheet("color:#9A3412; background:#FFF4E5; padding:3px;")
        self.warning.hide()
        self.fields = QTableWidget(0, 2); self.fields.setHorizontalHeaderLabels(["Поле шаблона", "Значение из БД"])
        self.fields.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.fields.verticalHeader().setVisible(False)
        self.fields.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fields.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.title); lay.addWidget(self.sides, 3); lay.addWidget(self.caption); lay.addWidget(self.warning); lay.addWidget(self.fields, 2)

    @property
    def pixmap(self):
        return self.pixmaps.get("front")

    def set_side(self, side):
        self.side = side; self.sides.setCurrentIndex(0 if side == "front" else 1)

    def set_person(self, pid):
        self.person_id = pid; self.refresh()

    def refresh(self):
        p = self.api.get_person(self.person_id) if self.person_id is not None else None
        if p is None: self.person_id = None
        for side in ("front", "back"):
            self.pixmaps[side] = QPixmap.fromImage(self.api.render_card(self.person_id, side))   # рендер Backend
        self._fit()
        self.caption.setText(f"Запись #{p['id']}" if p else "Пустой шаблон (запись не выбрана)")
        _fl = self.api.list_fields(); labels = {f["name"]: f["label"] or f["name"] for f in _fl}
        types = {f["name"]: field_type(f) for f in _fl}
        vals = (p or {}).get("fields") or {}
        rows = []
        for e in self.api.list_elements():
            if e["type"] == "photo":
                lab = labels.get(e.get("field_name"), TYPE_NAMES["photo"]) if e.get("field_name") else TYPE_NAMES["photo"]
                rows.append((f"{lab} · {TYPE_NAMES['photo']} · {SIDE_NAMES[e['side']].lower()}", self.api.photo_value(p, e) if p else "—"))
            elif e.get("field_name"):
                rows.append((f"{labels.get(e['field_name'], e['field_name'])} · {TYPE_NAMES.get(e['type'], e['type'])} · "
                             f"{SIDE_NAMES[e['side']].lower()}", display_value(types.get(e["field_name"]), vals.get(e["field_name"], ""))))
        self.fields.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.fields.setItem(r, 0, QTableWidgetItem(k))
            it = QTableWidgetItem(v if v not in ("", "—") else EMPTY_VALUE)
            if v in ("", "—") and p: it.setForeground(QColor("#9AA3AE")); it.setToolTip("В записи нет значения этого поля")
            self.fields.setItem(r, 1, it)
        self.desync = field_desync(self.api); t = desync_text(self.desync)
        self.warning.setText(t); self.warning.setVisible(bool(t))

    def db_rows(self):
        """[(поле, значение)]; пустое значение — "" (на экране — серым «(пусто)»)."""
        return [(self.fields.item(r, 0).text(), "" if self.fields.item(r, 1).text() == EMPTY_VALUE else self.fields.item(r, 1).text())
                for r in range(self.fields.rowCount())]

    def _fit(self):
        for side, lab in self.images.items():
            pm = self.pixmaps.get(side)
            if pm is None: continue
            w = max(200, lab.width() - 8); h = max(120, lab.height() - 8)
            lab.setPixmap(pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev); self._fit()


def _letter(ch):
    pm = QPixmap(18, 18); pm.fill(Qt.GlobalColor.transparent); p = QPainter(pm)
    p.setPen(QColor("#1F2937")); p.drawRect(1, 1, 15, 15)
    f = p.font(); f.setBold(True); f.setPixelSize(11); p.setFont(f)
    p.drawText(pm.rect().adjusted(0, 0, -1, -1), Qt.AlignmentFlag.AlignCenter, ch); p.end(); return pm


SIDE_LETTER = {"front": "F", "back": "B"}


def _side_type_icon(sides, kind):
    """[F][B] (стороны, где есть объект поля) + значок типа объекта; ширина постоянная — колонки ровные."""
    pm = QPixmap(66, 20); pm.fill(Qt.GlobalColor.transparent); p = QPainter(pm)
    for i, s_ in enumerate(("front", "back")):
        if s_ in sides: p.drawPixmap(i * 21, 1, _letter(SIDE_LETTER[s_]))
    p.drawPixmap(44, 0, glyph({"field": "text", "image": "photo"}.get(kind, kind)).pixmap(20, 20)); p.end(); return QIcon(pm)


def _two_icons(side, kind):
    pm = QPixmap(44, 22); pm.fill(Qt.GlobalColor.transparent); p = QPainter(pm)
    p.drawPixmap(0, 0, glyph(side).pixmap(22, 22))
    p.drawPixmap(22, 0, glyph({"field": "text"}.get(kind, kind)).pixmap(22, 22)); p.end(); return QIcon(pm)


field_manager_hook = None    # тесты: field_manager_hook(kind, dialog) -> значение вместо модального вопроса


class FieldEditDialog(QDialog):
    """Поле БД: имя (подпись), тип данных (D24), значение по умолчанию."""

    def __init__(self, parent=None, label="", data_type="text", default="", title="Поле БД", objects=None):
        super().__init__(parent); self.setWindowTitle(title)
        self.label = QLineEdit(label); self.type = QComboBox()
        for k, t in FIELD_TYPES: self.type.addItem(t, k)
        self.type.setCurrentIndex(max(0, self.type.findData(data_type)))
        if not BACKEND_HAS_TYPE: self.type.setToolTip("Backend пока не хранит data_type — сохраняется как «Строка»")
        self.default = QLineEdit(default or "")
        form = QFormLayout(); form.addRow("Имя поля:", self.label); form.addRow("Тип данных:", self.type); form.addRow("По умолчанию:", self.default)
        # этап 15 п.3 (макет): объект шаблона для поля; «создать при связывании» — если объекта нет
        self.obj = QComboBox(); self.obj.addItem("— нет: создать объект при связывании —", None)
        for e in objects or []: self.obj.addItem(e[1], e[0])
        self.obj.setToolTip("Если объекта нет — он будет создан при «Связать поле»")
        if objects is not None: form.addRow("Объект шаблона:", self.obj)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(lambda: self.accept() if self.label.text().strip() else None); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(bb)

    def values(self):
        return self.label.text().strip(), self.type.currentData(), self.default.text().strip() or None


class FieldManager(QDialog):
    """Менеджер полей (эталон reports/mockup/reference_field_manager.png): «Поле | Тип данных | Значение по умолчанию»;
    у поля — иконки стороны (F/B) и типа объекта; ниже «Описание» с легендой.
    Данные: list_fields / list_field_links; изменения — upsert_field, delete_field, set_field_default, link_field, unlink_field."""
    LINKABLE = ("field", "text", "barcode", "qr", "photo")   # Backend 91b0208: photo ↔ только поле типа image

    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent); self.api = api; self.setWindowTitle("Менеджер полей"); self.resize(720, 560)
        from PyQt6.QtWidgets import QTreeWidget, QGroupBox, QGridLayout
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Поле", "Тип данных", "Значение по умолчанию"]); self.tree.setIconSize(QSize(66, 20)); self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._edited); self.tree.currentItemChanged.connect(lambda *_: self._sel())
        desc = QGroupBox("Описание: объект, связанный с полем"); g = QGridLayout(desc)
        for i, (k, t) in enumerate((("F", "на лицевой стороне"), ("B", "на оборотной стороне"), ("text", "Текстовый объект"),
                                    ("barcode", "Штрихкод"), ("qr", "QR-код"), ("photo", "Изображение"))):
            ic = QLabel(); ic.setPixmap(_letter(k) if k in ("F", "B") else glyph(k).pixmap(18, 18)); cell = QHBoxLayout(); cell.addWidget(ic); cell.addWidget(QLabel(t)); cell.addStretch(1)
            g.addLayout(cell, i % 2, i // 2)
        self.b_add, self.b_rename, self.b_delete = QPushButton("Добавить поле"), QPushButton("Переименовать поле"), QPushButton("Удалить поле")
        self.b_print, self.b_link = QPushButton("Печать"), QPushButton("Связать поле")
        self.b_print.setToolTip("Печать списка полей")
        self.b_unlink, self.b_close = QPushButton("Отвязать поле"), QPushButton("Закрыть")
        self.b_add.clicked.connect(lambda: self.add_field()); self.b_rename.clicked.connect(lambda: self.rename_field())
        self.b_delete.clicked.connect(lambda: self.delete_field())
        self.b_print.clicked.connect(lambda: self.print_list()); self.b_link.clicked.connect(lambda: self.link())
        self.b_unlink.clicked.connect(lambda: self.unlink()); self.b_close.clicked.connect(self.accept)
        b1 = QHBoxLayout()
        for b in (self.b_add, self.b_rename, self.b_delete): b1.addWidget(b)
        b1.addStretch(1)
        bl = QHBoxLayout()
        for b in (self.b_print, self.b_link, self.b_unlink): bl.addWidget(b)
        bl.addStretch(1); bl.addWidget(self.b_close)
        for b in (self.b_add, self.b_rename, self.b_delete, self.b_print, self.b_link, self.b_unlink, self.b_close):
            b.setMinimumWidth(b.sizeHint().width())
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Выделите поле в списке и объект на макете → «Связать поле» / «Отвязать поле». Значение по умолчанию — двойной клик."))
        self.status = QLabel(); self.status.setWordWrap(True); self.status.setStyleSheet("color:#9A5B00;")
        lay.addWidget(self.tree, 1); lay.addLayout(b1); lay.addWidget(desc); lay.addWidget(self.status); lay.addLayout(bl)
        self.reload()

    def reload(self):
        """Плоский список: одна строка = одно поле. Значки: F/B (стороны, где поле есть на шаблоне) + тип объекта.
        Несвязанное поле — без значков. Фото — обычные поля data_type=image (Backend 91b0208), связь photo ↔ image через link_field."""
        from PyQt6.QtWidgets import QTreeWidgetItem
        self.tree.blockSignals(True); self.tree.clear()
        links = self.api.list_field_links(); els = self.api.list_elements()
        rows = [(f["label"] or f["name"], field_type(f), f.get("default_value"), ("field", f["name"]), links.get(f["name"], []))
                for f in self.api.list_fields()]
        for label, t, dv, key, ls in rows:
            it = QTreeWidgetItem(self.tree, [label, FIELD_TYPE_NAMES[t], display_value(t, dv)])
            it.setData(0, Qt.ItemDataRole.UserRole, key); it.setToolTip(0, key[1])
            if key[0] == "field": it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            if not ls:
                blank = QPixmap(66, 20); blank.fill(Qt.GlobalColor.transparent); it.setIcon(0, QIcon(blank))   # без значков, выравнивание
            else:
                sides = [s_ for s_ in ("front", "back") if any(e["side"] == s_ for e in ls)]
                it.setIcon(0, _side_type_icon(sides, ls[0]["type"]))
        self.tree.blockSignals(False); self._sel()

    # объект на макете: выделенный в редакторе главного окна (или заданный тестом через set_element)
    def set_element(self, eid):
        self._element = eid; self._sel(); return eid

    def selected_element(self):
        if getattr(self, "_element", None) is not None: return self._element
        le = getattr(self.parent(), "layout_editor", None)
        cur = getattr(le, "current", None) if le is not None else None
        return cur.el.get("id") if cur is not None else None

    def _element_info(self):
        eid = self.selected_element()
        return next((e for e in self.api.list_elements() if e["id"] == eid), None) if eid is not None else None

    def selected_field(self):
        it = self.tree.currentItem(); d = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        return d[1] if d and d[0] == "field" else None

    def _field(self, name):
        return next((f for f in self.api.list_fields() if f["name"] == name), None)

    def add_field(self, label=None, data_type="text", default=None):
        """Новое поле БД (upsert_field). Возвращает имя (ключ) или None."""
        chosen = None
        if label is None:
            objs = [(e["id"], f"{TYPE_NAMES.get(e['type'], e['type'])} #{e['id']} ({'лиц.' if e['side'] == 'front' else 'обор.'})")
                    for e in self.api.list_elements() if e["type"] in self.LINKABLE and not e.get("field_name")]
            d = FieldEditDialog(self, title="Добавить поле", objects=objs)
            if field_manager_hook is not None:
                v = field_manager_hook("add", d)
                if not v: return None
                label, data_type, default = v[0], v[1], v[2]
                chosen = v[3] if len(v) > 3 else d.obj.currentData()
            elif d.exec():
                label, data_type, default = d.values(); chosen = d.obj.currentData()
            else: return None
        fields = self.api.list_fields()
        name = new_field_name(label, {f["name"] for f in fields})
        self.api.upsert_field(name, label, max([f.get("sort_order") or 0 for f in fields] or [0]) + 1, data_type=data_type)
        if default: self.api.set_field_default(name, default)
        if chosen is not None:
            try: self.api.link_field(chosen, name)
            except ValueError as e:
                self.last_error = str(e)
                if field_manager_hook is not None: field_manager_hook("error", self.last_error)
                else: QMessageBox.warning(self, "Связать поле", self.last_error)
        self.reload(); self._select_field(name)
        if chosen is not None: self.status.setText("Объект привязан")
        return name

    def rename_field(self, label=None, data_type=None):
        name = self.selected_field()
        if name is None: return False
        f = self._field(name)
        if label is None:
            d = FieldEditDialog(self, f["label"] or name, field_type(f), f.get("default_value"), title="Переименовать поле")
            if field_manager_hook is not None:
                v = field_manager_hook("rename", d)
                if not v: return False
                label, data_type, _ = v
            elif d.exec(): label, data_type, _ = d.values()
            else: return False
        self.api.upsert_field(name, label, f.get("sort_order") or 0, data_type=data_type)
        self.reload(); self._select_field(name); return True

    def delete_field(self, confirm=None):
        name = self.selected_field()
        if name is None: return False
        n = len(self.api.list_field_links().get(name, []))
        q = f"Удалить поле «{(self._field(name) or {}).get('label') or name}»?" + (f" Связанные объекты ({n}) будут отвязаны." if n else "") \
            + " Данные записей не удаляются."
        if confirm is None:
            confirm = field_manager_hook("delete", q) if field_manager_hook is not None else \
                QMessageBox.question(self, "Удалить поле", q) == QMessageBox.StandardButton.Yes
        if not confirm: return False
        r = self.api.delete_field(name, unlink=True); self.reload(); return r

    def _select_field(self, name):
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole) == ("field", name): self.tree.setCurrentItem(it); return True
        return False

    def _sel(self):
        fld = self.selected_field() is not None; e = self._element_info()
        self.b_rename.setEnabled(fld); self.b_delete.setEnabled(fld)
        ok = fld and e is not None and e["type"] in self.LINKABLE
        if ok:   # подсказка UI; окончательное правило — link_field (ValueError показывается как есть)
            is_img = field_type(self._field(self.selected_field())) == "image"
            ok = (e["type"] == "photo") == is_img
        self.b_link.setEnabled(bool(ok) or (fld and e is None))   # этап 15 п.3: без объекта — объект создаётся при связывании
        self.b_unlink.setEnabled(e is not None and bool(e.get("field_name")))

    def _edited(self, item, col):
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if col == 2 and d and d[0] == "field":
            self.api.set_field_default(d[1], item.text(2).strip() or None)

    def set_default(self, name, value):
        self.api.set_field_default(name, value); self.reload()

    def link(self, field_name=None):
        """Выделенное поле списка ↔ выделенный объект на макете."""
        if self._locked("Связать поле"): return False
        eid = self.selected_element(); field_name = field_name or self.selected_field()
        le = getattr(self.parent(), "layout_editor", None)
        side = getattr(le, "side", "front") if le is not None else "front"
        if field_name is None: return False
        try:
            r = self.api.link_field(eid, field_name, side=side)
        except ValueError as e:
            self.last_error = str(e)                                   # текст Backend как есть
            if field_manager_hook is not None: field_manager_hook("error", self.last_error)
            else: QMessageBox.warning(self, "Связать поле", self.last_error)
            return False
        created = eid is None
        self.reload()
        if le is not None: le.reload()
        self.status.setText("Создан объект в шаблоне" if created else "Объект привязан")
        if created and isinstance(r, int): self.set_element(r)
        return r

    def _locked(self, title):
        """Этап 15: связывание/отвязка — только в «Режиме шаблона» (то же предупреждение, что и в редакторе)."""
        le = getattr(self.parent(), "layout_editor", None)
        return le is not None and le._locked(title)

    def unlink(self):
        if self._locked("Отвязать поле"): return False
        eid = self.selected_element()
        if eid is None: return False
        r = self.api.unlink_field(eid); self.reload()
        self.status.setText("Объект отвязан")     # этап 15 п.3
        le = getattr(self.parent(), "layout_editor", None)
        if le is not None: le.reload()
        return r

    def field_list_text(self):
        lines = ["Поля БД и связанные объекты шаблона", ""]
        links = self.api.list_field_links()
        for f in self.api.list_fields():
            dv = f.get("default_value")
            lines.append(f"{f['label'] or f['name']} ({f['name']})" + (f" — по умолчанию: {dv}" if dv else ""))
            for e in links.get(f["name"], []):
                lines.append(f"    {TYPE_NAMES.get(e['type'], e['type'])} · {SIDE_NAMES[e['side']]} · #{e['element_id']}")
        return "\n".join(lines)

    def print_list(self, printer=None):
        from PyQt6.QtGui import QTextDocument
        from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
        doc = QTextDocument(); doc.setPlainText(self.field_list_text())
        if printer is None:
            printer = QPrinter()
            if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted: return False
        doc.print(printer); return True


class PrintQueueDialog(QDialog):
    """Очередь печати: просмотр записей с print_mark=1 (действия — только в ленте)."""

    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent); self.setWindowTitle("Очередь печати"); self.resize(560, 380)
        self.api = api
        self.flds = [f for f in api.list_fields() if f["name"] != "logo"][:3]          # D19: из list_fields(), не хардкод
        self.table = QTableWidget(0, 2 + len(self.flds))
        self.table.setHorizontalHeaderLabels(["#", *[f["label"] or f["name"] for f in self.flds], "Напечатано"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().setVisible(False)
        self.info = QLabel()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addWidget(self.table); lay.addWidget(self.info); lay.addWidget(bb)
        self.reload()

    def reload(self):
        self.persons = self.api.list_persons(only_marked=True)
        self.table.setRowCount(len(self.persons))
        for r, p in enumerate(self.persons):
            f = p["fields"]
            vals = [str(p["id"]), *[str(f.get(x["name"]) or "") for x in self.flds], format_printed_at(p.get("printed_at"))]
            for c, v in enumerate(vals): self.table.setItem(r, c, QTableWidgetItem(v))
        self.info.setText(f"В очереди: {len(self.persons)}. Печать и снятие отметок — лента «База данных → Печать»."
                          if self.persons else "Очередь пуста — отметьте записи в колонке «Печать».")

    def ids(self):
        return [p["id"] for p in self.persons]


ALIGN = [("left", "По левому краю"), ("hcenter", "По центру (гориз.)"), ("right", "По правому краю"),
         ("top", "По верху"), ("vcenter", "По центру (верт.)"), ("bottom", "По низу")]


def aligned_geometry(el, how, margin=0):
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    bw, bh = abs(w), abs(h); ox, oy = min(0, w), min(0, h)          # линии: w/h могут быть < 0
    if how == "left": x = margin - ox
    elif how == "right": x = CARD_W_PX - margin - bw - ox
    elif how == "hcenter": x = (CARD_W_PX - bw) // 2 - ox
    elif how == "top": y = margin - oy
    elif how == "bottom": y = CARD_H_PX - margin - bh - oy
    elif how == "vcenter": y = (CARD_H_PX - bh) // 2 - oy
    return {"x": int(x), "y": int(y)}


class PositionDialog(QDialog):
    """Положение выбранного элемента: только численный ввод X/Y (выравнивание — «Выровнять ▾» в ленте)."""

    def __init__(self, el, parent=None):
        super().__init__(parent); self.setWindowTitle("Положение элемента"); self.el = dict(el)
        self.x = QSpinBox(); self.y = QSpinBox()
        for s_, v in ((self.x, el["x"]), (self.y, el["y"])): s_.setRange(-2000, 2000); s_.setValue(v)
        form = QFormLayout(); form.addRow("X, px:", self.x); form.addRow("Y, px:", self.y)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addWidget(QLabel(element_caption(el))); lay.addLayout(form); lay.addWidget(bb)

    def value(self):
        return {"x": self.x.value(), "y": self.y.value()}


class SettingsDialog(QDialog):
    """Настройка: каталог фото/изображений (база относительных путей) и масштаб предпросмотра."""

    def __init__(self, api: BackendAPI, settings, parent=None):
        super().__init__(parent); self.setWindowTitle("Настройка"); self.api, self.settings = api, settings
        self.base_dir = QLineEdit(str(api.base_dir or "")); pick = QPushButton("…")
        pick.clicked.connect(lambda: (lambda d: d and self.base_dir.setText(d))(QFileDialog.getExistingDirectory(self, "Каталог фото", self.base_dir.text())))
        row = QHBoxLayout(); row.addWidget(self.base_dir, 1); row.addWidget(pick)
        self.grid = QSpinBox(); self.grid.setRange(5, 200); self.grid.setValue(int(settings.value("editor/grid", 20)))
        form = QFormLayout(); form.addRow("Каталог фото и изображений:", row); form.addRow("Шаг сетки редактора, px:", self.grid)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(bb)

    def apply(self):
        if self.base_dir.text().strip(): self.api.base_dir = self.base_dir.text().strip()
        self.settings.setValue("editor/grid", self.grid.value())
        return {"base_dir": self.api.base_dir, "grid": self.grid.value()}
