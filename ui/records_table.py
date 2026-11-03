"""Таблица записей: колонки из person_fields + чекбокс «Печать» (print_mark)."""
import os
from datetime import datetime
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QComboBox,
                             QTableView, QAbstractItemView, QMessageBox, QHeaderView, QLabel)
from .backend_api import BackendAPI
from .record_form import RecordForm


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


FIO_PARTS = ("last_name", "first_name", "middle_name")
# Предпочтительный порядок колонок (только порядок; колонки появляются, лишь если такие поля есть в list_fields)
PREFERRED = ("position", "department", "employee_id", "barcode")
THUMB = 36


class PersonsModel(QAbstractTableModel):
    """Колонки: Печать | [Логотип] | [Фото] | [ФИО] | поля в предпочтительном порядке, затем прочие | Напечатано."""

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
        self.cols = self._build_cols()
        self.endResetModel()

    def _build_cols(self):
        names = [f["name"] for f in self.fields]; label = {f["name"]: f["label"] for f in self.fields}
        cols = [("mark", "Печать", None)]
        if self.template_logo or any(p["fields"].get("logo") for p in self.rows):
            cols.append(("logo", "Логотип", None))
        if any(p.get("photo_path") for p in self.rows):
            cols.append(("photo", "Фото", None))
        used = set()
        fio = [n for n in FIO_PARTS if n in names]
        if fio:
            cols.append(("fio", "ФИО", fio)); used.update(fio)
        for n in PREFERRED:
            if n in names: cols.append(("field", label[n], n)); used.add(n)
        for n in names:
            if n not in used and n != "logo": cols.append(("field", label[n], n))
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
        if kind == "fio": return " ".join(str(p["fields"].get(x, "") or "") for x in n).strip()
        if kind == "field": return str(p["fields"].get(n, "") or "")
        if kind == "printed": return format_printed_at(p.get("printed_at"))
        if kind == "photo": return os.path.basename(p.get("photo_path") or "")
        if kind == "logo": return os.path.basename(p["fields"].get("logo") or self.template_logo or "")
        return ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p, c = self.rows[index.row()], index.column(); kind = self.cols[c][0]
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
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole):
            return self.text(index.row(), c)
        return None

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            p = self.rows[index.row()]
            mark = Qt.CheckState(value) == Qt.CheckState.Checked
            self.api.set_print_mark([p["id"]], mark)
            p["print_mark"] = int(mark)
            self.dataChanged.emit(index, index)
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

    def set_search(self, t): self.search = (t or "").casefold(); self.invalidateFilter()
    def set_column_filter(self, col, t): self.col, self.col_text = col, (t or "").casefold(); self.invalidateFilter()
    def set_printed(self, v): self.printed = v; self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        m = self.sourceModel(); p = m.rows[row]
        if self.printed is not None and bool(p.get("printed_at")) != self.printed: return False
        if self.col_text and 0 <= self.col < m.columnCount() and self.col_text not in m.text(row, self.col).casefold():
            return False
        if self.search and not any(self.search in m.text(row, c).casefold() for c in range(m.columnCount())):
            return False
        return True


PRINTED_FILTERS = [(None, "Все записи"), (True, "Напечатано"), (False, "Не напечатано")]


class RecordsWidget(QWidget):
    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.model = PersonsModel(api, self)
        self.proxy = RecordsFilter(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)

        # строка фильтров: поиск + фильтр по колонке + напечатано/не напечатано
        self.search = QLineEdit(placeholderText="Поиск по всем полям…")
        self.search.textChanged.connect(self.proxy.set_search)
        self.col_box = QComboBox(); self.col_value = QLineEdit(placeholderText="Значение в колонке…")
        self.col_box.currentIndexChanged.connect(self._apply_col_filter); self.col_value.textChanged.connect(self._apply_col_filter)
        self.printed_box = QComboBox()
        for v, t in PRINTED_FILTERS: self.printed_box.addItem(t, v)
        self.printed_box.currentIndexChanged.connect(lambda _: self.proxy.set_printed(self.printed_box.currentData()))
        flt = QHBoxLayout(); flt.addWidget(self.search, 2); flt.addWidget(QLabel("Колонка:")); flt.addWidget(self.col_box)
        flt.addWidget(self.col_value, 1); flt.addWidget(self.printed_box)
        top = QHBoxLayout()
        for text, slot in (("Добавить", self.add), ("Изменить", self.edit), ("Удалить", self.delete),
                           ("Отметить все", lambda: self._mark_all(True)), ("Снять отметки", lambda: self._mark_all(False))):
            b = QPushButton(text); b.clicked.connect(slot); top.addWidget(b)
        self.view = QTableView(); self.view.setModel(self.proxy); self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.model.modelReset.connect(lambda: self.view.resizeColumnsToContents())
        self.view.doubleClicked.connect(lambda _: self.edit())
        self.counter = QLabel()
        self.model.modelReset.connect(self._count); self.model.dataChanged.connect(self._count)
        self.view.verticalHeader().setDefaultSectionSize(THUMB + 6)
        self.model.modelReset.connect(self._fill_col_box)
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(flt); lay.addWidget(self.view); lay.addLayout(top); lay.addWidget(self.counter)
        self._fill_col_box(); self._count()

    def _fill_col_box(self):
        cur = self.col_box.currentText()
        self.col_box.blockSignals(True); self.col_box.clear()
        for c in range(1, self.model.columnCount()):
            if self.model.col_kind(c) not in ("photo", "logo"):
                self.col_box.addItem(self.model.headerData(c, Qt.Orientation.Horizontal), c)
        i = self.col_box.findText(cur); self.col_box.setCurrentIndex(max(i, 0)); self.col_box.blockSignals(False)
        self._apply_col_filter()

    def _apply_col_filter(self, *_):
        self.proxy.set_column_filter(self.col_box.currentData() if self.col_box.count() else -1, self.col_value.text())

    def set_printed_filter(self, value):
        self.printed_box.setCurrentIndex(self.printed_box.findData(value) if value is not None else 0)

    def cycle_printed_filter(self):
        self.printed_box.setCurrentIndex((self.printed_box.currentIndex() + 1) % self.printed_box.count())
        return self.printed_box.currentText()

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
        if RecordForm(self.api, pid, self).exec():
            self.model.reload()

    def delete(self):
        ids = self.selected_ids()
        if ids and QMessageBox.question(self, "Удаление", f"Удалить записей: {len(ids)}?") \
                == QMessageBox.StandardButton.Yes:
            for pid in ids:
                self.api.delete_person(pid)
            self.model.reload()

    def _mark_all(self, value):
        ids = self.selected_ids() or [p["id"] for p in self.model.rows]
        self.api.set_print_mark(ids, value); self.model.reload()
