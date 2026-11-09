"""Таблица записей: колонки из person_fields + чекбокс «Печать» (print_mark)."""
import os
from datetime import datetime
from PyQt6.QtCore import pyqtSignal, Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QSize
from PyQt6.QtGui import QPixmap, QBrush, QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QComboBox,
                             QTableView, QAbstractItemView, QMessageBox, QHeaderView, QLabel, QCompleter)
from .backend_api import BackendAPI, display_value, field_type
from .record_form import RecordForm
from .stage15 import PRINTED_ROW_COLOR


PRINTED_LABEL = "Напечатано"


def parse_printed_at(value):
    """ISO 8601 со смещением (printed_at) → aware datetime или None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def format_printed_at(value) -> str:
    """'2026-11-03T16:40:12+03:00' → 'dd.MM.yyyy HH:mm' в локальном часовом поясе; None → ''."""
    dt = parse_printed_at(value)
    if dt is None:
        return "" if not value else str(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone()          # в локальный пояс системы
    return dt.strftime("%d.%m.%Y %H:%M")


form_hook = None   # тесты: form_hook(RecordForm) -> bool вместо exec()
THUMB = 36


class PersonsModel(QAbstractTableModel):
    queue_toggle_requested = pyqtSignal(int)
    """Колонки: Печать | [Логотип] | [Фото] | поля list_fields() в его порядке | Напечатано."""

    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api, self.fields, self.rows, self.cols = api, [], [], []
        self._thumbs = {}
        self.reload()

    def reload(self):
        self.beginResetModel()
        self.fields = self.api.list_fields()
        self.rows = self.api.list_persons()
        self._thumbs.clear()
        self.template_logo = next((e.get("static_value") for e in sorted(self.api.list_elements(), key=lambda e: e["side"] != "front")
                                   if e["type"] == "image" and e.get("static_value")), None)
        self.types = {f["name"]: field_type(f) for f in self.api.list_fields()}
        self.cols = self._build_cols()
        self.endResetModel()

    def _build_cols(self):
        names = [f["name"] for f in self.fields]; label = {f["name"]: f["label"] for f in self.fields}
        cols = [("mark", "Печать", None)]
        if self.template_logo or any(p["fields"].get("logo") for p in self.rows):
            cols.append(("logo", "Логотип", None))
        img_names = [n for n, typ in self.types.items() if typ == "image" and n != "logo"]
        if any(p.get("photo_path") for p in self.rows) or any(
            (p.get("fields") or {}).get(n) for p in self.rows for n in img_names
        ):
            cols.append(("photo", "Фото", None))
        for n in names:                                   # D19: ровно list_fields(), в его порядке
            if n != "logo": cols.append(("field", label[n] or n, n))
        cols.append(("printed", PRINTED_LABEL, None))
        return cols

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cols)

    def printed_col(self):
        return len(self.cols) - 1

    def col_kind(self, c):
        return self.cols[c][0]

    def column_of(self, kind, name=None):
        return next((i for i, (k, _l, n) in enumerate(self.cols) if k == kind and (name is None or n == name)), -1)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.cols[section][1]
        return super().headerData(section, orientation, role)

    def _thumb(self, path):
        if not path: return None
        if path not in self._thumbs:
            full = path if os.path.isabs(path) else os.path.join(self.api.base_dir or "", path)
            pm = QPixmap(full)
            self._thumbs[path] = None if pm.isNull() else pm.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                                                                    Qt.TransformationMode.SmoothTransformation)
        return self._thumbs[path]

    def text(self, row, c):
        p = self.rows[row]; kind, _l, n = self.cols[c]
        if kind == "field": return display_value(self.types.get(n), p["fields"].get(n, ""))
        if kind == "printed": return format_printed_at(p.get("printed_at"))
        if kind == "photo": return os.path.basename(p.get("photo_path") or "")
        if kind == "logo": return os.path.basename(p["fields"].get("logo") or self.template_logo or "")
        return ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p, c = self.rows[index.row()], index.column(); kind = self.cols[c][0]
        if role == Qt.ItemDataRole.BackgroundRole:   # этап 15 п.4: «Напечатано» — строка цветом; «Не напечатано» — обычный
            return QBrush(QColor(PRINTED_ROW_COLOR)) if p.get("printed_at") else None
        if kind == "mark":
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if p["print_mark"] else Qt.CheckState.Unchecked
            return p["print_mark"] if role == Qt.ItemDataRole.UserRole else None
        if kind == "printed":
            raw = p.get("printed_at")
            if role == Qt.ItemDataRole.DisplayRole: return format_printed_at(raw)
            if role == Qt.ItemDataRole.UserRole:   # сортировка по реальному времени; пустые — в начале
                dt = parse_printed_at(raw); return dt.timestamp() if dt else float("-inf")
            if role == Qt.ItemDataRole.ToolTipRole: return raw or "не печаталось"
            return None
        if kind in ("photo", "logo"):
            path = p.get("photo_path") if kind == "photo" else (p["fields"].get("logo") or self.template_logo)
            if role == Qt.ItemDataRole.DecorationRole: return self._thumb(path)
            if role == Qt.ItemDataRole.ToolTipRole: return path or ""
            if role == Qt.ItemDataRole.UserRole: return path or ""
            if role == Qt.ItemDataRole.SizeHintRole: return QSize(THUMB + 8, THUMB + 4)
            return None
        if kind == "field" and self.types.get(self.cols[c][2]) == "image" and role == Qt.ItemDataRole.DecorationRole:
            rp = self.api.resolve_photo_path(p, self.cols[c][2])      # Backend 91b0208: значение image-поля
            return self._thumb(str(rp)) if rp else None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole):
            return self.text(index.row(), c)
        return None

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            # D13: своего пути нет — запрос уходит в act_queue_toggle (главное окно)
            self.queue_toggle_requested.emit(self.rows[index.row()]["id"])
            return True
        return False

    def person_id(self, row):
        return self.rows[row]["id"]

    def row_of(self, pid):
        return next((r for r, p in enumerate(self.rows) if p["id"] == pid), -1)


class RecordsFilter(QSortFilterProxyModel):
    """Поиск по всем колонкам + фильтр по колонке + фильтр «Напечатано / Не напечатано» (printed_at)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.search, self.col, self.col_text, self.printed = "", -1, "", None   # printed: None | True | False
        self.ids = None        # результат query_persons (Backend) или None — без отбора

    def set_ids(self, ids): self.ids = None if ids is None else set(ids); self.invalidateFilter()

    def set_search(self, t): self.search = (t or "").casefold(); self.invalidateFilter()
    def set_column_filter(self, col, t): self.col, self.col_text = col, (t or "").casefold(); self.invalidateFilter()
    def set_printed(self, v): self.printed = v; self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        m = self.sourceModel(); p = m.rows[row]
        if self.printed is not None and bool(p.get("printed_at")) != self.printed: return False
        if self.ids is not None and p["id"] not in self.ids: return False
        if self.col_text and 0 <= self.col < m.columnCount() and self.col_text not in m.text(row, self.col).casefold():
            return False
        if self.search and not any(self.search in m.text(row, c).casefold() for c in range(m.columnCount())):
            return False
        return True


PRINTED_FILTERS = [(None, "Все карты"), (True, "Напечатанные"), (False, "Ненапечатанные")]
CONDITIONS = [("eq", "равно"), ("ne", "не равно"), ("contains", "содержит"), ("startswith", "начинается с"),
              ("empty", "пусто"), ("not_empty", "не пусто")]
NO_VALUE = ("empty", "not_empty")


def term_text(label, op_text, value):
    """Этап 15 п.5: «<название поля> оператор [значение]» (без значения для «пусто»/«не пусто»)."""
    return f"<{label}> {op_text}" + (f" [{value}]" if value is not None else "")


def parse_expr(txt, fields):
    """Обратный разбор term_text через И/ИЛИ (один вид связки). fields: подпись → имя поля."""
    import re
    if not txt: return [], "and"
    join = "or" if " ИЛИ " in txt else "and"
    if " ИЛИ " in txt and " И " in txt: raise ValueError("Смешивать И и ИЛИ нельзя")
    ops = sorted(CONDITIONS, key=lambda c: -len(c[1])); terms = []
    for part in txt.split(" ИЛИ " if join == "or" else " И "):
        m = re.fullmatch(r"\s*<([^>]+)>\s+(.+?)\s*(?:\[(.*)\])?\s*", part)
        if not m: raise ValueError(f"Ожидается <название поля> оператор [значение]: «{part.strip()}»")
        label, op_t, val = m.group(1).strip(), m.group(2).strip(), m.group(3)
        if label not in fields and label not in fields.values(): raise ValueError(f"Нет поля «{label}»")
        op = next((k for k, t in ops if t == op_t), None)
        if op is None: raise ValueError(f"Неизвестный оператор «{op_t}»")
        t = {"field": fields.get(label, label), "op": op}
        if op not in NO_VALUE: t["value"] = val or ""
        terms.append(t)
    return terms, join


confirm_delete_hook = None    # тесты: confirm_delete_hook(parent, n) -> bool


class FilterBlock(QWidget):
    """Блок фильтра под лентой: поле / условие / И-ИЛИ / значение / «Добавить»; выражение / «Применить».
    Выражение — данные {"join", "terms"} для Backend query_persons; SQL в UI нет."""

    def __init__(self, records, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QGridLayout
        self.records, self.terms, self.join_value = records, [], "and"
        self.field, self.cond, self.join = QComboBox(), QComboBox(), QComboBox()
        for c in (self.field, self.cond, self.join):
            c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); c.setMinimumContentsLength(6)
        for k, t in CONDITIONS: self.cond.addItem(t, k)
        self.join.addItem("И", "and"); self.join.addItem("ИЛИ", "or")
        self.value = QLineEdit(placeholderText="Значение"); self.value.returnPressed.connect(lambda: self.records.apply_filter())
        self.add_btn = QPushButton("Добавить"); self.add_btn.clicked.connect(self.add_term)
        # этап 15 п.5: выражение редактируемое, формат «<название поля> оператор [значение]»
        self.expr = QLineEdit(); self.expr.setPlaceholderText("<название поля> оператор [значение]   — пусто: показаны все записи")
        self.expr.editingFinished.connect(self._parse_expr)
        self.completer = QCompleter([], self); self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains); self.expr.setCompleter(self.completer)
        self.parse_error = None
        self.clear_btn = QPushButton("Сбросить"); self.clear_btn.clicked.connect(self.clear)
        g = QGridLayout(self); g.setContentsMargins(0, 0, 0, 0); g.setHorizontalSpacing(4); g.setVerticalSpacing(2)
        g.addWidget(QLabel("Поле"), 0, 0); g.addWidget(self.field, 0, 1); g.addWidget(QLabel("Условие"), 0, 2)
        g.addWidget(self.cond, 0, 3); g.addWidget(self.join, 0, 4); g.addWidget(self.value, 0, 5); g.addWidget(self.add_btn, 0, 6)
        g.addWidget(QLabel("Выражение"), 1, 0); g.addWidget(self.expr, 1, 1, 1, 5); g.addWidget(self.clear_btn, 1, 6)
        g.setColumnStretch(5, 1)
        self.grid = g
        self.apply_button = None  # кнопка «Применить» — QAction act_filter_apply, ставится главным окном

    def set_apply_action(self, act):
        from PyQt6.QtWidgets import QToolButton
        b = QToolButton(); b.setDefaultAction(act); b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        b.setAutoRaise(False); b.setMinimumWidth(96)
        b.setStyleSheet("QToolButton{border:1px solid #2E7D6B; border-radius:4px; background:#2E7D6B; color:white;"
                        " padding:4px 12px; font-weight:600;} QToolButton:hover{background:#3A9480;}")
        self.grid.addWidget(b, 0, 7, 2, 1); self.apply_button = b
        self.value.returnPressed.disconnect(); self.value.returnPressed.connect(act.trigger)

    def set_fields(self, fields):
        cur = self.field.currentData(); self.field.clear()
        for f in fields: self.field.addItem(f.get("label") or f["name"], f["name"])
        i = self.field.findData(cur); self.field.setCurrentIndex(max(i, 0))
        self.completer.model().setStringList(self.suggestions())   # автоподстановка в том же формате

    def suggestions(self):
        out = []
        for i in range(self.field.count()):
            for k, t in CONDITIONS: out.append(term_text(self.field.itemText(i), t, None if k in NO_VALUE else ""))
        return out

    def add_term(self, field=None, op=None, value=None, join=None):
        field = field or self.field.currentData(); op = op or self.cond.currentData()
        if not field: return None
        value = self.value.text() if value is None else value
        t = {"field": field, "op": op}
        if op not in ("empty", "not_empty"): t["value"] = value
        if self.terms: self.join_value = join or self.join.currentData()
        self.terms.append(t); self.value.clear(); self._show(); return self.where()

    def where(self):
        return {"join": self.join_value, "terms": list(self.terms)} if self.terms else None

    def _show(self):
        names = {self.field.itemData(i): self.field.itemText(i) for i in range(self.field.count())}
        ops = dict(CONDITIONS); j = " И " if self.join_value == "and" else " ИЛИ "
        self.expr.setText(j.join(term_text(names.get(t["field"], t["field"]), ops[t["op"]], t.get("value")) for t in self.terms))

    SEARCH_OPS = {"eq": "=", "ne": "!=", "contains": "~", "startswith": "^", "empty": "пусто", "not_empty": "непусто"}

    def search_text(self):
        """terms → строка для Backend parse_search/search_persons (автоподстановка остаётся в формате «<поле> оператор [значение]»)."""
        if not self.terms: return self.expr.text().strip()
        names = {self.field.itemData(i): self.field.itemText(i) for i in range(self.field.count())}
        parts = []
        for t in self.terms:
            lab = names.get(t["field"], t["field"])
            field = f'"{lab}"' if any(c.isspace() for c in lab) else lab
            op = self.SEARCH_OPS[t["op"]]
            if t["op"] in NO_VALUE: parts.append(f"{field} {op}"); continue
            val = str(t.get("value") or "")
            if any(c in val for c in ' ()="'): val = '"' + val.replace('"', r'"') + '"'
            parts.append(f"{field} {op} {val}")
        return (" и " if self.join_value == "and" else " или ").join(parts)

    def _parse_expr(self):
        """Разбор выражения: сначала формат «<поле> оператор [значение]», иначе Backend parse_search."""
        txt = self.expr.text().strip()
        fields = {self.field.itemText(i): self.field.itemData(i) for i in range(self.field.count())}
        try:
            terms, join = parse_expr(txt, fields)
        except ValueError as e_ui:
            api = getattr(self.records, "api", None)
            if api is not None and hasattr(api, "parse_search"):
                try:
                    w = api.parse_search(txt) if txt else None
                except ValueError as e:
                    self.parse_error = str(e); self.expr.setStyleSheet("border:1px solid #B23A3A;"); self.expr.setToolTip(str(e)); return None
                self.parse_error = None; self.expr.setStyleSheet(""); self.expr.setToolTip("")
                return w
            self.parse_error = str(e_ui); self.expr.setStyleSheet("border:1px solid #B23A3A;"); self.expr.setToolTip(str(e_ui)); return None
        self.parse_error = None; self.expr.setStyleSheet(""); self.expr.setToolTip("")
        self.terms, self.join_value = terms, join; return self.where()

    def clear(self):
        self.terms = []; self.join_value = "and"; self._show(); self.records.apply_filter()


class RecordsWidget(QWidget):
    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.model = PersonsModel(api, self)
        self.proxy = RecordsFilter(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)

        # блок фильтра (выражение → Backend query_persons); «Дисплей» — set_printed_filter (лента)
        self.filter = FilterBlock(self)
        self.printed_filter = None
        self.view = QTableView(); self.view.setModel(self.proxy); self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.model.modelReset.connect(lambda: self.view.resizeColumnsToContents())
        self.view.doubleClicked.connect(lambda _: self.edit())
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.counter = QLabel()
        self.model.modelReset.connect(self._count); self.model.dataChanged.connect(self._count)
        self.view.verticalHeader().setDefaultSectionSize(THUMB + 6)
        self.model.modelReset.connect(lambda: self.filter.set_fields(self.api.list_fields()))
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.view); lay.addWidget(self.counter)
        self.filter.set_fields(self.api.list_fields()); self._count()

    def set_printed_filter(self, value):
        """«Дисплей»: None — все карты, True — напечатанные, False — ненапечатанные (только отображение)."""
        self.printed_filter = value; self.proxy.set_printed(value)
        return dict(PRINTED_FILTERS)[value]

    def apply_filter(self):
        """Применить выражение через Backend parse_search / search_persons (без SQL в UI)."""
        parsed = self.filter._parse_expr()
        txt = self.filter.search_text() if self.filter.terms else self.filter.expr.text().strip()
        if self.filter.parse_error:
            QMessageBox.warning(self, "Поиск", self.filter.parse_error); return None
        if not txt:
            self.proxy.set_ids(None); return None
        try:
            ids = [p["id"] for p in self.api.search_persons(txt)]
        except ValueError as e:
            QMessageBox.warning(self, "Поиск", f"Некорректный поиск: {e}"); return None
        self.proxy.set_ids(ids); return ids

    def visible_ids(self):
        return [self.model.person_id(self.proxy.mapToSource(self.proxy.index(r, 0)).row()) for r in range(self.proxy.rowCount())]

    def _count(self, *a):
        n = len(self.model.rows); m = sum(p["print_mark"] for p in self.model.rows)
        self.counter.setText(f"Записей: {n}; отмечено для печати: {m}")

    def reload(self):
        self.model.reload()

    def selected_ids(self):
        rows = {self.proxy.mapToSource(i).row() for i in self.view.selectionModel().selectedRows()}
        return [self.model.person_id(r) for r in sorted(rows)]

    def add(self):
        self._open_form(None)

    def edit(self):
        ids = self.selected_ids()
        if ids:
            self._open_form(ids[0])

    def _open_form(self, pid):
        """После сохранения: перечитать модель, выделить новую/изменённую строку (→ превью и таблица значений)."""
        f = RecordForm(self.api, pid, self)
        ok = form_hook(f) if form_hook is not None else f.exec()
        if ok:
            self.model.reload(); self.select_id(f.person_id)
            return f.person_id
        return None

    def select_id(self, pid):
        r = self.model.row_of(pid)
        if r < 0: return False
        pr = self.proxy.mapFromSource(self.model.index(r, 0)).row()
        if pr < 0:                                         # скрыта фильтром — показать все
            self.proxy.set_ids(None); pr = self.proxy.mapFromSource(self.model.index(r, 0)).row()
        self.view.clearSelection(); self.view.selectRow(pr); self.view.scrollTo(self.proxy.index(pr, 0))
        return True

    def delete(self):
        """Удаление карт — только после подтверждения. Возвращает число удалённых."""
        ids = self.selected_ids()
        if not ids: return 0
        q = f"Удалить карт: {len(ids)}? Действие нельзя отменить."
        if confirm_delete_hook is not None: yes = bool(confirm_delete_hook(self, len(ids)))
        else:
            yes = QMessageBox.question(self, "Удаление карт", q, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        if not yes: return 0
        n = self.api.delete_persons(ids)
        self.model.reload(); return n
