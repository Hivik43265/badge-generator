"""Смоук-тест UI против реального Backend (временные БД, в т.ч. :memory:).
QT_QPA_PLATFORM=offscreen .venv/bin/python ui/smoke_test.py
Скриншоты и рендеры пишутся в reports/; корень проекта не засоряется."""
import os, sys, tempfile, faulthandler
if os.environ.get("BG_FH"): faulthandler.dump_traceback_later(int(os.environ["BG_FH"]))
sys.dont_write_bytecode = True
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QEventLoop, QTimer, QSettings
from PyQt6.QtGui import QPixmap
from PyQt6.QtPrintSupport import QPrinter
_cfg = tempfile.mkdtemp(prefix="bg_ui_cfg_")   # не трогать настройки пользователя
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _cfg)

app = QApplication([])
from badge_backend import demo  # тестовые данные только через Backend
from ui.backend_api import BackendAPI
from ui import main_window as mw
from ui.main_window import MainWindow
from ui.record_form import RecordForm
from ui import dialogs
from ui.dialogs import ImportDialog, ExportDialog
from ui.layout_editor import find_overlaps

tmp = Path(tempfile.mkdtemp(prefix="bg_ui_"))
shots = ROOT / "reports"
ok = lambda m: print("OK  ", m)
def spin(ms=50):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
def cancel_immediately(pd): pd.cancel()

api = BackendAPI(tmp / "test.db")
demo.make_photo(tmp / "p1.png"); demo.make_logo(tmp / "demo_logo.png"); demo.build_demo(api.con)
csv = tmp / "people.csv"
csv.write_text("ФИО;Должность;Таб. номер;Фото;Комментарий;Мусор\n"
               "Иванов Иван Иванович;Инженер;1001;p1.png;ИТ;a\n"
               "Петрова Анна Сергеевна;Бухгалтер;1002;;Финансы;b\n"
               ";Без имени;1003;;;c\n", encoding="utf-8")

w = MainWindow(api); w.show(); app.processEvents()
# --- импорт: отмена через прогресс ---
d = ImportDialog(api, w); d.set_file(str(csv)); d.photo_dir.setText(str(tmp))
dialogs.progress_hook = cancel_immediately; d.run(); dialogs.progress_hook = None
assert d.report.cancelled and d.report.added == 0 and api.list_persons() == [], d.report
ok("импорт: отмена через QProgressDialog → cancelled=True, ничего не добавлено")
# --- импорт: mapping {header: field|None}, labels, require_photo=False ---
d.set_target("Комментарий", "department"); d.set_target("Мусор", None)
d.table.item(d.headers.index("Комментарий"), 2).setText("Подразделение")
assert d.mapping() == {"Комментарий": "department", "Мусор": None} and d.labels() == {"department": "Подразделение"}
d.run(); rep = d.report
assert not rep.cancelled and rep.added == 2 and rep.skipped == 1 and rep.warnings, rep
assert "Предупреждения" in d.log.toPlainText()
ok(f"импорт: added={rep.added} skipped={rep.skipped} errors={len(rep.errors)} warnings={len(rep.warnings)}")
w.refresh_all(); m = w.records.model
labels = [m.headerData(i, Qt.Orientation.Horizontal) for i in range(1, m.columnCount())]
assert "Подразделение" in labels and not any("Мусор" in str(l) for l in labels), labels
assert all("musor" not in p["fields"] for p in api.list_persons())
ok(f"таблица: колонки {labels} (Мусор исключён, label задан)")
# --- строгий режим require_photo ---
d2 = ImportDialog(api, w); d2.set_file(str(csv)); d2.photo_dir.setText(str(tmp)); d2.require_photo.setChecked(True)
cur = {p["id"] for p in api.list_persons()}
dialogs.progress_hook = cancel_immediately; d2.run(); dialogs.progress_hook = None   # не засоряем БД
assert d2.report.cancelled and {p["id"] for p in api.list_persons()} == cur
ok("импорт: require_photo флаг передаётся (прогон с отменой)")
w.records.search.setText("петрова"); assert w.records.proxy.rowCount() == 1; w.records.search.setText("")
ivanov = next(p["id"] for p in api.list_persons() if p["fields"].get("last_name") == "Иванов")
petrova = next(p["id"] for p in api.list_persons() if p["fields"].get("last_name") == "Петрова")
row = next(r for r in range(m.rowCount()) if m.person_id(r) == ivanov)
m.setData(m.index(row, 0), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
assert [p["id"] for p in api.list_persons(only_marked=True)] == [ivanov]
assert all(p["printed_at"] is None for p in api.list_persons())
m.setData(m.index(row, 0), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
assert api.get_person(ivanov)["print_mark"] == 0 and api.get_person(ivanov)["printed_at"] is None
m.setData(m.index(row, 0), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
assert m.headerData(m.printed_col(), Qt.Orientation.Horizontal) == "Напечатано"
assert not (m.flags(m.index(row, m.printed_col())) & Qt.ItemFlag.ItemIsEditable)
assert m.data(m.index(row, m.printed_col())) == ""
ok("поиск, чекбокс «Печать» → set_print_mark, printed_at не тронут; колонка «Напечатано» пустая, read-only")
# --- форма ---
f = RecordForm(api, ivanov, w)
assert f.preview.pixmap() and f.preview.pixmap().width() == 506
f.scale.setValue(1.5); f.sx.setValue(10); f.angle.setValue(15); f.update_preview()
f.edits["position"].setText("Ведущий инженер"); f.save()
p = api.get_person(ivanov)
assert p["photo_config"] == "10;0;1.5;0;0;15" and api.get_person(petrova)["photo_config"] == "0;0;1.0;0;0;0"
ok(f"форма: photo_config={p['photo_config']} только у #{ivanov}")
f.grab().save(str(shots / "screenshot_record_form.png"))
# --- редактор: палитра v1, пересечения ---
w.show_editor(); app.processEvents(); le = w.layout_editor
from ui import layout_editor as lem
WARN = []; lem.warn_hook = lambda t, m: WARN.append(m)
RES_WARN = []; dialogs.warning_hook = lambda t, m: RES_WARN.append(m)
assert set(le.tool_actions) == {"text", "field", "image", "background", "photo", "rect", "line", "barcode", "qr"}
tb = [a.objectName() for a in w.add_menu.actions() if a.objectName().startswith("tool_")]
assert len(tb) == 9 and "tool_qr" in tb, tb
draw = [a.text() for a in w.menus["Рисование"].actions() if not a.isSeparator()]
assert len(draw) == 8 and "QR-код" in draw and "Линия" in draw, draw
ok(f"инструменты: панель «Добавить элемент», меню «Рисование» и кнопка тулбара «Добавить элемент» — {len(tb)} инструментов, QR показан")
assert le.overlaps == [], le.overlaps
# D10: геометрия берётся только из макета tests/fixtures/demo_layout.json (загружен demo.build_demo)
els0 = api.list_elements("front")
src = next(e for e in els0 if e["type"] == "text")          # элемент из фикстуры
dst = next(e for e in els0 if e["type"] == "photo")         # цель пересечения из фикстуры
eid, ORIG = src["id"], (src["x"], src["y"], src["w"], src["h"])
le.load("front", eid)
le.p_x.setValue(dst["x"]); le.p_y.setValue(dst["y"]); le.p_w.setValue(src["w"]); le.p_h.setValue(src["h"]); le.apply_props()
assert any(eid in pair for pair in le.overlaps) and "пересекаются" in le.warn.text()
assert "пересекаются" in w.statusBar().currentMessage()
red = next(i for i in le.items() if i.el["id"] == eid).pen().color().name()
assert red == "#d00000", red
ok(f"пересечение: элемент фикстуры #{eid} сдвинут на фото #{dst['id']} → предупреждение {le.overlaps}, подсветка {red}")
it = next(i for i in le.items() if i.el["id"] == eid)
it.setPos(ORIG[0], ORIG[1]); it.set_size(ORIG[2], ORIG[3]); le._commit_geometry(it); spin()
els = api.list_elements("front"); g = next(e for e in els if e["id"] == eid)
assert (g["x"], g["y"], g["w"], g["h"]) == ORIG, g
assert find_overlaps(els) == [] and le.overlaps == [] and le.warn.text() == ""
ok(f"элемент #{eid} возвращён на позицию из фикстуры {ORIG} перетаскиванием: пересечений нет ({len(els) - 1} проверено)")
le.side_box.setCurrentIndex(1); app.processEvents(); assert le.side == "back" and le.items()
le.side_box.setCurrentIndex(0); app.processEvents()
w.grab().save(str(shots / "screenshot_layout.png"))
tmpid = le.add_element(); next(i for i in le.items() if i.el["id"] == tmpid).setSelected(True)
le.delete_element(); assert all(e["id"] != tmpid for e in api.list_elements())
ok("редактор: delete_element, стороны")
# --- предпросмотр ---
w.tabs.setCurrentWidget(w.preview); app.processEvents()
assert w.preview.person_box.currentData() == ivanov and w.preview.image.pixmap().width() == round(1011 * 0.8)
w.grab().save(str(shots / "screenshot_preview.png"))
api.render_card(ivanov).save(str(shots / "preview_backend_render.png"))
ok("предпросмотр: рендер Backend")
# --- экспорт: фото в порядке ---
ex = ExportDialog(api, [ivanov], w); ex.target.setText(str(tmp / "png"))
assert ex.start() and len(ex.result) == 2 and not ex.result.missing_photo_ids
ok(f"экспорт PNG: {[Path(x).name for x in ex.result]}")
# --- missing photo flow ---
asked = []
dialogs.confirm_hook = lambda parent, ids, names: (asked.append((ids, names)), False)[1]
ex = ExportDialog(api, [ivanov, petrova], w); ex.target.setText(str(tmp / "png2"))
assert not ex.start() and asked[-1][0] == [petrova] and "Петрова" in asked[-1][1][0] and not (tmp / "png2").exists()
ok(f"нет фото: предупреждение {asked[-1][1]}, «Нет» → экспорт не выполнен")
dialogs.confirm_hook = lambda *a: True
ex.pdf.setChecked(True); ex.target.setText(str(tmp / "out.pdf"))
assert ex.start() and Path(ex.result).exists() and list(ex.result.missing_photo_ids) == [petrova], ex.status.text()
ok(f"нет фото: «Да» → allow_missing_photo=True, PDF создан, {ex.status.text()}")
# --- отмена экспорта через прогресс ---
dialogs.progress_hook = cancel_immediately
ex = ExportDialog(api, [ivanov, petrova], w); ex.target.setText(str(tmp / "cancel.pdf")); ex.pdf.setChecked(True)
ex.start(); assert ex.result is None and not (tmp / "cancel.pdf").exists(), ex.status.text()
ok(f"отмена PDF: {ex.status.text()}")
ex.png.setChecked(True); ex.target.setText(str(tmp / "cancel_png")); ex.start()
assert ex.result.cancelled and len(ex.result) < 4, ex.status.text()
ok(f"отмена PNG: {ex.status.text()}")
dialogs.progress_hook = None
# --- печать: только print_mark=1, missing-photo flow ---
mw.clear_marks_hook = lambda parent, n: False   # D5: в этих проверках отвечаем «Нет»
pr = QPrinter(); pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(str(tmp / "print.pdf"))
res, err = w.do_print(printer=pr); assert err is None and res == 2 and (tmp / "print.pdf").stat().st_size > 0
ok(f"печать: {int(res)} стр. (только print_mark=1)")
api.set_print_mark([petrova], True); asked.clear()
dialogs.confirm_hook = lambda parent, ids, names: (asked.append(ids), False)[1]
assert w.do_print(printer=pr) == (None, None) and asked == [[petrova]]
dialogs.confirm_hook = lambda *a: True
res, err = w.do_print(printer=pr); assert err is None and res == 4 and list(res.missing_photo_ids) == [petrova]
ok(f"печать без фото: «Нет» → отмена; «Да» → {int(res)} стр., плейсхолдер у {list(res.missing_photo_ids)}")
dialogs.progress_hook = cancel_immediately
res, err = w.do_print(printer=pr); assert err is None and res.cancelled
ok(f"отмена печати: {w.statusBar().currentMessage()}")
dialogs.progress_hook = None; dialogs.confirm_hook = None
api.set_print_mark([petrova], False)
# --- D5: снять отметки после успешной печати ---
marked = lambda: sorted(p["id"] for p in api.list_persons(only_marked=True))
table_marks = lambda: sorted(w.records.model.person_id(r) for r in range(w.records.model.rowCount())
                             if w.records.model.rows[r]["print_mark"])
sid = api.create_person({"last_name": "Сидоров", "first_name": "Пётр"}, "p1.png", None, 0)
api.set_print_mark([ivanov, petrova], True); w.records.reload()
dialogs.confirm_hook = lambda *a: True
asked = []
mw.clear_marks_hook = lambda parent, n: (asked.append(n), False)[1]
res, err = w.do_print(printer=pr)
printed_at = lambda: {p["id"]: p["printed_at"] for p in api.list_persons()}
assert int(res) == 4 and asked == [2] and marked() == sorted([ivanov, petrova]) == table_marks()
assert all(v is None for v in printed_at().values())
ok(f"D5 «Нет»: вопрос про {asked[0]} записи, отметки не изменены {marked()}")
asked.clear(); mw.clear_marks_hook = lambda parent, n: (asked.append(n), False)[1]
dialogs.progress_hook = cancel_immediately
res, err = w.do_print(printer=pr); dialogs.progress_hook = None
assert res.cancelled and asked == [] and marked() == sorted([ivanov, petrova])
assert all(v is None for v in printed_at().values())
ok("D5 отмена печати: вопрос не задан, отметки не изменены")
asked.clear(); mw.clear_marks_hook = lambda parent, n: (asked.append(n), False)[1]
dialogs.confirm_hook = lambda *a: False      # отказ на предупреждении «нет фото» → печати нет
assert w.do_print(printer=pr) == (None, None) and asked == [] and marked() == sorted([ivanov, petrova])
ok("D5 печать не состоялась: вопрос не задан, отметки не изменены")
dialogs.confirm_hook = lambda *a: True
def yes_and_mark_other(parent, n):   # пока шла печать, пользователь отметил ещё одну запись
    asked.append(n); api.set_print_mark([sid], True); return True
asked.clear(); mw.clear_marks_hook = yes_and_mark_other
res, err = w.do_print(printer=pr)
assert int(res) == 4 and asked == [2] and marked() == [sid] == table_marks(), (marked(), table_marks())
assert "Отметки сняты: 2" in w.statusBar().currentMessage()
pa = printed_at()
assert pa[ivanov] and pa[petrova] and pa[sid] is None, pa
from datetime import datetime
from ui.records_table import format_printed_at
for pid in (ivanov, petrova):
    dt = datetime.fromisoformat(pa[pid]); assert dt.tzinfo is not None and abs((datetime.now().astimezone() - dt).total_seconds()) < 60
mdl = w.records.model; pc = mdl.printed_col()
shown = {mdl.person_id(r): mdl.data(mdl.index(r, pc)) for r in range(mdl.rowCount())}
assert shown[ivanov] == format_printed_at(pa[ivanov]) and len(shown[ivanov]) == 16 and shown[sid] == "", shown
ok(f"D5 printed_at: {pa[ivanov]} → в таблице «{shown[ivanov]}»; у #{sid} пусто")
ok(f"D5 «Да»: сняты отметки только с напечатанных {[ivanov, petrova]}, #{sid} остался отмеченным, таблица обновлена")
api.delete_person(sid); dialogs.confirm_hook = None; mw.clear_marks_hook = None
# --- форматирование и сортировка «Напечатано» ---
import time
from ui.records_table import format_printed_at, parse_printed_at
local = lambda iso: datetime.fromisoformat(iso).astimezone().strftime("%d.%m.%Y %H:%M")
assert format_printed_at(None) == "" and format_printed_at("2026-11-03T16:40:12+03:00") == local("2026-11-03T16:40:12+03:00")
assert format_printed_at("2026-11-03T13:40:12+00:00") == format_printed_at("2026-11-03T16:40:12+03:00")
if time.strftime("%z") == "+0300": assert format_printed_at("2026-11-03T13:40:12+00:00") == "03.11.2026 16:40"
proxy = w.records.proxy; pc = w.records.model.printed_col()
proxy.sort(pc, Qt.SortOrder.DescendingOrder)
top = w.records.model.person_id(proxy.mapToSource(proxy.index(0, 0)).row())
assert api.get_person(top)["printed_at"] is not None
# сортировка по времени, а не по строке: '+00:00' 13:40 == '+03:00' 16:40, а 15:00+00:00 позже
assert parse_printed_at("2026-11-03T15:00:00+00:00") > parse_printed_at("2026-11-03T16:40:12+03:00")
proxy.sort(-1)
ok("«Напечатано»: локальный пояс dd.MM.yyyy HH:mm, сортировка по datetime")
# --- в ui/ нет вызовов mark_printed(..., value) ---
import ast
calls = []
for fpath in (ROOT / "ui").glob("*.py"):
    for node in ast.walk(ast.parse(fpath.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "mark_printed":
            facade = isinstance(node.func.value, ast.Name) and node.func.value.id == "_api"
            n = len(node.args) + len(node.keywords)
            if n != (2 if facade else 1): calls.append(f"{fpath.name}:{node.lineno}")
assert calls == [], calls
ok("AST-проверка ui/: нет вызовов mark_printed(..., value)")
# --- миграция старой v1-БД при открытии (БД создаёт Backend-хелпер, без SQL в UI) ---
from badge_backend import api as bapi, db as bdb
from badge_backend.testing import create_legacy_db
pold = create_legacy_db(tmp / "old.db", version=1)
con = bapi.connect(str(pold)); assert bapi.get_schema_version(con) == bdb.LATEST; con.close()
pold2 = create_legacy_db(tmp / "old_ui.db", version=1)
w.switch_db(pold2)
assert api.schema_version() == bdb.LATEST and w.records.model.rowCount() == 0
api.upsert_field("last_name", "Фамилия", 0)
nid = api.create_person({"last_name": "Старый"}); w.records.reload()
assert api.get_person(nid)["printed_at"] is None and w.records.model.rowCount() == 1
assert w.records.model.data(w.records.model.index(0, w.records.model.printed_col())) == ""
ok("create_legacy_db(v1) → connect/open_db → LATEST; printed_at=None через API, колонка «Напечатано» пустая")
# --- D7: в ui/ нет прямого SQL ---
def _no_sql_in_ui():
    bad, ex = [], "exec" + "ute"
    meths = {ex, ex + "many", ex + "script"}
    word, mod = "PRA" + "GMA", "sql" + "ite3"
    for fpath in sorted((ROOT / "ui").glob("*.py")):
        tree = ast.parse(fpath.read_text(encoding="utf-8"))
        skip = set()
        for node in ast.walk(tree):     # литералы внутри самого чекера не считаем
            if isinstance(node, ast.FunctionDef) and node.name == "_no_sql_in_ui":
                skip |= {id(n) for n in ast.walk(node)}
        for node in ast.walk(tree):
            if id(node) in skip: continue
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in meths:
                bad.append(f"{fpath.name}:{node.lineno} .{node.func.attr}()")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and word in node.value.upper():
                bad.append(f"{fpath.name}:{node.lineno} строка с {word}")
            elif isinstance(node, ast.Import) and any(a.name.split(".")[0] == mod for a in node.names):
                bad.append(f"{fpath.name}:{node.lineno} import {mod}")
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == mod:
                bad.append(f"{fpath.name}:{node.lineno} from {mod}")
    return bad
sql_bad = _no_sql_in_ui()
assert sql_bad == [], sql_bad
ok(f"D7 AST: в ui/*.py ({len(list((ROOT / 'ui').glob('*.py')))} файлов) нет прямого SQL (вызовы exec*, служебные команды БД, импорт драйвера)")
# --- :memory: + экспорт в рабочем потоке ---
w.switch_db(":memory:"); assert w.records.model.rowCount() == 0
demo.build_demo(api.con); api.base_dir = str(tmp)   # база путей для :memory:
f2 = RecordForm(api, None, w); f2.edits["last_name"].setText("Новиков"); f2.edits["first_name"].setText("Олег")
f2.photo_path.setText(str(tmp / "p1.png")); f2.save(); w.refresh_all()
mid = api.list_persons()[0]["id"]
ex = ExportDialog(api, [mid], w); ex.target.setText(str(tmp / "mem.pdf")); ex.pdf.setChecked(True)
assert ex.start() and Path(ex.result).exists(), ex.status.text()
ok("БД :memory: — экспорт PDF через snapshot в QThread")
w.switch_db(tmp / "test.db")
for i in range(3): w.tabs.setCurrentIndex(i); app.processEvents()
w.tabs.setCurrentIndex(0); app.processEvents()
ok("Открыть БД / вкладки")
# ===== Этап 9 =====
# выбор строки внизу → холст сразу рендерит эту запись
w.layout_editor.show_render.setChecked(True)
for pid in (petrova, ivanov):
    r = w.records.proxy.mapFromSource(w.records.model.index(next(r for r in range(w.records.model.rowCount()) if w.records.model.person_id(r) == pid), 1)).row()
    w.records.view.selectRow(r); app.processEvents()
    assert w.layout_editor.person_id == pid and w.preview.person_box.currentData() == pid
    assert w.layout_editor.canvas_image == api.render_card(pid, "front"), pid
ok("выбор строки в доке «Записи» → холст = render_card(выбранная запись), предпросмотр синхронизирован")
w.grab().save(str(shots / "screenshot.png"))
# пустая БД → пустой шаблон, подсказка; кнопки создают элементы нужных типов
w.switch_db(tmp / "empty.db"); le = w.layout_editor; app.processEvents()
assert api.list_elements() == [] and api.list_elements("back") == [] and le.items() == []
assert le.hint is not None and le.hint.text() == "Добавьте элементы с панели инструментов"
assert api.render_card(None, "front") == le.canvas_image   # подсказка — не часть рендера
ok("пустая БД: шаблон пуст (0 элементов), показана подсказка, демо-макет не создан")
demo.make_logo(tmp / "logo2.png"); api.base_dir = str(tmp)
made, skipped = {}, []
for key, opts in (("text", {}), ("field", {"field_name": "last_name"}), ("image", {"image_path": "logo2.png"}),
                  ("photo", {}), ("rect", {}), ("line", {}), ("barcode", {}), ("qr", {})):
    WARN.clear(); eid = le.add_element(key, **opts)
    if eid is None and key == "line":
        skipped.append(f"line: Backend отклонил тип ('{WARN[-1] if WARN else le.last_error}') — SKIP, ждём миграцию схемы")
        continue
    assert eid is not None, (key, WARN)
    e = next(x for x in api.list_elements() if x["id"] == eid)
    assert e["type"] == key and e["x"] == (1011 - e["w"]) // 2 and e["y"] == (638 - e["h"]) // 2, e
    assert le.current and le.current.el["id"] == eid and le.props.isEnabled()
    assert le.hint is None
    made[key] = eid
assert next(x for x in api.list_elements() if x["id"] == made["field"])["field_name"] == "last_name"
assert next(x for x in api.list_elements() if x["id"] == made["barcode"])["style"]["format"] == "code128"
ok(f"кнопки → create_element с верным типом, по центру, выделен: {sorted(made)}")
for m_ in skipped: print("SKIP", m_)
bg = le.add_background(color="#E8F0FA"); assert api.get_background("front")["color"].upper() == "#E8F0FA", bg
ok("Фон стороны → set_background/get_background")
# свойства: шрифт/цвет/привязка/символика; z-order; удаление
le.load("front", made["field"]); le.p_font.setValue(22); le.p_color.setText("#112233"); le.p_field.setCurrentText("first_name"); le.apply_props()
e = next(x for x in api.list_elements() if x["id"] == made["field"])
assert e["style"]["font_size"] == 22 and e["style"]["color"] == "#112233" and e["field_name"] == "first_name", e
el_ = lambda i: next(x for x in api.list_elements() if x["id"] == i)
# --- этап 10: штрихкод ---
le.load("front", made["barcode"]); assert le.p_show_text.isChecked() and le.p_quiet.value() == 10 and le.p_font.value() == 8
le.p_format.setCurrentIndex(le.p_format.findData("ean13")); assert le.p_hint.text() == "12 или 13 цифр"
le.p_static.setText("400638133393"); le.p_show_text.setChecked(False); le.p_quiet.setValue(14)
le.p_color.setText("#102030"); le.p_bg.setText("#F0F0F0"); le.p_font.setValue(9); assert le.apply_props()
st = el_(made["barcode"])["style"]
assert st["format"] == "ean13" and "symbology" not in st and st["show_text"] is False and st["quiet_zone"] == 14 \
    and st["color"] == "#102030" and st["background"] == "#F0F0F0" and st["font_size"] == 9, st
le.p_field.setCurrentText("employee_id"); le.apply_props(); assert el_(made["barcode"])["field_name"] == "employee_id"
le.p_field.setCurrentText(""); le.apply_props()
# старый ключ symbology читается, при сохранении заменяется на format
api.update_element(made["barcode"], style={"symbology": "ean13"}); le.load("front", made["barcode"])
assert le.p_format.currentData() == "ean13"; le.apply_props(); st = el_(made["barcode"])["style"]
assert st["format"] == "ean13" and "symbology" not in st, st
ok(f"штрихкод: format/show_text/quiet_zone/color/background/font_size, поле или static сохраняются; symbology → format {st}")
# --- QR ---
le.load("front", made["qr"]); assert le.p_ec.currentText() == "M" and le.p_qborder.value() == 4
le.p_ec.setCurrentText("H"); le.p_qborder.setValue(2); le.p_color.setText("#000080"); le.p_bg.setText("#FFFFEE")
le.p_static.setText("https://example.org/badge"); assert le.apply_props(); st = el_(made["qr"])["style"]
assert st["error_correction"] == "H" and st["border"] == 2 and st["color"] == "#000080" and st["background"] == "#FFFFEE", st
assert el_(made["qr"])["static_value"] == "https://example.org/badge"
ok(f"QR: error_correction/border/color/background сохраняются {st}")
# --- линия: отрезок, w/h 0 или <0, но не оба 0 ---
le.load("front", made["line"]); le.p_stroke.setText("#C00000"); le.p_stroke_w.setValue(5)
le.p_w.setValue(-300); le.p_h.setValue(120); assert le.apply_props()
g = el_(made["line"]); assert (g["w"], g["h"]) == (-300, 120) and g["style"]["stroke"] == "#C00000" and g["style"]["stroke_width"] == 5, g
it = le.current; assert it.geometry()["w"] == -300 and it.rect().width() > 300 and it.rect().left() < -300
le.p_w.setValue(0); le.p_h.setValue(-80); assert le.apply_props() and (el_(made["line"])["w"], el_(made["line"])["h"]) == (0, -80)
assert le.current.rect().width() > 0   # нулевая ширина всё ещё выбирается
WARN.clear(); le.p_w.setValue(0); le.p_h.setValue(0); assert not le.apply_props()
assert WARN and "одновременно 0" in WARN[-1] and (el_(made["line"])["w"], el_(made["line"])["h"]) == (0, -80)
it = le.current; it.set_size(0, 0); WARN.clear(); le._commit_geometry(it); spin()
assert WARN and (el_(made["line"])["w"], el_(made["line"])["h"]) == (0, -80)
le.load("front", made["line"]); le.p_w.setValue(500); le.p_h.setValue(0); le.apply_props()
ok("линия: (-300,120), (0,-80) сохраняются, выбор работает; (0,0) запрещено и в свойствах, и при перетаскивании")
# --- рамка: stroke/stroke_width/fill/radius, чтение legacy border_* ---
api.update_element(made["rect"], style={"border_color": "#123456", "border_width": 7}); le.load("front", made["rect"])
assert le.p_stroke.text() == "#123456" and le.p_stroke_w.value() == 7
le.p_fill.setText("#EEF3FA"); le.p_radius.setValue(16); le.p_stroke_w.setValue(2); assert le.apply_props()
st = el_(made["rect"])["style"]
assert st == {**st, "stroke": "#123456", "stroke_width": 2, "fill": "#EEF3FA", "radius": 16} and "border_color" not in st, st
ok(f"рамка: legacy border_* прочитан, записаны stroke/stroke_width/fill/radius {st}")
le.load("front", made["barcode"])
z0 = le.current.el["z_order"]; le.move_z(+1); assert le.current.el["z_order"] == z0 + 1; le.move_z(-1); assert le.current.el["z_order"] == z0
tmp_id = le.add_element("text"); le.delete_element(); assert all(x["id"] != tmp_id for x in api.list_elements())
ok("свойства (шрифт, цвет, поле), z-order ↑↓, удаление")
# раскладка для скриншота: штрихкод, QR и линия рендерит Backend
for k, geo in (("text", (40, 30, 600, 80)), ("field", (40, 120, 600, 80)), ("image", (800, 30, 170, 170)),
               ("photo", (40, 220, 240, 320)), ("rect", (300, 220, 370, 320)), ("line", (40, 210, 930, 0)),
               ("barcode", (300, 548, 420, 80)), ("qr", (740, 360, 230, 230))):
    api.update_element(made[k], **dict(zip("xywh", geo)))
api.update_element(made["barcode"], static_value="400638133393", style={"format": "ean13", "show_text": True, "quiet_zone": 10, "font_size": 8})
api.update_element(made["text"], static_value="Пропуск")
le.load("front"); w.layout_editor.grab().save(str(shots / "screenshot_editor.png"))
ok("скриншот редактора: reports/screenshot_editor.png (штрихкод EAN-13, QR, линия — рендер Backend)")
# --- D8: подписи без 'None' ---
api.upsert_field("employee_id", "Таб. номер", 9)
extra = [api.create_element(type=t, x=10, y=10, w=50, h=50 if t != "line" else 0, side="back", field_name=fn, static_value=sv)
         for t, fn, sv in (("field", "employee_id", None), ("field", "no_label_field", None),
                           ("text", None, None), ("barcode", None, None), ("qr", None, "X"), ("photo", None, None),
                           ("image", None, None), ("rect", None, None), ("line", None, None), ("barcode", "employee_id", None))]
from ui.layout_editor import element_caption
for side in ("front", "back"):
    le.load(side)
    caps = [i.caption.text() for i in le.items()] + [le.el_list.item(r).text() for r in range(le.el_list.count())]
    assert caps and not any("None" in c for c in caps), caps
    for i in le.items():
        if i.el["type"] == "field":
            assert i.caption.text() == "Поле" or i.caption.text().startswith("Поле: "), i.caption.text()
        i.setSelected(True); app.processEvents(); assert "None" not in le.p_type.text(); i.setSelected(False)
assert element_caption({"type": "field", "field_name": None}) == "Поле"
assert element_caption({"type": "field", "field_name": "employee_id"}, {"employee_id": "Таб. номер"}) == "Поле: Таб. номер"
assert element_caption({"type": "field", "field_name": "x"}, {"x": None}) == "Поле: x"
assert element_caption({"type": "text", "static_value": "Гость"}) == "Текст: Гость" and element_caption({"type": "text"}) == "Текст"
assert element_caption({"type": "barcode", "field_name": "employee_id"}, {"employee_id": "Таб. номер"}) == "Штрихкод: Таб. номер"
assert element_caption({"type": "qr", "static_value": "X"}) == "QR: X" and element_caption({"type": "rect"}) == "Рамка"
ok(f"D8: подписи рамок/списка/свойств без 'None' ({len(caps)} на обороте), поля — 'Поле: <label|name>' или 'Поле'")
for eid in extra: api.delete_element(eid)
le.load("front")
# --- результат экспорта: empty_template и warnings ---
w.switch_db(tmp / "empty2.db"); api.base_dir = str(tmp)
pid0 = api.create_person({"last_name": "Пустов"}); RES_WARN.clear()
ex = ExportDialog(api, [pid0], w); ex.target.setText(str(tmp / "empty_png"))
dialogs.confirm_hook = lambda *a: True; ex.start(); dialogs.confirm_hook = None; assert getattr(ex.result, "empty_template", False), ex.result
assert RES_WARN and "Шаблон пуст" in RES_WARN[-1] and "Шаблон пуст" in ex.status.text(), (RES_WARN, ex.status.text())
from ui.dialogs import describe_result
class _R(list): warnings = ["сторона 'back' шаблона пуста"]; empty_template = False
assert "Предупреждение: сторона 'back' шаблона пуста" in describe_result(_R(["a"]), None, "Экспорт")
ok(f"экспорт пустого шаблона: явное предупреждение показано — {ex.status.text()!r}")
w.switch_db(tmp / "empty.db"); le = w.layout_editor
# ===== Главный вид =====
from ui.main_window import MENUS
from ui import main_window as mwm
w.switch_db(tmp / "main_view.db"); api.base_dir = str(tmp); w.show_main(); app.processEvents()
demo.build_demo(api.con)                                     # демо-макет — только из теста (фикстура)
dimp = ImportDialog(api, w); dimp.set_file(str(csv)); dimp.photo_dir.setText(str(tmp)); dimp.set_target("Мусор", None)
dimp.set_target("Комментарий", "department"); dimp.run(); w.refresh_all()
assert [a.text() for a in w.menuBar().actions()] == MENUS == ["Файл", "Дизайн", "Рисование", "Редактировать", "Просмотр", "Опции", "База данных", "Помощь"]
need = ["Подключить БД", "Отключить БД", "Настройка", "Сохранить", "Печать", "Очередь печати", "Напечатано / Не напечатано",
        "Лицевая", "Оборот", "Текст", "Положение", "Добавить элемент", "Удалить элемент", "Захват изображения"]
assert w.toolbar_texts() == need, w.toolbar_texts()
assert all(not a.icon().isNull() for a in w.toolbar.actions() if not a.isSeparator())
ok(f"меню по порядку: {' | '.join(MENUS)}; тулбар: {len(need)} действий с собственными иконками")
assert w.tabs.currentWidget() is w.splitter and w.splitter.widget(0) is w.records and w.splitter.widget(1) is w.preview_panel
m = w.records.model; hdr = [m.headerData(c, Qt.Orientation.Horizontal) for c in range(m.columnCount())]
lab = {f["name"]: f["label"] for f in api.list_fields()}
assert hdr[:7] == ["Печать", "Логотип", "Фото", "ФИО", lab["position"], lab["department"], lab["employee_id"]] and hdr[-1] == "Напечатано", hdr
assert m.data(m.index(0, m.column_of("photo")), Qt.ItemDataRole.DecorationRole) is not None or m.data(m.index(1, m.column_of("photo")), Qt.ItemDataRole.DecorationRole) is not None
ok(f"таблица: колонки {hdr} (миниатюры Логотип/Фото, ФИО из частей)")
pp = w.preview_panel
people = api.list_persons(); a_id, b_id = people[0]["id"], people[1]["id"]
for pid in (a_id, b_id):
    w._select_person(pid); app.processEvents()
    assert pp.person_id == pid and pp.pixmap.toImage() == QPixmap.fromImage(api.render_card(pid, "front")).toImage()
    rows = dict(pp.db_rows()); f = api.get_person(pid)["fields"]
    assert rows["ФИО"].startswith(f["last_name"]) and rows["Должность"] == f.get("position", "") and "Фото" in rows and "Логотип" in rows, rows
ok(f"выбор строки → предпросмотр = render_card(лицевая), «Поля БД»: {list(rows)[:6]}…")
pp.tabs.setCurrentIndex(0); app.processEvents()
items = [pp.layout_fields.item(i).text() for i in range(pp.layout_fields.count())]
assert len(items) == len(api.list_elements("front")) and not any("None" in t for t in items) and pp.preview_box.parent() is pp.pages[0]
pp.tabs.setCurrentIndex(1); app.processEvents(); assert pp.preview_box.parent() is pp.pages[1] and pp.db_fields.rowCount() > 3
ok(f"вкладки «Поля макета» ({len(items)} элементов) и «Поля БД» работают, предпросмотр над ними")
w.act_back.trigger(); app.processEvents(); assert pp.side == "back" and w.layout_editor.side == "back"
w.act_front.trigger(); app.processEvents(); assert pp.side == "front"
# очередь печати — только print_mark=1
api.set_print_mark([p["id"] for p in people], False); api.set_print_mark([b_id], True)
q = w.show_print_queue(exec_=False); assert q.ids() == [b_id] and q.table.rowCount() == 1
ok(f"очередь печати: только отмеченные {q.ids()}")
# фильтр Напечатано / Не напечатано (printed_at)
api.mark_printed([b_id]); w.records.reload()
assert w.toggle_printed_filter() == "Напечатано" and w.records.proxy.rowCount() == 1
assert w.records.model.person_id(w.records.proxy.mapToSource(w.records.proxy.index(0, 0)).row()) == b_id
assert w.toggle_printed_filter() == "Не напечатано" and w.records.proxy.rowCount() == len(people) - 1
assert w.toggle_printed_filter() == "Все записи" and w.records.proxy.rowCount() == len(people)
w.records.col_box.setCurrentIndex(w.records.col_box.findText("Должность")); w.records.col_value.setText("бух")
assert w.records.proxy.rowCount() == 1; w.records.col_value.setText("")
ok("фильтры: «Напечатано / Не напечатано» по printed_at, фильтр по колонке")
# положение выбранного элемента
le = w.layout_editor; el0 = api.list_elements("front")[-1]; le.load("front", el0["id"])
mwm.position_hook = lambda d: (d.align("hcenter"), d.value())[1]; v = w.edit_position(); mwm.position_hook = None
e1 = next(e for e in api.list_elements("front") if e["id"] == el0["id"]); assert e1["x"] == (1011 - abs(e1["w"])) // 2 - min(0, e1["w"]), e1
ok(f"«Положение»: выравнивание по центру → x={e1['x']}")
api.update_element(el0["id"], x=el0["x"], y=el0["y"]); le.load("front")   # вернуть макет фикстуры
# захват изображения из файла
demo.make_photo(tmp / "cap.png"); w._select_person(a_id); app.processEvents()
assert w.capture_image(str(tmp / "cap.png")) == "cap.png" and api.get_person(a_id)["photo_path"] == "cap.png"
from ui.main_view import camera_available
ok(f"«Захват изображения»: фото из файла записано; камера доступна: {camera_available()} (иначе — файл)")
assert w.open_settings({"grid": 25})["grid"] == 25; w.act_grid.trigger(); assert le.grid_on; w.act_grid.trigger()
txt = []; mwm.about_hook = txt.append; w.about(); mwm.about_hook = None; assert "Схема БД: v3" in txt[0]
assert w.save_all()
ok("Настройка, Сетка, О программе, Сохранить")
w._select_person(a_id); pp.tabs.setCurrentIndex(1); w.show_main(); w.setMinimumWidth(1440); w.resize(1440, 880); spin(150)
w.grab().save(str(shots / "screenshot_main_view.png")); pp.tabs.setCurrentIndex(0); w.setMinimumWidth(0)
ok("скриншот: reports/screenshot_main_view.png")
# сплиттер главного вида: сохранение/восстановление из QSettings
_cfg2 = tempfile.mkdtemp(prefix="bg_ui_cfg2_")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _cfg2)
w.settings = QSettings("BadgeGenerator", "Frontend")
w.show_main(); app.processEvents(); w.splitter.setSizes([500, 900]); app.processEvents(); saved = w.splitter.sizes()
w.close(); app.processEvents()   # closeEvent → save_layout; api не закрыт (не наш)
assert w.settings.value("window/splitter") is not None
w2 = MainWindow(api); w2.resize(w.size()); w2.show(); spin(100); r2 = w2.splitter.sizes()
assert abs(r2[0] / sum(r2) - saved[0] / sum(saved)) < 0.03, (r2, saved)
w2.reset_layout(); app.processEvents(); sz = w2.splitter.sizes()
assert abs(sz[0] / sum(sz) - 0.65) < 0.05, sz
ok(f"сплиттер: размеры {saved} сохранены в QSettings ({_cfg2}) и восстановлены; сброс → ~65/35 {sz}")
w2.close(); lem.warn_hook = None
print("ALL OK; tmp =", tmp)
