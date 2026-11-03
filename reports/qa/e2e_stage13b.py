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

# ---- D36 (QA): один столбец фото, превью через resolve_photo_path, photo_path без image-поля ----
import inspect
for with_img in (False, True):
    tag = "с image-полем" if with_img else "без image-поля"
    a3 = BackendAPI(TMP / f"d36_{int(with_img)}.db", TMP); a3.upsert_field("last_name", "Фамилия", 0, data_type="text")
    if with_img: a3.upsert_field("foto", "Фото", 1, data_type="image")
    d = ImportDialog(a3, w); d.set_file(str(xp)); d.photo_dir.setText(str(PH)); d._show_row(0); app.processEvents()
    labs = [d.table.item(r, 0).text() for r in range(d.table.rowCount())]
    keys = d._keys(); img_rows = [k for k, _l, t in d.fields if t == dialogs.FIELD_TYPE_NAMES["image"]]
    chk(f"D36 [{tag}] нет строки «Фото записи (photo_path)»", not any("photo_path" in l for l in labs) and "photo_path" not in keys, labs)
    chk(f"D36 [{tag}] строк фото в сопоставлении ≤1 (image-поле)", len(img_rows) == (1 if with_img else 0), img_rows)
    hdr = [d.preview.horizontalHeaderItem(j).text() for j in range(d.preview.columnCount())]
    chk(f"D36 [{tag}] в превью один столбец «Фото»", sum("фото" in h.lower() for h in hdr) == 1, hdr)
    pm = d.photo.pixmap(); chk(f"D36 [{tag}] превью фото показано", pm is not None and not pm.isNull(), d.photo.text())
    d.run(); app.processEvents(); p0 = a3.list_persons()[0]
    rp = a3.resolve_photo_path(p0, "foto" if with_img else None)  # D39: копия в <проект>/photos/
    if with_img: chk(f"D36 [{tag}] импорт: фото в image-поле, photo_path пуст", p0["fields"].get("foto") and not p0.get("photo_path"), (p0["fields"], p0.get("photo_path")))
    else: chk(f"D36 [{tag}] импорт: фото в photo_path", bool(p0.get("photo_path")), p0.get("photo_path"))
    chk(f"D36 [{tag}] resolve_photo_path(база проекта, D39) → существующий файл", rp is not None and pathlib.Path(rp).is_file(), rp)
    d.done(0); a3.close()
chk("D36 BackendAPI.import_file удалён", not hasattr(BackendAPI, "import_file"))
callers = [f"{f.relative_to(ROOT)}" for f in list((ROOT / "ui").glob("*.py")) + [ROOT / "main.py"] if re.search(r"\bimport_file\(", f.read_text(encoding="utf-8"))]
chk("D36 import_file нигде в ui/ и main.py не вызывается", not callers, callers)
srcd = inspect.getsource(ImportDialog._show_row)
chk("D36 _show_row берёт путь через api.resolve_photo_path, без своей сборки base/p", "resolve_photo_path" in srcd and not re.search(r"pathlib\.Path\(b\)\s*/", srcd), "")

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

# ---- D37 (QA): .db confirm только реальные новые поля; подсказка без image-поля ----
from badge_backend.services import headers as _hdr, sources as _srcm, importer as _impm
asked = []; dialogs.confirm_fields_hook = lambda new: (asked.append(list(new)), False)[1]
a4 = BackendAPI(TMP / "d37.db", TMP); a4.upsert_field("last_name", "Фамилия", 0, data_type="text")
dd = ImportDialog(a4, w); dd.set_file(str(TMP / "src.db")); dd.run(); app.processEvents()
chk("D37 .db: подтверждение предлагает только ['extra']", asked == [["extra"]], asked)
dialogs.confirm_fields_hook = None
chk("D37 подсказка видна без image-поля", dd.no_image_hint.isVisibleTo(dd) and dd.no_image_hint.text() == "Добавьте поле типа Изображение в Менеджере полей", dd.no_image_hint.text())
dd.done(0); a4.close()
a5 = BackendAPI(TMP / "d37i.db", TMP); a5.upsert_field("foto", "Фото", 0, data_type="image")
dd = ImportDialog(a5, w); dd.set_file(str(xp)); app.processEvents()
chk("D37 подсказка скрыта при наличии image-поля", not dd.no_image_hint.isVisibleTo(dd))
dd.done(0); a5.close()
_ds = pathlib.Path(dialogs.__file__).read_text(encoding="utf-8") + pathlib.Path(dialogs.__file__).with_name("backend_api.py").read_text(encoding="utf-8")
chk("D37 ui/ без своего списка служебных колонок (SERVICE_KEYS/PROJECT_COLS из Backend)", "SERVICE_KEYS" in _ds and "PROJECT_COLS" in _ds and not re.search(r"""\{\s*['"]photo_path['"]\s*,\s*['"]photo_config['"]""", _ds), "")

# ---- D38 (QA): встроенная картинка xlsx ----
import hashlib, shutil
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
def mk_xlsx(path):
    g = TMP / "g_emb.png"; Image.new("RGB", (21, 33), (0, 128, 0)).save(g)
    wb = Workbook(); ws = wb.active; ws.append(["Фамилия", "Снимок"]); ws.append(["Ёжиков", None]); ws.append(["Щукина", None])
    ws.add_image(XLImage(str(g)), "B2"); wb.save(path); return path
def opens(con, person, el):
    p = bapi.resolve_photo_path(person, el, bapi.project_base_dir(con))
    try:
        with Image.open(p) as im: im.load(); return im.size
    except Exception as e: return repr(e)
for img in (True, False):
    tag = "с image-полем" if img else "без image-поля"
    pd = TMP / f"d38_{int(img)}"; pd.mkdir(); c = bapi.connect(pd / "p.db"); bapi.upsert_field(c, "last_name", "Фамилия")
    if img: bapi.upsert_field(c, "a", "A", data_type="image"); bapi.upsert_field(c, "b", "B", data_type="image")
    out = TMP / f"d38x_{int(img)}"; out.mkdir()
    rep = bapi.import_rows(c, bapi.open_source(mk_xlsx(TMP / f"e{int(img)}.xlsx"))[0], *([{"Снимок": "b"}] if img else []), photo_dir=out)
    p0, p1 = bapi.list_persons(c)
    files = list((pd / "photos").iterdir()) if (pd / "photos").exists() else []
    if img:
        chk(f"D38 [{tag}] картинка → сопоставленное поле b, photo_path пуст, a пусто", str(p0["fields"].get("b", "")).startswith("photos/") and not p0["photo_path"] and not p0["fields"].get("a"), (p0["fields"], p0["photo_path"]))
        chk(f"D38 [{tag}] фото открывается", opens(c, p0, "b") == (21, 33), opens(c, p0, "b"))
    else:
        chk(f"D38 [{tag}] картинка → photo_path (photos/…)", str(p0["photo_path"] or "").startswith("photos/"), p0["photo_path"])
        chk(f"D38 [{tag}] фото открывается", opens(c, p0, None) == (21, 33), opens(c, p0, None))
    chk(f"D38 [{tag}] без дублей хранения: 1 файл в photos/, 0 во временной папке, 2-я запись без фото", len(files) == 1 and list(out.iterdir()) == [] and not p1["photo_path"] and not any(p1["fields"].get(k) for k in ("a", "b")), f"photos={[f.name for f in files]}; tmp={list(out.iterdir())}")
    c.close()

# ---- D39 (QA): «Фото: папка» копируется; удаление исходника; отмена удаляет копии ----
pd = TMP / "d39"; pd.mkdir(); c = bapi.connect(pd / "p.db"); bapi.upsert_field(c, "last_name", "Фамилия"); bapi.upsert_field(c, "pic", "Фото", data_type="image")
sd = TMP / "d39src"; sd.mkdir(); Image.new("RGB", (40, 50), "navy").save(sd / "x.png"); h_src = hashlib.sha256((sd / "x.png").read_bytes()).hexdigest()
cs = TMP / "d39.csv"; cs.write_text("Фамилия;Фото\nА;x.png\nБ;x.png\n", encoding="utf-8")
bapi.import_rows(c, bapi.open_source(cs)[0], photo_dir=sd); shutil.rmtree(sd)
ps = bapi.list_persons(c); v = [p["fields"].get("pic") for p in ps]
chk("D39 путь в записи = photos/…, один файл на один исходник", all(str(x).startswith("photos/") for x in v) and v[0] == v[1] and len(list((pd / "photos").iterdir())) == 1, v)
fa = pd / v[0]
chk("D39 после удаления исходной папки фото открывается, байты = исходник", opens(c, ps[0], "pic") == (40, 50) and hashlib.sha256(fa.read_bytes()).hexdigest() == h_src, opens(c, ps[0], "pic"))
c.close()
# рендер в UI (превью карточки/формы) через BackendAPI.resolve_photo_path → QPixmap
from PyQt6.QtGui import QPixmap
a6 = BackendAPI(pd / "p.db", pd); rp = a6.resolve_photo_path(a6.list_persons()[0], "pic")
pmx = QPixmap(str(rp)) if rp else QPixmap()
chk("D39 после удаления исходника фото рендерится (QPixmap)", not pmx.isNull() and pmx.width() == 40, rp); a6.close()
# отмена
pd2 = TMP / "d39c"; pd2.mkdir(); c = bapi.connect(pd2 / "p.db"); bapi.upsert_field(c, "last_name", "Фамилия")
sd2 = TMP / "d39src2"; sd2.mkdir()
for i in range(3): Image.new("RGB", (10, 10), (i * 50, 0, 0)).save(sd2 / f"{i}.png")
cs2 = TMP / "d39c.csv"; cs2.write_text("Фамилия;Фото\n" + "".join(f"Ч{i};{i}.png\n" for i in range(3)), encoding="utf-8")
cnt = {"n": 0}
def cancel_after():
    cnt["n"] += 1; return cnt["n"] > 3
r = bapi.import_rows(c, bapi.open_source(cs2)[0], photo_dir=sd2, cancel=cancel_after)
left = list((pd2 / "photos").iterdir()) if (pd2 / "photos").exists() else []
chk("D39 отмена: cancelled, 0 записей, копии в photos/ удалены", r.cancelled and not bapi.list_persons(c) and left == [], f"cancelled={r.cancelled}; ticks={cnt['n']}; left={[f.name for f in left]}")
c.close()

# ---- Дубли (D38/D39): логика сохранения фото только в Backend ----
ui_copy = [f"{n}:{i+1}" for n, s in src_ui.items() for i, l in enumerate(s.splitlines()) if re.search(r"shutil\.copy|copyfile|write_bytes\(|\.save\(\s*os\.path\.join\([^)]*photos", l)]
chk("Дубли: в ui/ нет своего копирования фото (только BackendAPI.save_photo)", not ui_copy, ui_copy)
imp_src = pathlib.Path(_impm.__file__).read_text(encoding="utf-8")
other = [i + 1 for i, l in enumerate(imp_src.splitlines()) if re.search(r"save_photo\(|shutil\.copy|copyfile|write_bytes\(", l)]
ps_src = inspect.getsource(_impm._PhotoStore); ps_lines = set(range(inspect.getsourcelines(_impm._PhotoStore)[1], inspect.getsourcelines(_impm._PhotoStore)[1] + len(ps_src.splitlines())))
chk("Дубли: в importer копирование/save_photo только внутри _PhotoStore", other and all(x in ps_lines for x in other), f"строки={other}")
_imp_rec = inspect.getsource(_impm.import_records)
chk("Дубли: import_records — единственная точка, все фото-поля через store.store", _imp_rec.count("_PhotoStore(") == 1 and "store.store(" in _imp_rec, "")

w.close(); n_ok = sum(r[1] for r in RES)
(ROOT / "reports/qa/e2e_stage13b_results.json").write_text(json.dumps(RES, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"ИТОГО: {n_ok}/{len(RES)} PASS; tmp={TMP}"); sys.exit(0 if n_ok == len(RES) else 1)
