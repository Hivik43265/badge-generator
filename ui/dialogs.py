"""Диалоги импорта, экспорта и печати.

Импорт выполняется в GUI-потоке (соединение sqlite привязано к нему) с QProgressDialog и отменой.
Экспорт: missing_photos() + snapshot() в GUI-потоке → рабочий QThread вызывает
*_from_snapshot без соединения (работает и с :memory:).
Печать: snapshot в GUI-потоке, print_snapshot тоже в GUI-потоке (QPrinter/QPainter
нельзя уводить в QThread); прогресс — через processEvents.
"""
import threading
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QEventLoop
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton,
                             QFileDialog, QTableWidget, QTableWidgetItem, QComboBox, QPlainTextEdit,
                             QDialogButtonBox, QRadioButton, QCheckBox, QLabel, QHeaderView,
                             QButtonGroup, QMessageBox, QProgressDialog, QApplication, QProgressBar, QToolButton)
from PyQt6.QtGui import QColor, QPixmap
from .backend_api import (SERVICE_COLUMNS, person_caption, BackendAPI, MissingPhotosError,
                          export_png_from_snapshot, export_pdf_from_snapshot, print_snapshot,
                          IMPORT_FORMATS, DATA_FORMATS, SHEET_KINDS, XLS_MAX_ROWS, FIELD_TYPE_NAMES, field_type,
                          open_source, read_rows, save_mapping, load_mapping)

AUTO, SKIP = "__auto__", "__skip__"
# Хуки для тестов: confirm_hook(parent, ids, names) -> bool; progress_hook(QProgressDialog)
confirm_hook = None
progress_hook = None
warning_hook = None   # тесты: warning_hook(title, text) вместо модального окна предупреждений результата


def make_progress(parent, title, text):
    pd = QProgressDialog(text, "Отмена", 0, 0, parent)
    pd.setWindowTitle(title); pd.setWindowModality(Qt.WindowModality.WindowModal); pd.setMinimumDuration(300)
    pd.setAutoClose(False); pd.setAutoReset(False)
    if progress_hook: progress_hook(pd)
    return pd


def confirm_missing_photos(parent, api: BackendAPI, ids):
    """Предпроверка фото. Возвращает (продолжать?, allow_missing_photo)."""
    miss = api.missing_photos(ids)
    if not miss:
        return True, False
    names = []
    for pid in miss:
        p = api.get_person(pid) or {"fields": {}}
        names.append(person_caption(api, p).strip())
    if confirm_hook is not None:
        return bool(confirm_hook(parent, miss, names)), True
    text = ("У следующих записей нет фото или файл недоступен — на карточке будет плейсхолдер «нет фото»:\n\n"
            + "\n".join(names[:30]) + (f"\n… и ещё {len(names) - 30}" if len(names) > 30 else "")
            + "\n\nПродолжить?")
    r = QMessageBox.warning(parent, "Нет фото", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No)
    return r == QMessageBox.StandardButton.Yes, True


# ---------------- импорт ----------------
NONE_COL = "—"
PREVIEW_LIMIT = 200
# Служебные цели сопоставления (колонки Backend D28 / фото); подписи — для таблицы «Поле БД»
SERVICE_TARGETS = [("photo_config", "Настройки фото", "Строка"),
                   ("print_mark", "Отметка печати", "Да/Нет"), ("printed", "Напечатано", "Да/Нет"),
                   ("printed_at", "Дата печати", "Дата"), ("__fio__", "ФИО (разбить на поля БД)", "Строка")]
confirm_fields_hook = None   # тесты: confirm_fields_hook(new_fields) -> True (создать) | False (только существующие) | None (отмена)


class ImportDialog(QDialog):
    """Импорт: источник (.xlsx/.xls/.csv/.db) → лист → «Поле БД | Тип | Сопоставлено | Колонка файла ▾» → import_rows."""

    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api, self.report = api, None
        self.sheets, self.headers, self.rows, self.fields, self.auto = [], [], [], [], {}
        self.setWindowTitle("Импорт записей"); self.resize(1000, 680)
        self.file = QLineEdit(); self.file.setReadOnly(True); self.file.setPlaceholderText("Файл .xlsx / .xls / .csv / .db")
        self.photo_dir = QLineEdit(); self.photo_dir.setPlaceholderText("Папка с фото (необязательно)")
        bf = QPushButton("Обзор…"); bf.clicked.connect(self._pick_file)
        bd = QPushButton("Обзор…"); bd.clicked.connect(self._pick_dir)
        self.sheet = QComboBox(); self.sheet.setMinimumWidth(200); self.sheet.currentIndexChanged.connect(lambda *_: self._load())
        self.sheet_kind = QLabel()
        self.use_header = QCheckBox("Временно использовать заголовок"); self.use_header.setChecked(True)
        self.use_header.setToolTip("Первая строка листа — имена колонок. Снимите, если заголовка нет: колонки станут «Колонка 1…N»")
        self.use_header.toggled.connect(lambda *_: self._load())
        self.require_photo = QCheckBox("Требовать фото"); self.require_photo.setToolTip("Строки без фото не импортировать")
        top = QHBoxLayout(); top.addWidget(QLabel("Источник:")); top.addWidget(self.file, 3); top.addWidget(bf)
        top.addSpacing(10); top.addWidget(QLabel("Фото:")); top.addWidget(self.photo_dir, 2); top.addWidget(bd)
        act = getattr(parent, "act_field_manager", None)   # тот же QAction ленты, нового действия нет
        if act is not None:
            self.b_fields = QToolButton(); self.b_fields.setDefaultAction(act)
            self.b_fields.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly); self.b_fields.setText("Менеджер полей…")
            act.triggered.connect(self._fields_changed)
        else:
            self.b_fields = QPushButton("Менеджер полей…"); self.b_fields.clicked.connect(lambda: self.open_fields())
        top2 = QHBoxLayout(); top2.addWidget(QLabel("Лист:")); top2.addWidget(self.sheet); top2.addWidget(self.sheet_kind)
        top2.addSpacing(10); top2.addWidget(self.use_header); top2.addWidget(self.require_photo); top2.addStretch(1)
        top2.addWidget(self.b_fields)
        # сопоставление
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Поле БД", "Тип", "Сопоставлено", "Колонка файла ▾"])
        hh = self.table.horizontalHeader(); hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # справа: значения выбранной строки + фото
        self.values = QTableWidget(0, 2); self.values.setHorizontalHeaderLabels(["Колонка", "Значение"])
        self.values.verticalHeader().setVisible(False); self.values.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.values.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.photo = QLabel("нет фото"); self.photo.setAlignment(Qt.AlignmentFlag.AlignCenter); self.photo.setFixedHeight(150)
        self.photo.setStyleSheet("background:#F4F7F7; border:1px solid #D5DCDA; color:#7A8A8A;")
        right = QVBoxLayout(); cap = QLabel("Выбранная строка файла"); cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(cap); right.addWidget(self.photo); right.addWidget(self.values, 1)
        mid = QHBoxLayout(); mid.addWidget(self.table, 3); mid.addLayout(right, 1)
        # превью строк
        self.preview = QTableWidget(0, 0); self.preview.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.currentCellChanged.connect(lambda r, *_: self._show_row(r))
        self.log = QPlainTextEdit(readOnly=True); self.log.setPlaceholderText("Здесь будет отчёт об импорте"); self.log.setMaximumHeight(90)
        # низ
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0); self.progress.setFormat("%p%")
        self.b_save = QPushButton("Сохранить привязку"); self.b_save.clicked.connect(self._save_binding)
        self.b_load = QPushButton("Загрузить привязку"); self.b_load.clicked.connect(self._load_binding)
        self.btn = QPushButton("Импорт"); self.btn.clicked.connect(self.run); self.btn.setEnabled(False); self.btn.setDefault(True)
        self.b_close = QPushButton("Отмена"); self.b_close.clicked.connect(self.reject)
        bottom = QHBoxLayout(); bottom.addWidget(QLabel("Ход импорта:")); bottom.addWidget(self.progress, 1)
        for b in (self.b_save, self.b_load, self.btn, self.b_close): bottom.addWidget(b)
        lay = QVBoxLayout(self); lay.addLayout(top); lay.addLayout(top2); lay.addLayout(mid, 3)
        self.no_image_hint = QLabel("Добавьте поле типа Изображение в Менеджере полей")
        self.no_image_hint.setStyleSheet("color:#a05a00;"); lay.addWidget(self.no_image_hint); self.update_image_hint()
        lay.addWidget(QLabel("Превью строк:")); lay.addWidget(self.preview, 2); lay.addWidget(self.log); lay.addLayout(bottom)

    # ---- жизненный цикл: временные копии .db удаляет Sheet.close() ----
    # D48: Sheet.close() → OSError (временная копия .db занята; своего класса исключений у Backend нет) пишется
    # в журнал диалога по-русски с именем файла, остальные листы закрываются; при закрытии диалога неудачные листы
    # пробуются ещё раз (один раз). Прочие исключения не глотаются (пробрасываются после закрытия остальных листов).
    def _close_list(self, sheets, retry=False):
        failed, unexpected = [], None
        for sh in sheets:
            fn = getattr(sh, "_bg_close_name", None) or getattr(getattr(sh, "work_path", None) or getattr(sh, "path", None), "name", None) \
                or getattr(sh, "name", "?")
            try: sh.close()
            except OSError as e:
                if retry: self.log.appendPlainText(f"Повторная попытка закрыть {fn} не удалась")      # кратко, без текста ошибки
                else:
                    self.log.appendPlainText(f"Не удалось закрыть источник «{fn}» (временная копия не удалена): {e}")
                    try: sh._bg_close_name = fn          # то же имя в строке повтора
                    except AttributeError: pass
                failed.append(sh)
            except BaseException as e:  # noqa: BLE001 — не глотается: закрыть остальные и пробросить первое
                unexpected = unexpected or e
        return failed, unexpected

    def close_sheets(self, final=False):
        sheets, self.sheets = list(self.sheets), []
        failed, unexpected = self._close_list(sheets)
        self._close_failed = getattr(self, "_close_failed", []) + failed
        if final and self._close_failed:            # закрытие диалога: одна повторная попытка для неудачных
            retry, self._close_failed = self._close_failed, []
            _left, unexpected2 = self._close_list(retry, retry=True); unexpected = unexpected or unexpected2
        if unexpected is not None: raise unexpected

    def done(self, r):
        try: self.close_sheets(final=True)
        finally: super().done(r)

    def closeEvent(self, e):
        try: self.close_sheets(final=True)
        finally: super().closeEvent(e)

    def _fields_changed(self, *_):
        try:
            if self.isVisible() and self.sheets: self._load()
        except RuntimeError:
            pass

    def open_fields(self):
        from .main_view import FieldManager, field_manager_hook
        fm = FieldManager(self.api, self)
        if field_manager_hook is None: fm.exec()
        if self.sheets: self._load()
        return fm

    # ---- источник ----
    def _pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Источник импорта", "", IMPORT_FORMATS)
        if p: self.set_file(p)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка с фото")
        if d: self.photo_dir.setText(d)

    def set_file(self, path):
        self.close_sheets()
        try:
            self.sheets = open_source(path)
        except Exception as e:  # noqa: BLE001
            self.file.setText(str(path)); self.log.setPlainText(f"Не удалось открыть источник: {e}"); self.btn.setEnabled(False)
            return False
        self.file.setText(str(path))
        self.sheet.blockSignals(True); self.sheet.clear()
        for sh in self.sheets: self.sheet.addItem(sh.name)
        self.sheet.blockSignals(False)
        self._load(); return True

    def current_sheet(self):
        i = self.sheet.currentIndex()
        return self.sheets[i] if 0 <= i < len(self.sheets) else None

    def is_db(self):
        sh = self.current_sheet(); return sh is not None and sh.kind in ("project", "sqlite")

    def has_image_field(self):
        return any(f.get("data_type") == "image" for f in self.api.list_fields())

    def update_image_hint(self):
        """Подсказка видна только если в проекте нет поля типа «Изображение»."""
        self.no_image_hint.setHidden(self.has_image_field())

    def _load(self):
        self.update_image_hint()
        sh = self.current_sheet()
        if sh is None: return
        self.sheet_kind.setText(f"({SHEET_KINDS.get(sh.kind, sh.kind)})")
        self.use_header.setEnabled(not self.is_db())
        try:
            self.headers, self.rows = read_rows(sh, header=self.use_header.isChecked() or self.is_db(), limit=PREVIEW_LIMIT)
        except Exception as e:  # noqa: BLE001
            self.log.setPlainText(f"Не удалось прочитать лист: {e}"); return
        auto = self.api.auto_match(self.headers)            # D26: только существующие поля БД
        self.auto = {}
        for h, k in zip(self.headers, auto):
            if k and k not in self.auto: self.auto[k] = h
        flds = self.api.list_fields()
        self.fields = [(f["name"], f.get("label") or f["name"], FIELD_TYPE_NAMES[field_type(f)]) for f in flds] + \
                      [t for t in SERVICE_TARGETS if t[0] != "__fio__" or "__fio__" in self.auto]
        self.table.setRowCount(len(self.fields))
        for r, (key, lab, typ) in enumerate(self.fields):
            it = QTableWidgetItem(lab); it.setData(Qt.ItemDataRole.UserRole, key); it.setToolTip(key)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable); self.table.setItem(r, 0, it)
            t = QTableWidgetItem(typ); t.setFlags(t.flags() & ~Qt.ItemFlag.ItemIsEditable); self.table.setItem(r, 1, t)
            m = QTableWidgetItem(""); m.setFlags(Qt.ItemFlag.ItemIsEnabled); self.table.setItem(r, 2, m)
            cb = QComboBox(); cb.addItem(NONE_COL, None)
            for h in self.headers: cb.addItem(h, h)
            if key in self.auto: cb.setCurrentIndex(cb.findData(self.auto[key]))
            cb.currentIndexChanged.connect(lambda _i, r=r: self._changed(r))
            self.table.setCellWidget(r, 3, cb); self._mark(r)
        self.preview.clear(); self.preview.setColumnCount(len(self.headers)); self.preview.setHorizontalHeaderLabels(self.headers)
        self.preview.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            for j in range(len(self.headers)):
                self.preview.setItem(i, j, QTableWidgetItem(row[j] if j < len(row) else ""))
        if self.rows: self.preview.selectRow(0); self._show_row(0)
        else: self.values.setRowCount(0); self._set_photo(None)
        self.btn.setEnabled(bool(self.headers)); self.progress.setValue(0)

    def _combo(self, r): return self.table.cellWidget(r, 3)
    def _keys(self): return [k for k, *_ in self.fields]

    def _changed(self, r):
        h = self._combo(r).currentData()
        if h is not None:                                      # одна колонка — одно поле
            for o in range(self.table.rowCount()):
                if o != r and self._combo(o).currentData() == h:
                    cb = self._combo(o); cb.blockSignals(True); cb.setCurrentIndex(0); cb.blockSignals(False); self._mark(o)
        self._mark(r)

    def _mark(self, r):
        h = self._combo(r).currentData(); key = self.fields[r][0]
        it = self.table.item(r, 2)
        if h is None: it.setText(""); it.setForeground(QColor("#7A8A8A"))
        else:
            it.setText("✓ авто" if self.auto.get(key) == h else "✓ вручную"); it.setForeground(QColor("#1E7B4E"))

    def _set_photo(self, pm):
        if pm is not None and not pm.isNull():
            self.photo.setPixmap(pm.scaled(110, 140, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.photo.setPixmap(QPixmap()); self.photo.setText("нет фото")

    def _show_row(self, r):
        if not (0 <= r < len(self.rows)): return
        row = self.rows[r]; self.values.setRowCount(len(self.headers))
        for j, h in enumerate(self.headers):
            a = QTableWidgetItem(h); a.setBackground(QColor("#E3F0FB"))
            self.values.setItem(j, 0, a); self.values.setItem(j, 1, QTableWidgetItem(row[j] if j < len(row) else ""))
        # D36: один столбец фото — image-поле; значение через Backend resolve_photo_path
        # (нет image-поля → Backend сам пишет колонку «Фото» в photo_path; UI фолбэк не делает)
        import pathlib
        img = next((k for k, _l, t in self.fields if t == FIELD_TYPE_NAMES["image"]), None)
        h = self.field_column(img) if img else None
        if h is None and not img:                   # колонка, которую Backend отправит в photo_path
            h = next((x for x, k in zip(self.headers, self.api.auto_match(self.headers)) if k == "photo_path"), None)
        j = self.headers.index(h) if h in self.headers else -1
        val = row[j] if 0 <= j < len(row) else ""
        person = {"fields": {img: val} if img else {}, "photo_path": None if img else (val or None)}
        src = pathlib.Path(self.file.text())
        bases = ([self.photo_dir.text()] if self.photo_dir.text() else []) + [str(src.parent), str(src.parent / f"{src.stem}_photos")]
        pm = None
        if val:
            paths = [self.api.resolve_photo_path(person, img, base_dir=b) for b in bases]
            p = next((x for x in paths if x and pathlib.Path(x).is_file()), paths[0])
            pm = QPixmap(str(p)) if p else None
        self._set_photo(pm)

    # ---- сопоставление ----
    def field_column(self, field):
        keys = self._keys()
        return self._combo(keys.index(field)).currentData() if field in keys else None

    def set_target(self, header, target):
        """Колонку header → в поле target (None — не импортировать колонку)."""
        for r in range(self.table.rowCount()):
            if self._combo(r).currentData() == header: self._combo(r).setCurrentIndex(0)
        if target is not None:
            keys = self._keys()
            if target not in keys: raise KeyError(target)
            cb = self._combo(keys.index(target)); cb.setCurrentIndex(cb.findData(header))

    def mapping(self):
        """{"Заголовок": "field" | None} для import_rows(mapping=...): только отличия от auto_match."""
        chosen = {self._combo(r).currentData(): k for r, k in enumerate(self._keys()) if self._combo(r).currentData() is not None}
        auto = dict(zip(self.headers, self.api.auto_match(self.headers)))
        m = {}
        for h in self.headers:
            if h in chosen:
                if chosen[h] != auto.get(h): m[h] = chosen[h]
            elif auto.get(h) in self._keys(): m[h] = None   # скрытые цели (photo_path) решает Backend
        return m or None

    def labels(self):
        return None

    def _save_binding(self, _=False, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить привязку", "binding.json", "Привязка (*.json)")
        if not path: return None
        try:
            p = save_mapping(path, self.mapping(), columns=self.headers)
        except Exception as e:  # noqa: BLE001
            self.log.setPlainText(f"Не удалось сохранить привязку: {e}"); return None
        self.log.setPlainText(f"Привязка сохранена: {p}"); return p

    def _load_binding(self, _=False, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Загрузить привязку", "", "Привязка (*.json)")
        if not path: return False
        try:
            data = load_mapping(path)
        except Exception as e:  # noqa: BLE001  (Backend: чужой/битый файл → ValueError)
            self.log.setPlainText(f"Не удалось загрузить привязку: {e}"); return False
        m = data.get("mapping") if isinstance(data, dict) and "mapping" in data else data
        self._load()                                           # сначала авто, затем отличия из файла
        miss = []
        for h, f in (m or {}).items():
            if h not in self.headers: miss.append(h); continue
            try: self.set_target(h, f)
            except KeyError: miss.append(f"{h}→{f}")
        self.log.setPlainText(f"Привязка загружена: {path}" + (f"\nНе применено (нет колонки/поля): {', '.join(miss)}" if miss else ""))
        return True

    def new_source_fields(self):
        """Поля источника-проекта (.db), которых нет в текущем проекте."""
        sh = self.current_sheet()
        if sh is None or sh.kind != "project": return []
        have = {f["name"] for f in self.api.list_fields()}
        return [h for h in self.headers if h not in SERVICE_COLUMNS and h not in have]

    def ask_import_fields(self):
        """True — создать поля источника, False — только существующие, None — отмена."""
        new = self.new_source_fields()
        if not new: return False
        if confirm_fields_hook is not None: return confirm_fields_hook(new)
        mb = QMessageBox(QMessageBox.Icon.Question, "Импорт из базы проекта",
                         "В базе-источнике есть поля, которых нет в текущем проекте:\n\n" + ", ".join(new)
                         + "\n\nСоздать их (с типом и значением по умолчанию) и импортировать значения?", parent=self)
        yes = mb.addButton("Создать поля", QMessageBox.ButtonRole.YesRole)
        no = mb.addButton("Только существующие", QMessageBox.ButtonRole.NoRole)
        mb.addButton("Отмена", QMessageBox.ButtonRole.RejectRole); mb.exec()
        return True if mb.clickedButton() is yes else (False if mb.clickedButton() is no else None)

    # ---- импорт ----
    def run(self):
        sh = self.current_sheet()
        if sh is None: self.log.setPlainText("Выберите источник"); return
        imp_fields = self.ask_import_fields()
        if imp_fields is None: self.log.setPlainText("Импорт отменён."); return
        pd = make_progress(self, "Импорт", "Импорт записей…")
        def progress(done, total):
            pd.setMaximum(max(total, 1)); pd.setValue(done)
            self.progress.setValue(int(100 * done / max(total, 1)))
            QApplication.processEvents()
            return not pd.wasCanceled()
        try:
            rep = self.api.import_rows(sh, self.mapping(), header=self.use_header.isChecked() or self.is_db(),
                                       photo_dir=self.photo_dir.text() or None, labels=self.labels(),
                                       require_photo=self.require_photo.isChecked(), progress=progress,
                                       import_fields=bool(imp_fields))
        except Exception as e:  # noqa: BLE001
            self.log.setPlainText(f"Ошибка импорта: {e}"); return
        finally:
            pd.close()
        self.report = rep
        lines = ["ИМПОРТ ОТМЕНЁН — изменения откатаны." if getattr(rep, "cancelled", False) else "Импорт завершён.",
                 f"Добавлено: {rep.added}", f"Пропущено: {rep.skipped}", f"Валидатор: {rep.validator}"]
        if imp_fields: lines.append("Поля источника созданы в проекте (import_fields).")
        fmt = lambda e: f"  строка {e.get('row')}: {e.get('field') or ''} — {e.get('code')} {e.get('details') or ''}"
        if rep.errors:
            lines += [f"Отклонено строк: {len({e.get('row') for e in rep.errors})} (не импортированы; FIELD_TYPE — неверный тип значения):",
                      *map(fmt, rep.errors)]
        ws = list(getattr(rep, "warnings", None) or [])
        if ws: lines += ["Предупреждения (строки импортированы):", *map(fmt, ws)]
        if getattr(rep, "photo_issues", None):
            lines += ["Проблемы с фото:", *(f"  строка {x.get('row')}: {x.get('code')} {x.get('file') or ''}" if isinstance(x, dict) else f"  {x}"
                                            for x in rep.photo_issues)]
        if getattr(rep, "skipped_columns", None):
            cols = [(c.get("label") or c.get("key")) if isinstance(c, dict) else str(c) for c in rep.skipped_columns]
            lines += ["Колонки файла не импортированы (нет такого поля БД): " + ", ".join(cols)]
        self.log.setPlainText("\n".join(lines))
        if not getattr(rep, "cancelled", False): self.btn.setEnabled(False); self.progress.setValue(100)
        else: self.progress.setValue(0)


# ---------------- фоновое выполнение по snapshot ----------------
class SnapshotWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, fn, *args, allow_missing_photo=False):
        super().__init__()
        self.fn, self.args, self.allow = fn, args, allow_missing_photo
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        def cb(done, total):
            self.progress.emit(done, total)
            return not self._cancel.is_set()
        try:
            self.done.emit(self.fn(*self.args, progress=cb, allow_missing_photo=self.allow))
        except Exception as e:  # noqa: BLE001  (MissingPhotosError и др.)
            self.failed.emit(e)


def run_snapshot_job(parent, title, fn, *args, allow_missing_photo=False):
    """Запустить worker с QProgressDialog (Отмена → progress вернёт False). Возвращает (result, error).
    Только для экспорта (Pillow). Печать на QPrinter — через run_print_job в главном потоке."""
    pd = make_progress(parent, title, f"{title}…")
    w = SnapshotWorker(fn, *args, allow_missing_photo=allow_missing_photo)
    box = {"res": None, "err": None}
    w.progress.connect(lambda a, b: (pd.setMaximum(max(b, 1)), pd.setValue(a)))
    w.done.connect(lambda r: box.__setitem__("res", r)); w.failed.connect(lambda e: box.__setitem__("err", e))
    pd.canceled.connect(w.cancel)
    if pd.wasCanceled(): w.cancel()
    loop = QEventLoop(); w.finished.connect(loop.quit)
    w.start(); loop.exec(); w.wait(); QApplication.processEvents()
    pd.close()
    return box["res"], box["err"]


def run_print_job(parent, title, fn, *args, allow_missing_photo=False):
    """Вызвать print_snapshot в GUI-потоке. QPrinter/QPainter нельзя уводить в QThread.
    Прогресс и «Отмена» — тот же QProgressDialog, что у экспорта (processEvents, abort сохраняется)."""
    pd = make_progress(parent, title, f"{title}…")
    def cb(done, total):
        pd.setMaximum(max(total, 1)); pd.setValue(done)
        QApplication.processEvents()
        return not pd.wasCanceled()
    try:
        res, err = fn(*args, progress=cb, allow_missing_photo=allow_missing_photo), None
    except Exception as e:  # noqa: BLE001  (MissingPhotosError и др.)
        res, err = None, e
    pd.close()
    QApplication.processEvents()
    return res, err


def describe_result(res, err, kind):
    """Текст для пользователя по результату Backend."""
    if isinstance(err, MissingPhotosError):
        return f"{kind}: отменено — нет фото у записей {getattr(err, 'ids', [])}"
    if err is not None:
        return f"{kind}: ошибка — {err}"
    if res is None:
        return f"{kind}: отменено пользователем (файл не создан)"
    parts = []
    if getattr(res, "cancelled", False): parts.append("отменено пользователем")
    n = len(res) if isinstance(res, list) else (res if isinstance(res, int) else 1)
    parts.append(f"{'файлов' if isinstance(res, list) else ('страниц' if isinstance(res, int) else 'PDF')}: {n}")
    miss = getattr(res, "missing_photo_ids", None)
    if miss: parts.append(f"с плейсхолдером «нет фото»: {list(miss)}")
    text = f"{kind}: " + "; ".join(parts)
    if getattr(res, "empty_template", False):
        text += "\n⚠ " + EMPTY_TEMPLATE_WARNING
    for wmsg in getattr(res, "warnings", None) or []:
        if getattr(res, "empty_template", False) and "пуст" in str(wmsg) and "сторона" not in str(wmsg): continue
        text += f"\nПредупреждение: {wmsg}"
    return text


def show_result_warnings(parent, res, kind):
    """Явное предупреждение пользователю: пустой шаблон и/или .warnings результата Backend."""
    if res is None: return None
    ws = list(getattr(res, "warnings", None) or [])
    if not ws and not getattr(res, "empty_template", False): return None
    text = describe_result(res, None, kind)
    if warning_hook is not None: warning_hook(kind, text)
    else: QMessageBox.warning(parent, kind, text)
    return text


EMPTY_TEMPLATE_WARNING = "Шаблон пуст — карточки выведены без элементов. Добавьте элементы: вкладка ленты «Рисование»."


# ---------------- экспорт ----------------
D29_HINT = "Значения по умолчанию сохраняются только в .db"


class ExportDialog(QDialog):
    """Экспорт: карточки (PNG/PDF) или данные записей (.xlsx/.xls/.csv/.db, Backend export_persons)."""
    DATA_FORMATS = DATA_FORMATS

    def __init__(self, api: BackendAPI, selected_ids=(), parent=None, filtered_ids=None):
        super().__init__(parent)
        self.api, self.selected_ids = api, list(selected_ids)
        self.filtered_ids = None if filtered_ids is None else list(filtered_ids)
        self.result, self.error = None, None
        self.setWindowTitle("Экспорт")
        self.m_cards, self.m_data = QRadioButton("Карточки (PNG / PDF)"), QRadioButton("Данные записей (.xlsx / .xls / .csv / .db)")
        self.m_cards.setChecked(True); gm = QButtonGroup(self); gm.addButton(self.m_cards); gm.addButton(self.m_data)
        self.data_fmt = QComboBox()
        for k, t in self.DATA_FORMATS: self.data_fmt.addItem(t, k)
        self.data_fmt.currentIndexChanged.connect(self._fmt_changed)
        n_all = len(self.api.list_persons())
        self.d_all = QRadioButton(f"Все записи ({n_all})")
        n_f = len(self.filtered_ids) if self.filtered_ids is not None else n_all
        self.d_filtered = QRadioButton(f"Только отфильтрованные ({n_f})")
        self.d_all.setChecked(True); gd = QButtonGroup(self); gd.addButton(self.d_all); gd.addButton(self.d_filtered)
        self.hint = QLabel(f"ⓘ {D29_HINT}"); self.hint.setStyleSheet("color:#9A5B00;"); self.hint.setWordWrap(True)
        self.png, self.pdf = QRadioButton("PNG (300 DPI, файл на сторону)"), QRadioButton("PDF (CR80, страница на сторону)")
        self.png.setChecked(True); g = QButtonGroup(self); g.addButton(self.png); g.addButton(self.pdf)
        self.front, self.back = QCheckBox("Лицевая"), QCheckBox("Оборотная"); self.front.setChecked(True); self.back.setChecked(True)
        self.scope = QComboBox()
        self.scope.addItem("Отмеченные для печати", "marked")
        self.scope.addItem(f"Выделенные в таблице ({len(self.selected_ids)})", "selected")
        self.scope.addItem("Все записи", "all")
        if self.selected_ids: self.scope.setCurrentIndex(1)
        self.target = QLineEdit(); b = QPushButton("Обзор…"); b.clicked.connect(self._pick)
        tr = QHBoxLayout(); tr.addWidget(self.target, 1); tr.addWidget(b)
        sides = QHBoxLayout(); sides.addWidget(self.front); sides.addWidget(self.back)
        mode = QHBoxLayout(); mode.addWidget(self.m_cards); mode.addWidget(self.m_data); mode.addStretch(1)
        drec = QHBoxLayout(); drec.addWidget(self.d_all); drec.addWidget(self.d_filtered); drec.addStretch(1)
        form = QFormLayout(); form.addRow("Что:", mode)
        form.addRow("Формат:", self.png); form.addRow("", self.pdf)
        form.addRow("Стороны:", sides); form.addRow("Записи:", self.scope)
        form.addRow("Формат данных:", self.data_fmt); form.addRow("Записи данных:", drec); form.addRow("", self.hint)
        form.addRow("Куда:", tr)
        self.form = form
        self.cards_rows = [self.png, self.pdf, sides, self.scope]; self.data_rows = [self.data_fmt, drec]
        self.status = QLabel(); self.status.setWordWrap(True)
        self.bb = QDialogButtonBox(); self.go = self.bb.addButton("Экспортировать", QDialogButtonBox.ButtonRole.AcceptRole)
        self.bb.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        self.go.clicked.connect(self.start); self.bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(self.status); lay.addWidget(self.bb)
        self.m_data.toggled.connect(self._mode); self._mode()
        self.setMinimumSize(620, 300)

    def _mode(self, *_):
        data = self.m_data.isChecked()
        for w in self.cards_rows: self.form.setRowVisible(w, not data)
        for w in self.data_rows: self.form.setRowVisible(w, data)
        self._fmt_changed()
        self.setWindowTitle("Экспорт данных" if data else "Экспорт карточек")

    def _fmt_changed(self, *_):
        """D29: в табличных форматах default_value полей не переносится."""
        self.form.setRowVisible(self.hint, self.m_data.isChecked() and self.data_fmt.currentData() != "db")
        t = self.target.text()
        if self.m_data.isChecked() and t:
            import pathlib
            p = pathlib.Path(t)
            if p.suffix.lower().lstrip(".") in {k for k, _ in self.DATA_FORMATS}:
                self.target.setText(str(p.with_suffix("." + self.data_fmt.currentData())))

    def data_ids(self):
        if self.d_filtered.isChecked() and self.filtered_ids is not None: return list(self.filtered_ids)
        return [p["id"] for p in self.api.list_persons()]

    def start_data(self):
        fmt, ids = self.data_fmt.currentData(), self.data_ids()
        self.result = self.error = None
        if not self.target.text():
            self.status.setText("Укажите файл"); return False
        if not ids:
            self.status.setText("Нет записей для экспорта"); return False
        if fmt == "xls" and len(ids) > XLS_MAX_ROWS:
            self.error = ValueError(f"Слишком много записей для формата .xls: выбрано {len(ids)}, максимум {XLS_MAX_ROWS}. "
                                    "Выберите формат .xlsx (Excel 2007+) — в нём ограничения нет.")
            self.status.setText(f"Ошибка: {self.error}"); return False
        try:
            self.result = self.api.export_persons(self.target.text(), fmt, ids)
        except Exception as e:  # noqa: BLE001  (ValueError .xls, FileExistsError .db …)
            self.error = e
            msg = f"Файл уже существует: {e}" if isinstance(e, FileExistsError) else str(e)
            self.status.setText(f"Ошибка: {msg}"); return False
        r = self.result
        text = f"Экспорт данных: {r.get('rows')} записей → {r.get('path')}"
        if r.get("files_copied") is not None: text += f"; файлов скопировано: {r['files_copied']}"
        for wmsg in r.get("warnings") or []: text += f"\nПредупреждение: {wmsg}"
        self.status.setText(text)
        return True

    def _pick(self):
        if self.m_data.isChecked():
            fmt = self.data_fmt.currentData()
            p, _ = QFileDialog.getSaveFileName(self, "Файл данных", f"persons.{fmt}", f"*.{fmt}")
        elif self.pdf.isChecked():
            p, _ = QFileDialog.getSaveFileName(self, "PDF-файл", "cards.pdf", "PDF (*.pdf)")
        else:
            p = QFileDialog.getExistingDirectory(self, "Папка для PNG")
        if p: self.target.setText(p)

    def ids(self):
        s = self.scope.currentData()
        if s == "selected": return self.selected_ids
        if s == "all": return [p["id"] for p in self.api.list_persons()]
        return [p["id"] for p in self.api.list_persons(only_marked=True)]

    def sides(self):
        return [s for s, cb in (("front", self.front), ("back", self.back)) if cb.isChecked()]

    def start(self):
        if self.m_data.isChecked(): return self.start_data()
        ids, sides = self.ids(), self.sides()
        self.result = self.error = None
        if not self.target.text() or not ids or not sides:
            self.status.setText("Укажите путь, стороны и хотя бы одну запись"); return False
        go, allow = confirm_missing_photos(self, self.api, ids)
        if not go:
            self.status.setText("Экспорт отменён: есть записи без фото"); return False
        snap = self.api.snapshot(ids, sides)          # GUI-поток
        fn = export_pdf_from_snapshot if self.pdf.isChecked() else export_png_from_snapshot
        self.go.setEnabled(False)
        self.result, self.error = run_snapshot_job(self, "Экспорт", fn, snap, self.target.text(), self.api.base_dir,
                                                   allow_missing_photo=allow)
        self.go.setEnabled(True)
        self.status.setText(describe_result(self.result, self.error, "Экспорт"))
        if self.error is None: show_result_warnings(self, self.result, "Экспорт")
        return self.error is None and self.result is not None and not getattr(self.result, "cancelled", False)
