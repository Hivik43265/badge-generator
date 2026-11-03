"""Диалоги импорта, экспорта и печати.

Импорт выполняется в GUI-потоке (соединение sqlite привязано к нему) с QProgressDialog и отменой.
Экспорт/печать: missing_photos() + snapshot() в GUI-потоке → рабочий QThread вызывает
*_from_snapshot / print_snapshot без соединения (работает и с :memory:).
"""
import threading
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QEventLoop
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton,
                             QFileDialog, QTableWidget, QTableWidgetItem, QComboBox, QPlainTextEdit,
                             QDialogButtonBox, QRadioButton, QCheckBox, QLabel, QHeaderView,
                             QButtonGroup, QMessageBox, QProgressDialog, QApplication)
from .backend_api import (BackendAPI, map_headers, LABELS, MissingPhotosError,
                          export_png_from_snapshot, export_pdf_from_snapshot, print_snapshot)

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
        f = p["fields"]; names.append(f"#{pid} {f.get('last_name', '')} {f.get('first_name', '')}".strip())
    if confirm_hook is not None:
        return bool(confirm_hook(parent, miss, names)), True
    text = ("У следующих записей нет фото или файл недоступен — на карточке будет плейсхолдер «нет фото»:\n\n"
            + "\n".join(names[:30]) + (f"\n… и ещё {len(names) - 30}" if len(names) > 30 else "")
            + "\n\nПродолжить?")
    r = QMessageBox.warning(parent, "Нет фото", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No)
    return r == QMessageBox.StandardButton.Yes, True


# ---------------- импорт ----------------
class ImportDialog(QDialog):
    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api, self.report, self.headers = api, None, []
        self.setWindowTitle("Импорт записей"); self.resize(820, 600)
        self.file = QLineEdit(); self.photo_dir = QLineEdit()
        bf = QPushButton("Обзор…"); bf.clicked.connect(self._pick_file)
        bd = QPushButton("Обзор…"); bd.clicked.connect(self._pick_dir)
        self.require_photo = QCheckBox("Требовать фото (строки без фото пропускать)")
        form = QFormLayout()
        form.addRow("Файл (.xlsx/.csv):", self._row(self.file, bf)); form.addRow("Папка с фото:", self._row(self.photo_dir, bd))
        form.addRow(self.require_photo)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Колонка файла", "Поле записи", "Заголовок в таблице"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.log = QPlainTextEdit(readOnly=True); self.log.setPlaceholderText("Здесь будет отчёт об импорте")
        self.btn = QPushButton("Импортировать"); self.btn.clicked.connect(self.run); self.btn.setEnabled(False)
        close = QPushButton("Закрыть"); close.clicked.connect(self.accept)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(QLabel("Сопоставление колонок:"))
        lay.addWidget(self.table, 2); lay.addWidget(self.log, 1); lay.addLayout(self._row(self.btn, close, stretch=False))

    @staticmethod
    def _row(*ws, stretch=True):
        l = QHBoxLayout()
        for i, w in enumerate(ws): l.addWidget(w, 1 if stretch and i == 0 else 0)
        return l

    def _pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Файл импорта", "", "Таблицы (*.xlsx *.xlsm *.csv *.txt)")
        if p: self.set_file(p)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка с фото")
        if d: self.photo_dir.setText(d)

    def set_file(self, path):
        self.file.setText(path)
        try:
            headers = [str(h) if h is not None else "" for h in self.api.read_headers(path)]
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Импорт", f"Не удалось прочитать файл: {e}"); return
        auto = map_headers(headers)
        existing = {f["name"]: f["label"] for f in self.api.list_fields()}
        names = {**existing, **LABELS, "photo_path": "Фото (путь)", "photo_config": "Настройки фото", "__fio__": "ФИО (разбить)"}
        targets = list(dict.fromkeys([*LABELS, "photo_path", "photo_config", "__fio__", *existing]))
        self.table.setRowCount(len(headers)); self.headers = headers
        for r, (h, k) in enumerate(zip(headers, auto)):
            it = QTableWidgetItem(h); it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable); self.table.setItem(r, 0, it)
            cb = QComboBox()
            cb.addItem(f"(авто: {names.get(k, k) if k else 'игнор'})", AUTO)
            cb.addItem("— не импортировать —", SKIP)
            for t in targets: cb.addItem(f"{names.get(t, t)} [{t}]", t)
            self.table.setCellWidget(r, 1, cb)
            self.table.setItem(r, 2, QTableWidgetItem(""))   # пусто = label по умолчанию Backend
        self.table.setToolTip("Третья колонка: свой заголовок поля (необязательно)")
        self.btn.setEnabled(bool(headers))

    def set_target(self, header, target):
        """target: ключ поля, None — исключить, AUTO — автоматически."""
        r = self.headers.index(header); cb = self.table.cellWidget(r, 1)
        cb.setCurrentIndex(cb.findData(SKIP if target is None else target))

    def mapping(self):
        """{"Заголовок": "field" | None} — новый формат import_file(mapping=...)."""
        m = {}
        for r, h in enumerate(self.headers):
            t = self.table.cellWidget(r, 1).currentData()
            if t == SKIP: m[h] = None
            elif t != AUTO: m[h] = t
        return m or None

    def labels(self):
        """{key: label} для заданных вручную заголовков (только для явно назначенных колонок)."""
        out = {}
        for r, h in enumerate(self.headers):
            t = self.table.cellWidget(r, 1).currentData(); lab = self.table.item(r, 2).text().strip()
            if lab and t not in (AUTO, SKIP, "photo_path", "photo_config", "__fio__"): out[t] = lab
        return out or None

    def run(self):
        pd = make_progress(self, "Импорт", "Импорт записей…")
        def progress(done, total):
            pd.setMaximum(max(total, 1)); pd.setValue(done)
            QApplication.processEvents()
            return not pd.wasCanceled()
        try:
            rep = self.api.import_file(self.file.text(), self.mapping(), self.photo_dir.text() or None,
                                       labels=self.labels(), require_photo=self.require_photo.isChecked(),
                                       progress=progress)
        except Exception as e:  # noqa: BLE001
            self.log.setPlainText(f"Ошибка импорта: {e}"); return
        finally:
            pd.close()
        self.report = rep
        lines = ["ИМПОРТ ОТМЕНЁН — изменения откатаны." if getattr(rep, "cancelled", False) else "Импорт завершён.",
                 f"Добавлено: {rep.added}", f"Пропущено: {rep.skipped}", f"Валидатор: {rep.validator}"]
        fmt = lambda e: f"  строка {e.get('row')}: {e.get('field')} — {e.get('code')} {e.get('details') or ''}"
        if rep.errors: lines += ["Ошибки (строки не импортированы):", *map(fmt, rep.errors)]
        if getattr(rep, "warnings", None): lines += ["Предупреждения (строки импортированы):", *map(fmt, rep.warnings)]
        self.log.setPlainText("\n".join(lines))
        if not getattr(rep, "cancelled", False): self.btn.setEnabled(False)


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
    """Запустить worker с QProgressDialog (Отмена → progress вернёт False). Возвращает (result, error)."""
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


EMPTY_TEMPLATE_WARNING = "Шаблон пуст — карточки выведены без элементов. Добавьте элементы: «Дизайн → Редактор макета»."


# ---------------- экспорт ----------------
class ExportDialog(QDialog):
    def __init__(self, api: BackendAPI, selected_ids=(), parent=None):
        super().__init__(parent)
        self.api, self.selected_ids = api, list(selected_ids)
        self.result, self.error = None, None
        self.setWindowTitle("Экспорт карточек")
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
        form = QFormLayout(); form.addRow("Формат:", self.png); form.addRow("", self.pdf)
        form.addRow("Стороны:", sides); form.addRow("Записи:", self.scope); form.addRow("Куда:", tr)
        self.status = QLabel(); self.status.setWordWrap(True)
        self.bb = QDialogButtonBox(); self.go = self.bb.addButton("Экспортировать", QDialogButtonBox.ButtonRole.AcceptRole)
        self.bb.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        self.go.clicked.connect(self.start); self.bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(self.status); lay.addWidget(self.bb)

    def _pick(self):
        if self.pdf.isChecked():
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
