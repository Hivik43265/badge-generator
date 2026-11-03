"""QA этап 13b (Frontend D31–D35): диалоги импорта/экспорта offscreen через act_import/act_export.
QT_QPA_PLATFORM=offscreen .venv/bin/python reports/qa/e2e_stage13b.py"""
import os, sys, json, tempfile, pathlib, ast, re
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from PIL import Image
import xlwt
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer
app = QApplication.instance() or QApplication(sys.argv)
from ui.backend_api import BackendAPI
from ui import dialogs
from ui.dialogs import ImportDialog, ExportDialog, D29_HINT
from ui.main_window import MainWindow
from badge_backend import api as bapi
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa13b_")); RES = []
def chk(n, ok, ev=""): RES.append((n, bool(ok), str(ev))); print("PASS" if ok else "FAIL", "|", n, "|", ev)

api = BackendAPI(TMP / "p.db", TMP)
api.upsert_field("last_name", "Фамилия", 0, data_type="text"); api.upsert_field("dept", "Отдел", 1, data_type="text")
w = MainWindow(api); w.show(); app.processEvents()
PH = TMP / "ph"; PH.mkdir(); Image.new("RGB", (60, 80), "red").save(PH / "a.png")

# xls с двумя листами
xp = TMP / "multi.xls"; wb = xlwt.Workbook()
s1 = wb.add_sheet("Лист1"); [s1.write(0, j, h) for j, h in enumerate(["Фамилия", "Отдел", "Фото"])]
s1.write(1, 0, "Иванов"); s1.write(1, 1, "ИТ"); s1.write(1, 2, "a.png")
s2 = wb.add_sheet("Сотрудники2"); [s2.write(0, j, h) for j, h in enumerate(["Фамилия", "Отдел"])]
for i, (a, b) in enumerate([("Петров", "Бух"), ("Сидоров", "ИТ")], 1): s2.write(i, 0, a); s2.write(i, 1, b)
wb.save(str(xp))

# D31 через act_import (перехватываем открытый диалог)
seen = {}
def grab():
    for wd in app.topLevelWidgets():
        if isinstance(wd, ImportDialog) and wd.isVisible(): seen["d"] = wd; wd.reject(); return
    QTimer.singleShot(50, grab)
QTimer.singleShot(50, grab); w.act_import.trigger(); app.processEvents()
chk("D31 act_import открывает ImportDialog", "d" in seen)
d = ImportDialog(api, w); d.set_file(str(xp)); d.photo_dir.setText(str(PH))
names = [d.sheet.itemText(i) for i in range(d.sheet.count())]
chk("D31 xls: список листов", names == ["Лист1", "Сотрудники2"], names)
d.sheet.setCurrentIndex(1); app.processEvents()
chk("D31 смена листа перезагружает превью", d.preview.rowCount() == 2 and d.preview.item(0, 0).text() == "Петров",
    f"rows={d.preview.rowCount()}")
d.run(); app.processEvents()
ln = sorted(p["fields"].get("last_name") for p in api.list_persons())
chk("D31 импорт выбранного листа xls", ln == ["Петров", "Сидоров"], ln)
chk("D31 импорт не создаёт поля", sorted(f["name"] for f in api.list_fields()) == ["dept", "last_name"])
d.done(0)
# D33 превью строк и фото
d = ImportDialog(api, w); d.set_file(str(xp)); d.photo_dir.setText(str(PH)); d._show_row(0); app.processEvents()
vals = {d.values.item(i, 0).text(): d.values.item(i, 1).text() for i in range(d.values.rowCount())}
pm = d.photo.pixmap()
chk("D33 превью строк заполнено", d.preview.rowCount() == 1 and d.preview.columnCount() == 3, f"{d.preview.rowCount()}x{d.preview.columnCount()}")
chk("D33 «Колонка|Значение» выбранной строки", vals.get("Фамилия") == "Иванов", vals)
chk("D33 превью фото", pm is not None and not pm.isNull(), f"text={d.photo.text()!r}")
# D32 привязка
d.set_target("Отдел", None); d.set_target("Фото", "dept"); m1 = d.mapping()
bp = TMP / "b.json"; p = d._save_binding(path=str(bp))
chk("D32 сохранение привязки", p and bp.exists(), bp.read_text(encoding="utf-8")[:150] if bp.exists() else "")
d.done(0)
d = ImportDialog(api, w); d.set_file(str(xp)); m0 = d.mapping()
ok = d._load_binding(path=str(bp)); m2 = d.mapping()
chk("D32 загрузка привязки: roundtrip", ok and m2 == m1 and m0 != m1, f"до={m0} сохр={m1} после={m2}")
bad = TMP / "bad.json"; bad.write_text("{не json", encoding="utf-8")
chk("D32 битая привязка → сообщение, без исключения", d._load_binding(path=str(bad)) is False, d.log.toPlainText()[:80])
d.done(0)

# D34 экспорт 4 форматов
pid = api.list_persons()[0]["id"]
for fmt in ("xlsx", "xls", "csv", "db"):
    ex = ExportDialog(api, [pid], w); ex.m_data.setChecked(True)
    ex.data_fmt.setCurrentIndex(ex.data_fmt.findData(fmt)); app.processEvents()
    hint_vis = not ex.hint.isHidden()
    out = TMP / f"out.{fmt}"; ex.target.setText(str(out)); r = ex.start()
    chk(f"D34 экспорт {fmt}", r and out.exists() and (ex.result or {}).get("rows") == 2, ex.status.text()[:100])
    chk(f"D34 D29-подсказка {'скрыта' if fmt=='db' else 'видна'} для {fmt}", hint_vis == (fmt != "db"), f"visible={hint_vis}; text={D29_HINT}")
    ex.done(0)
seen.clear()
def grab2():
    for wd in app.topLevelWidgets():
        if isinstance(wd, ExportDialog) and wd.isVisible(): seen["e"] = wd; wd.reject(); return
    QTimer.singleShot(50, grab2)
QTimer.singleShot(50, grab2); w.act_export.trigger(); app.processEvents()
chk("D34 act_export открывает единый ExportDialog", "e" in seen)

# D35 импорт .db
src = bapi.connect(str(TMP / "src.db")); bapi.upsert_field(src, "last_name", "Фамилия", 0); bapi.upsert_field(src, "extra", "Доп", 1, default_value="X")
bapi.create_person(src, {"last_name": "Козлов", "extra": "e1"}); src.close()
for ans, lbl in ((None, "отмена"), (False, "только существующие"), (True, "создать поля")):
    a2 = BackendAPI(TMP / f"t_{lbl}.db", TMP); a2.upsert_field("last_name", "Фамилия", 0, data_type="text")
    asked = []; dialogs.confirm_fields_hook = lambda new, ans=ans: (asked.append(list(new)), ans)[1]
    dd = ImportDialog(a2, w); dd.set_file(str(TMP / "src.db")); dd.run(); app.processEvents()
    fl = sorted(f["name"] for f in a2.list_fields()); n = len(a2.list_persons())
    exp = {None: (["last_name"], 0), False: (["last_name"], 1), True: (["extra", "last_name"], 1)}[ans]
    chk(f"D35 .db: {lbl}", asked == [["extra"]] and (fl, n) == exp, f"спрошено={asked}; поля={fl}; записей={n}")
    if ans: chk("D35 default_value перенесён из .db", any(f["name"] == "extra" and f.get("default_value") == "X" for f in a2.list_fields()))
    dd.done(0); a2.close()
dialogs.confirm_fields_hook = None

# Дубли
acts = [a for a in w.findChildren(QAction) if re.search(r"(?i)экспорт|импорт|менеджер полей", a.text())]
chk("Дубли: QAction импорт/экспорт/менеджер полей по одному", sorted(a.objectName() for a in acts).count("act_export") == 1 and len({a.text() for a in acts}) == len(acts), [(a.objectName(), a.text()) for a in acts])
d = ImportDialog(api, w)
chk("Дубли: кнопка «Менеджер полей…» = setDefaultAction(act_field_manager)", getattr(d.b_fields, "defaultAction", lambda: None)() is w.act_field_manager)
d.done(0)
src_ui = {f.name: f.read_text(encoding="utf-8") for f in (ROOT / "ui").glob("*.py") if f.name not in ("smoke_test.py", "qa_click_all.py", "self_test.py")}
bad_imp = [n for n, s in src_ui.items() if re.search(r"^\s*(import|from)\s+(openpyxl|xlrd|xlwt|csv|sqlite3)\b", s, re.M)]
chk("Дубли: ui/ не читает/пишет xlsx/xls/csv/sqlite сам", not bad_imp, bad_imp)
legacy = [n for n, s in src_ui.items() if re.search(r"\.import_file\(", s) and n != "backend_api.py"]
chk("Дубли: старый путь import_file не вызывается из ui/", not legacy, legacy)
ph = [f"{n}:{i+1}" for n, s in src_ui.items() for i, l in enumerate(s.splitlines()) if re.search(r"""['"]photos['"]|photo_dir\s*/|base_dir\s*/\s*.*photo""", l)]
chk("Фото: путь не вычисляется в ui/ вне resolve_photo_path", not ph, ph)

w.close(); n_ok = sum(r[1] for r in RES)
(ROOT / "reports/qa/e2e_stage13b_results.json").write_text(json.dumps(RES, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"ИТОГО: {n_ok}/{len(RES)} PASS; tmp={TMP}"); sys.exit(0 if n_ok == len(RES) else 1)
