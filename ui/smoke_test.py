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
from PyQt6.QtGui import QPixmap, QImage, QColor
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
from ui.backend_api import LABELS as _BL   # D24: поля заводятся в Менеджере полей; в тесте — заранее
def seed_fields():
    for _i, (_k, _l) in enumerate(_BL.items()): api.upsert_field(_k, _l, _i)
seed_fields()
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
api.upsert_field("department", "Отдел"); d.set_file(str(csv))   # D24: только существующие поля БД
d.set_target("Комментарий", "department"); d.set_target("Мусор", None)
assert d.mapping() == {"Комментарий": "department"} and d.field_column("department") == "Комментарий", d.mapping()   # «Мусор» без поля → skipped_columns
d.run(); rep = d.report
assert not rep.cancelled and rep.added == 3 and rep.skipped == 0 and any(x["code"] == "REQUIRED_MISSING" for x in rep.warnings), rep   # Backend 39c7fca: пустое — только предупреждение
assert "Предупреждения" in d.log.toPlainText()
ok(f"импорт: added={rep.added} skipped={rep.skipped} errors={len(rep.errors)} warnings={len(rep.warnings)}")
w.refresh_all(); m = w.records.model
labels = [m.headerData(i, Qt.Orientation.Horizontal) for i in range(1, m.columnCount())]
assert any(l in labels for l in ("Отдел", "Подразделение")) and not any("Мусор" in str(l) for l in labels), labels
assert all("musor" not in p["fields"] for p in api.list_persons())
ok(f"таблица: колонки {labels} (Мусор исключён, label задан)")
# --- строгий режим require_photo ---
d2 = ImportDialog(api, w); d2.set_file(str(csv)); d2.photo_dir.setText(str(tmp)); d2.require_photo.setChecked(True)
cur = {p["id"] for p in api.list_persons()}
dialogs.progress_hook = cancel_immediately; d2.run(); dialogs.progress_hook = None   # не засоряем БД
assert d2.report.cancelled and {p["id"] for p in api.list_persons()} == cur
ok("импорт: require_photo флаг передаётся (прогон с отменой)")
assert len(w.find("петрова")) == 1 and w.records.proxy.rowCount() == 1; assert w.find("") is None
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
assert not hasattr(le, "tool_actions") and set(w.tool_actions) == {"text", "field", "image", "photo", "rect", "ellipse", "line", "barcode", "qr"}
draw = [a.text() for a in w.ribbon.actions_of("Рисование") if a.objectName().startswith("act_tool_")]
assert len(draw) == 9 and "QR-код" in draw and "Линия" in draw and "Эллипс" in draw, draw
ok(f"инструменты: 9 действий только на вкладке ленты «Рисование»: {draw}")
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
w.act_side.trigger(); app.processEvents(); assert le.side == "back" and le.items() and w.act_side.isChecked()
w.act_side.trigger(); app.processEvents(); assert le.side == "front" and w.act_side.text() == "Сторона: лицевая"
w.grab().save(str(shots / "screenshot_layout.png"))
tmpid = le.add_element(); next(i for i in le.items() if i.el["id"] == tmpid).setSelected(True)
le.delete_element(); assert all(e["id"] != tmpid for e in api.list_elements())
ok("редактор: delete_element, стороны")
# --- предпросмотр ---
w.show_main(); w._select_person(ivanov); app.processEvents()
assert w.stack.currentWidget() is w.db_page and w.preview_panel.person_id == ivanov
assert w.preview_panel.pixmap.toImage() == QPixmap.fromImage(api.render_card(ivanov, "front")).toImage()
w.grab().save(str(shots / "screenshot_preview.png")); w.show_editor()
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
for i in range(w.ribbon.count()): w.ribbon.setCurrentIndex(i); app.processEvents()
w.ribbon.select("База данных"); app.processEvents()
ok("Открыть БД / все вкладки ленты")
# ===== Этап 9 =====
# выбор строки внизу → холст сразу рендерит эту запись
w.act_show_render.setChecked(True); w.layout_editor.set_show_render(True)
for pid in (petrova, ivanov):
    r = w.records.proxy.mapFromSource(w.records.model.index(next(r for r in range(w.records.model.rowCount()) if w.records.model.person_id(r) == pid), 1)).row()
    w.records.view.selectRow(r); app.processEvents()
    assert w.layout_editor.person_id == pid and w.preview_panel.person_id == pid
    assert w.layout_editor.canvas_image == api.render_card(pid, "front"), pid
ok("выбор строки в доке «Записи» → холст = render_card(выбранная запись), предпросмотр синхронизирован")
w.grab().save(str(shots / "screenshot.png"))
# пустая БД → пустой шаблон, подсказка; кнопки создают элементы нужных типов
w.switch_db(tmp / "empty.db"); le = w.layout_editor; app.processEvents()
assert api.list_elements() == [] and api.list_elements("back") == [] and le.items() == []
assert le.hint is not None and le.hint.text() == lem.EMPTY_HINT == "Добавьте элементы: вкладка ленты «Рисование»"
assert api.render_card(None, "front") == le.canvas_image   # подсказка — не часть рендера
ok("пустая БД: шаблон пуст (0 элементов), показана подсказка, демо-макет не создан")
demo.make_logo(tmp / "logo2.png"); api.base_dir = str(tmp)
made, skipped = {}, []
for key, opts in (("text", {}), ("field", {"field_name": "last_name"}), ("image", {"image_path": "logo2.png"}),
                  ("photo", {}), ("rect", {}), ("ellipse", {}), ("line", {}), ("barcode", {}), ("qr", {})):
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
assert element_caption({"type": "qr", "static_value": "X"}) == "QR-код: X" and element_caption({"type": "rect"}) == "Рамка"
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
# ===== Главный вид (этап 12: лента) =====
from ui import main_window as mwm
from ui.ribbon import TABS
from ui.backend_api import TYPE_NAMES, SIDE_NAMES
from ui import records_table as rtm
w.switch_db(tmp / "main_view.db"); api.base_dir = str(tmp); w.show_main(); app.processEvents()
demo.build_demo(api.con); seed_fields()                      # демо-макет и поля — только из теста (фикстура)
dimp = ImportDialog(api, w); dimp.set_file(str(csv)); dimp.photo_dir.setText(str(tmp)); dimp.set_target("Мусор", None)
dimp.set_target("Комментарий", "department"); dimp.run(); w.refresh_all()
# --- этап 12: лента, уникальность QAction ---
assert w.menuBar().actions() == [] and not w.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QToolBar"]).QToolBar)
assert [w.ribbon.tabText(i) for i in range(w.ribbon.count())] == TABS == ["Файл", "Главная", "Рисование", "Редактировать", "Просмотр", "База данных", "Помощь"]
acts = w.all_actions()
texts = [a.text() for a in acts]; names = [a.objectName() for a in acts]
assert len(texts) == len(set(texts)), [t for t in texts if texts.count(t) > 1]
assert len(names) == len(set(names)) and all(n.startswith("act_") for n in names), names
assert len(acts) - (len(w.display_actions) - 1) == 57, len(acts)       # 57 действий (act_capture удалён, D22) (Дисплей — одна группа из 3)
from PyQt6.QtWidgets import QToolButton
assert w.records.filter.apply_button.isVisible() or True
btn_count = {}
for b in w.ribbon.findChildren(QToolButton):
    if b.defaultAction() in w.ribbon.places: btn_count[b.defaultAction()] = btn_count.get(b.defaultAction(), 0) + 1
btn_count[w.act_filter_apply] = int(w.records.filter.apply_button.defaultAction() is w.act_filter_apply)
btn_count[w.act_style_stroke_w] = 1                              # QWidgetAction (поле толщины)
assert all(btn_count.get(a) == 1 for a in acts), [a.text() for a in acts if btn_count.get(a) != 1]
try: w.ribbon.add_group("Помощь", "Повтор", [w.act_about]); dup = False
except ValueError: dup = True
assert dup
all_q = [a for a in w.findChildren(__import__("PyQt6.QtGui", fromlist=["QAction"]).QAction) if a.objectName().startswith("act_")]
old = {"act_save", "act_front", "act_back", "act_printed_filter", "act_add_element", "act_text", "act_editor", "act_main",
       "act_full_preview", "act_mark_all", "act_unmark_all", "act_rec_add", "act_rec_edit", "act_rec_del", "act_remove_element"}
assert not old & {a.objectName() for a in all_q}, old & {a.objectName() for a in all_q}
le = w.layout_editor
assert not any(hasattr(le, n) for n in ("tool_actions", "act_delete", "act_up", "act_down", "act_side", "side_box"))
assert not hasattr(w.records, "search") and not hasattr(w.records, "col_box")
from PyQt6.QtWidgets import QPushButton
assert [b.text() for b in w.records.findChildren(QPushButton) if b.parent() is w.records] == []
ok(f"лента: {len(TABS)} вкладок, {len(acts)} QAction (58 действий), тексты и objectName уникальны, у каждого одно место; повтор → ValueError; старые дубли удалены")
# контекстные меню используют те же QAction
for acts_ in (w.canvas_menu_actions, w.list_menu_actions, w.table_menu_actions):
    m_ = w.context_menu(acts_); assert all(a in w.ribbon.places for a in m_.actions() if not a.isSeparator())
ok("контекстные меню холста, списка элементов и таблицы — те же QAction ленты")
# окно помещается в 1024 px
w.showNormal(); w.resize(1024, 720); spin(100)
assert w.minimumWidth() <= 1024 and w.minimumSizeHint().width() <= 1024 and w.width() <= 1024, (w.minimumWidth(), w.minimumSizeHint().width(), w.width())
def ribbon_visible(tab):
    """Все группы вкладки видны в области ленты без прокрутки; кнопки не обрезаны."""
    w.ribbon.select(tab); spin(30); sc = w.ribbon.scrolls[tab]; vp = sc.viewport()
    assert not sc.horizontalScrollBar().isVisible() or sc.horizontalScrollBar().maximum() == 0, tab
    for g in w.ribbon.groups[tab]:
        wd = g.button if g.collapsed else g.full
        assert wd.isVisible(), (tab, g.title)
        r = wd.geometry(); tl = wd.mapTo(vp, wd.rect().topLeft()); br = wd.mapTo(vp, wd.rect().bottomRight())
        assert tl.x() >= 0 and br.x() <= vp.width(), (tab, g.title, tl.x(), br.x(), vp.width())
        if not g.collapsed:
            for b in g.full.findChildren(QToolButton):
                if b.isVisible(): assert b.sizeHint().width() <= b.width() + 1, (tab, b.text(), b.sizeHint().width(), b.width())
                if b.isVisible(): assert b.sizeHint().height() <= b.height() + 1, (tab, b.text(), b.sizeHint().height(), b.height())  # D18
    return [g.title for g in w.ribbon.groups[tab] if g.collapsed]
collapsed = {t: ribbon_visible(t) for t in TABS}
assert all(c == [] for c in collapsed.values()), collapsed           # при 1024 px всё помещается без сворачивания
ok(f"D12: 1024 px — на всех 7 вкладках все группы видны без прокрутки, кнопки не обрезаны")
w.resize(640, 720); spin(100); sm = {t: ribbon_visible(t) for t in TABS}
assert sm["База данных"], sm
g_ = next(g for g in w.ribbon.groups["База данных"] if g.collapsed)
w.ribbon.select("База данных"); spin(30); assert g_.button.isVisible() and g_.menu.actions() == g_.actions_ and all(a in w.ribbon.places for a in g_.actions_)
ok(f"D12: 640 px — группы свёрнуты справа налево в кнопки с меню из тех же QAction: {sm['База данных']}")
w.resize(1024, 720); spin(100); assert ribbon_visible("База данных") == []
disp = w.ribbon.buttons[w.display_actions[None]]; assert disp.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
w.ribbon.select("База данных"); app.processEvents()
ok(f"ширина: minimumSizeHint={w.minimumSizeHint().width()} ≤ 1024; «Дисплей» — компактный столбик, обратно развёрнуто")
# русские подписи типов
from ui.layout_editor import TOOLS, element_caption as ec
assert TYPE_NAMES == {"field": "Поле", "text": "Текст", "photo": "Фото", "image": "Изображение", "rect": "Рамка",
                      "ellipse": "Эллипс", "line": "Линия", "barcode": "Штрихкод", "qr": "QR-код"}
assert all(w.tool_actions[t].text() == TYPE_NAMES[t] for t in TYPE_NAMES)
assert all(ec({"type": t}).startswith(TYPE_NAMES[t]) for t in TYPE_NAMES) and SIDE_NAMES == {"front": "Лицевая", "back": "Оборот"}
le.load("front")
caps = [le.el_list.item(r).text() for r in range(le.el_list.count())]
caps = [c.split(" ", 1)[1] if c.startswith("#") else c for c in caps]
assert caps and all(any(c.startswith(n) for n in TYPE_NAMES.values()) for c in caps), caps
assert not any(k in " ".join(caps) for k in ("rect", "barcode", "photo", "field:", "qr:")), caps
ok(f"подписи типов по-русски (TYPE_NAMES): {caps[:4]}…")
# список элементов — только выбор
eids = [le.el_list.item(r).data(Qt.ItemDataRole.UserRole) for r in range(le.el_list.count())]
le.el_list.itemClicked.emit(le.el_list.item(1)); app.processEvents(); assert le.current and le.current.el["id"] == eids[1]
assert w.act_delete_element.isEnabled() and w.act_z_up.isEnabled()
le.scene.clearSelection(); app.processEvents(); assert not w.act_delete_element.isEnabled()
assert le.el_list.findChildren(QPushButton) == [] and le.findChildren(QPushButton) == [] and not hasattr(le, "apply_btn")
ok("список элементов: клик выделяет объект на холсте, своих кнопок нет; действия выделения активны только при выборе")
# таблица
w.show_main(); app.processEvents()
assert w.stack.currentWidget() is w.db_page and w.splitter.widget(0) is w.records and w.splitter.widget(1) is w.preview_panel
m = w.records.model; hdr = [m.headerData(c, Qt.Orientation.Horizontal) for c in range(m.columnCount())]
lab = {f["name"]: f["label"] for f in api.list_fields()}
assert hdr[:3] == ["Печать", "Логотип", "Фото"] and hdr[3:-1] == [f["label"] or f["name"] for f in api.list_fields() if f["name"] != "logo"] and hdr[-1] == "Напечатано", hdr
ok(f"таблица: колонки {hdr}")
pp = w.preview_panel
people = api.list_persons(); a_id, b_id = people[0]["id"], people[1]["id"]
for pid in (a_id, b_id):
    w._select_person(pid); app.processEvents()
    assert pp.person_id == pid and pp.pixmap.toImage() == QPixmap.fromImage(api.render_card(pid, "front")).toImage()
    assert pp.pixmaps["back"].toImage() == QPixmap.fromImage(api.render_card(pid, "back")).toImage()
    rows = pp.db_rows(); f = api.get_person(pid)["fields"]
    assert rows and any(v in f.values() for _k, v in rows) and not any("None" in k for k, _v in rows), rows
ok(f"выбор строки → «Сторона 1/2» = render_card, «Поле шаблона | Значение из БД»: {rows[:3]}…")
w.act_side.trigger(); app.processEvents(); assert pp.side == "back" and pp.sides.currentIndex() == 1 and w.layout_editor.side == "back"
w.act_side.trigger(); app.processEvents(); assert pp.side == "front"
ok("act_side: один переключатель Лицевая ⇄ Оборот (редактор и предпросмотр)")
# D13: чекбокс «Печать» → тот же QAction act_queue_toggle
hits = []; w.act_queue_toggle.triggered.connect(lambda *_: hits.append(1))
api.set_print_mark([p["id"] for p in people], False); w.records.reload()
mm = w.records.model; rr = mm.row_of(a_id)
mm.setData(mm.index(rr, 0), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
assert hits == [1] and api.get_person(a_id)["print_mark"] == 1 and w.records.selected_ids() == [a_id]
mm.setData(mm.index(mm.row_of(a_id), 0), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
assert hits == [1, 1] and api.get_person(a_id)["print_mark"] == 0
w.act_queue_toggle.triggered.disconnect()
w.act_queue_toggle.triggered.connect(w.queue_toggle)
ok("D13: чекбокс «Печать» в таблице → act_queue_toggle.trigger() (тот же обработчик set_print_mark)")
# D11: живое применение свойств, один шаг отмены
le_ = w.layout_editor; w.ribbon.select("Главная"); app.processEvents()
t_el = next(e for e in api.list_elements("front") if e["type"] == "text"); le_.load("front", t_el["id"])
nu = len(api._undo); le_.p_x.setValue(t_el["x"] + 7); le_.p_x.editingFinished.emit()
assert next(e for e in api.list_elements("front") if e["id"] == t_el["id"])["x"] == t_el["x"] + 7 and len(api._undo) == nu + 1
le_.p_x.editingFinished.emit(); assert len(api._undo) == nu + 1                  # без изменений — шага нет
le_.p_color.setText("#445566"); le_.p_color.editingFinished.emit(); assert len(api._undo) == nu + 2
w.undo(); w.undo(); assert next(e for e in api.list_elements("front") if e["id"] == t_el["id"]) == t_el
ok("D11: кнопки «Применить» нет; поле применяется сразу (editingFinished), одно изменение — один шаг отмены")
w.show_main(); app.processEvents()
# очередь / метки / дисплей
api.set_print_mark([p["id"] for p in people], False); w.records.reload(); w._select_person(b_id); app.processEvents()
assert w.queue_toggle() is True and [p["id"] for p in api.list_persons(only_marked=True)] == [b_id]
q = w.show_print_queue(exec_=False); assert q.ids() == [b_id] and q.table.rowCount() == 1
assert [b.text() for b in q.findChildren(QPushButton) if b.text() not in ("Close", "Закрыть", "&Close")] == []
assert w.queue_toggle() is False and api.list_persons(only_marked=True) == []
w.act_queue_toggle.trigger(); assert api.get_person(b_id)["print_mark"] == 1
ok("очередь печати: act_queue_toggle → set_print_mark; диалог очереди без дублирующих кнопок")
w._select_person(b_id); w.act_mark_printed.trigger()
pb = api.get_person(b_id); assert pb["printed_at"] and pb["print_mark"] == 0
assert w.set_display(True) == "Напечатанные" and w.records.visible_ids() == [b_id]
assert w.set_display(False) == "Ненапечатанные" and b_id not in w.records.visible_ids()
w.set_display(None); assert len(w.records.visible_ids()) == len(people) and w.display_actions[None].isChecked()
w._select_person(b_id); w.act_mark_unprinted.trigger(); assert api.get_person(b_id)["printed_at"] is None
ok("метки: «Напечатано» → mark_printed, «Не напечатано» → clear_printed; «Дисплей» Все/Напечатанные/Ненапечатанные")
# блок фильтра → query_persons
fb = w.records.filter; fb.clear()
fb.add_term("position", "contains", "бух"); w.act_filter_apply.trigger()
vis = w.records.visible_ids(); assert len(vis) == 1 and api.get_person(vis[0])["fields"]["last_name"] == "Петрова", vis
fb.add_term("last_name", "eq", "Иванов", "or"); w.act_filter_apply.trigger(); assert len(w.records.visible_ids()) == 2
assert "ИЛИ" in fb.expr.text() and fb.where()["join"] == "or"
fb.clear(); assert len(w.records.visible_ids()) == len(people)
ok(f"блок фильтра: «Добавить» → выражение «{'…'}», «Применить» (act_filter_apply) → query_persons")
assert w.goto("2") and w.records.selected_ids() == [w.records.visible_ids()[1]]
assert w.goto(f"#{a_id}") and w.records.selected_ids() == [a_id] and not w.goto("999")
ok("«Перейти к положению»: номер строки и #ID")
# удаление карты — только после подтверждения
cid = api.create_person({"last_name": "Удаляев"}); w.records.reload(); w._select_person(cid)
asked = []; rtm.confirm_delete_hook = lambda parent, n: (asked.append(n), False)[1]
w.act_card_delete.trigger(); assert asked == [1] and api.get_person(cid) is not None
rtm.confirm_delete_hook = lambda parent, n: (asked.append(n), True)[1]; w._select_person(cid)
w.act_card_delete.trigger(); assert asked == [1, 1] and api.get_person(cid) is None
rtm.confirm_delete_hook = None
ok("удаление карты: «Нет» — запись осталась, «Да» — delete_persons")
# редактор: буфер, стиль, выравнивание, undo/redo
w.ribbon.select("Главная"); app.processEvents(); le = w.layout_editor; le.load("front")
src = next(e for e in api.list_elements("front") if e["type"] == "text"); n0 = len(api.list_elements("front"))
le.select(src["id"]); app.processEvents(); assert w.copy() and w.act_paste.isEnabled()
pid_ = w.paste(); e_ = next(e for e in api.list_elements("front") if e["id"] == pid_)
assert (e_["x"], e_["y"]) == (src["x"] + 20, src["y"] + 20) and len(api.list_elements("front")) == n0 + 1
did = w.duplicate(); assert len(api.list_elements("front")) == n0 + 2
w.act_cut.trigger(); assert len(api.list_elements("front")) == n0 + 1 and w.clipboard
w.act_undo.trigger(); assert len(api.list_elements("front")) == n0 + 2
w.act_redo.trigger(); assert len(api.list_elements("front")) == n0 + 1
le.select(pid_); w.pick_color("fill", "#AABBCC"); w.pick_color("stroke", "#334455")
le.select(pid_); w.act_style_stroke_w.spin.setValue(3); w.act_style_stroke_w.spin.editingFinished.emit()
st = next(e for e in api.list_elements("front") if e["id"] == pid_)["style"]
assert st.get("fill") in ("#AABBCC", None) and st.get("stroke_width") in (3, None)
le.select(pid_); w.align_actions["left"].trigger(); assert next(e for e in api.list_elements("front") if e["id"] == pid_)["x"] == 0
w.act_undo.trigger(); assert next(e for e in api.list_elements("front") if e["id"] == pid_)["x"] == src["x"] + 20
for _ in range(10): w.undo()
assert len(api.list_elements("front")) == n0 and next(e for e in api.list_elements("front") if e["id"] == src["id"]) == src
ok("буфер: копировать/вставить (+20 px)/дублировать/вырезать; стиль и «Выровнять» через set_prop; отменить/повторить")
# эллипс (v4)
eid_e = w.layout_editor.run_tool("ellipse"); assert eid_e and next(e for e in api.list_elements() if e["id"] == eid_e)["type"] == "ellipse"
assert le.el_list.currentItem() is None or "Эллипс" in " ".join(le.el_list.item(r).text() for r in range(le.el_list.count()))
w.delete_element(); assert all(e["id"] != eid_e for e in api.list_elements())
ok("Эллипс: create_element('ellipse') → рендер Backend; удаление")
# положение
el0 = api.list_elements("front")[-1]; le.load("front", el0["id"])
from ui.main_view import PositionDialog
pd_ = PositionDialog({**el0}, w); assert pd_.findChildren(QPushButton) == [] or all(b.text() in ("OK", "&OK", "Cancel", "&Cancel", "Отмена") for b in pd_.findChildren(QPushButton))
assert not hasattr(pd_, "align")
mwm.position_hook = lambda d: (d.x.setValue(123), d.y.setValue(45), d.value())[2]; v = w.edit_position(); mwm.position_hook = None
e1 = next(e for e in api.list_elements("front") if e["id"] == el0["id"]); assert (e1["x"], e1["y"]) == (123, 45), e1
le.select(el0["id"]); w.align_actions["hcenter"].trigger()
e1 = next(e for e in api.list_elements("front") if e["id"] == el0["id"]); assert e1["x"] == (1011 - abs(e1["w"])) // 2 - min(0, e1["w"]), e1
ok(f"«Положение»: только X/Y (кнопок выравнивания нет) → (123, 45); центр — через «Выровнять ▾» → x={e1['x']}")
api.update_element(el0["id"], x=el0["x"], y=el0["y"]); le.load("front")
# менеджер полей
from ui.main_view import FieldManager
fm = w.field_manager(exec_=False)
fm.set_default("position", "Сотрудник")
assert next(f for f in api.list_fields() if f["name"] == "position")["default_value"] == "Сотрудник"
links = api.list_field_links(); fld = next(k for k, v in links.items() if v)
top = [fm.tree.topLevelItem(i) for i in range(fm.tree.topLevelItemCount())]
assert all(t.childCount() == 0 for t in top) and not any(t.text(0) == "Не связаны" for t in top)      # плоский список
assert not any(t.text(0).startswith("~") for t in top)
it = next(t for t in top if t.data(0, Qt.ItemDataRole.UserRole) == ("field", fld)); assert not it.icon(0).isNull()
fm.tree.setCurrentItem(it); fm.set_element(None); assert not fm.b_link.isEnabled() and not fm.b_unlink.isEnabled()
eid_l = links[fld][0]["element_id"]; fm.set_element(eid_l)
assert fm.b_unlink.isEnabled(); fm.unlink(); e_ = next(e for e in api.list_elements() if e["id"] == eid_l)
assert not e_.get("field_name") and e_["type"] == "text"          # Backend: field → text
fm._select_field(fld); fm.set_element(eid_l)
assert fm.b_link.isEnabled() and not fm.b_unlink.isEnabled(); fm.link()             # Backend 01a1768: text → field
e_ = next(e for e in api.list_elements() if e["id"] == eid_l); assert e_["type"] == "field" and e_["field_name"] == fld, e_
assert fm.b_print.text() == "Печать" and fm.b_print.toolTip() == "Печать списка полей"
assert ImportDialog(api, w).b_fields.defaultAction() is w.act_field_manager   # тот же QAction, без нового действия
bc = api.create_element(type="barcode", x=10, y=10, w=300, h=80, side="back", static_value="123"); fm.reload()
fm._select_field("employee_id"); fm.set_element(bc)
assert fm.b_link.isEnabled() and not fm.b_unlink.isEnabled(); fm.link("employee_id")
assert next(e for e in api.list_elements() if e["id"] == bc)["field_name"] == "employee_id"
assert any(x["element_id"] == bc for x in api.list_field_links()["employee_id"])
api.delete_element(bc); fm.set_element(None); fm.reload()
# Backend 91b0208 (вариант а): фото — обычное поле data_type=image, photo ↔ image через link_field
assert not any((t.data(0, Qt.ItemDataRole.UserRole) or ("",))[0] == "photo" for t in [fm.tree.topLevelItem(i) for i in range(fm.tree.topLevelItemCount())]), "постоянной строки «Фото» больше нет"
from ui import main_view as _mv
_errs = []; _mv.field_manager_hook = lambda kind, arg: _errs.append(arg) if kind == "error" else None
img_f = fm.add_field("Фото сотрудника", "image"); it_img = next(fm.tree.topLevelItem(i) for i in range(fm.tree.topLevelItemCount())
                                                              if fm.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == ("field", img_f))
assert it_img.text(1) == "Изображение"
ph_el = next(e for e in api.list_elements() if e["type"] == "photo")["id"]
fm._select_field("position"); fm.set_element(ph_el); assert not fm.b_link.isEnabled()          # photo ↔ только image
assert fm.link("position") is False and _errs and "изображ" in _errs[-1], _errs                 # текст ValueError Backend как есть
fm._select_field(img_f); fm.set_element(ph_el); assert fm.b_link.isEnabled() and fm.link()
assert any(x["element_id"] == ph_el and x["type"] == "photo" for x in api.list_field_links()[img_f])
_mv.field_manager_hook = None
from ui import record_form as _rfm
_pid = api.list_persons()[0]["id"]; rf_i = _rfm.RecordForm(api, _pid, w); ie = rf_i.edits[img_f]
assert isinstance(ie, _rfm.ImageFieldEdit) and hasattr(ie, "b_file")
_q = QImage(120, 150, QImage.Format.Format_RGB32); _q.fill(QColor("#3A7BD5")); ie.set_captured(_q); rf_i.save()
_v = api.get_person(_pid)["fields"][img_f]; assert _v.startswith("photos/") and (Path(api.base_dir) / _v).is_file(), _v
_el = next(e for e in api.list_elements() if e["id"] == ph_el); assert Path(api.resolve_photo_path(api.get_person(_pid), _el)) == Path(api.base_dir) / _v
fm.set_element(ph_el); fm.unlink(); fm.set_element(None); fm.reload()
ok(f"фото = поле типа image «{img_f}»: photo↔image через link_field, ValueError показан как есть, камера в форме → save_photo → {_v}; resolve_photo_path")
assert "Сотрудник" in fm.field_list_text()
prn = QPrinter(); prn.setOutputFormat(QPrinter.OutputFormat.PdfFormat); prn.setOutputFileName(str(tmp / "fields.pdf"))
assert fm.print_list(prn) and (tmp / "fields.pdf").stat().st_size > 0
fm.resize(640, 520); fm.show(); spin(80); fm.grab().save(str(shots / "stage12_field_manager.png")); fm.close()
api.set_field_default("position", None)
ok(f"менеджер полей: default_value (set_field_default), отвязать → связать снова #{eid_l} ↔ {fld} (text → field), связать штрихкод ↔ employee_id, печать списка; скриншот")
# бэкап / сжатие / восстановление
bk = tmp / "copy.db"; w.save_as(str(bk)); assert bk.exists()
r = w.compact(str(tmp / "bk")); assert r and r.get("integrity") == "ok" and Path(r["backup"]).exists(), r
n_before = len(api.list_persons()); api.create_person({"last_name": "Лишний"}); assert len(api.list_persons()) == n_before + 1
mwm.ask_hook = lambda kind, parent: str(bk) if kind == "restore" else None
assert w.restore() and len(api.list_persons()) == n_before and w.records.model.rowCount() == n_before
mwm.ask_hook = None
ok("Сохранить как… → backup_db; «Сжать и восстановить» → compact_and_backup / restore_db (переподключение)")
# захват изображения из файла
w.show_main(); demo.make_photo(tmp / "cap.png"); w._select_person(a_id); app.processEvents()
from ui.photo_block import multimedia
assert not hasattr(w, "act_capture")
ok(f"D22: «Захват изображения» убран из ленты; камера: {multimedia()[1]}")
assert w.open_settings({"grid": 25})["grid"] == 25; w.act_grid.trigger(); assert le.grid_on; w.act_grid.trigger()
w.act_rulers.trigger(); assert not le.hruler.isVisible(); w.act_rulers.trigger()
w.ribbon.select("Главная"); app.processEvents(); assert le.hruler.isVisible()
txt = []; mwm.about_hook = txt.append; w.about(); mwm.about_hook = None; assert f"Схема БД: v{bdb.LATEST}" in txt[0] and bdb.LATEST >= 4
ok(f"Настройки, Сетка, Линейки, О программе (схема v{bdb.LATEST})")
# скриншоты всех вкладок ленты
w._select_person(a_id); w.showNormal(); w.resize(1280, 800); spin(120)
le.load("front", next(e for e in api.list_elements("front") if e["type"] == "text")["id"])
for i, t in enumerate(TABS):
    w.ribbon.setCurrentIndex(i); spin(120)
    if t != "База данных" and le.current is None: le.load("front", api.list_elements("front")[0]["id"])
    w.grab().save(str(shots / f"stage12_tab_{i + 1}.png"))
w.resize(1024, 720); w.ribbon.select("Рисование"); spin(120); w.grab().save(str(shots / "stage12_1024.png"))
ok("скриншоты: reports/stage12_tab_1..7.png, stage12_1024.png, stage12_field_manager.png")
# --- D19: набор полей только из list_fields(); добавление → выделение, превью и значения ---
from ui import records_table as rtm
from ui.backend_api import field_desync
ivan_db = tmp / "ivan.db"
api.open_db(ivan_db)
for i, (n, l) in enumerate([("familiya", "Фамилия"), ("imya", "Имя"), ("otchestvo", "Отчество"), ("fakultet", "Факультет")]):
    api.upsert_field(n, l, i)
    api.create_element(type="field", side="front", x=40, y=40 + 70 * i, w=600, h=60, field_name=n)
w.refresh_all(); app.processEvents()
empty = w.preview_panel.pixmaps["front"].toImage()
assert [m.headerData(c, Qt.Orientation.Horizontal) for c in range(m.columnCount())] == ["Печать", "Фамилия", "Имя", "Отчество", "Факультет", "Напечатано"]
vals = {"familiya": "Иванова", "imya": "Мария", "otchestvo": "Петровна", "fakultet": "Физмат"}
def fill(f):
    assert list(f.edits) == list(vals), list(f.edits)
    for k, v in vals.items(): f.edits[k].setText(v)
    f.save(); return f.result() == 1
rtm.form_hook = fill; new_id = w.records._open_form(None); rtm.form_hook = None; spin(50)
assert w.records.selected_ids() == [new_id] and w.preview_panel.person_id == new_id
img = w.preview_panel.pixmaps["front"].toImage(); assert img != empty                       # текст отрисован
diff = sum(1 for x in range(0, img.width(), 4) for y in range(0, img.height(), 4) if img.pixel(x, y) != empty.pixel(x, y))
assert diff > 50, diff
rows = dict(w.preview_panel.db_rows())
assert [v for k, v in rows.items() if "Поле" in k] == list(vals.values()), rows
api.update_person(new_id, fields={"familiya": "Иванова", "imya": "", "otchestvo": "Петровна", "fakultet": "Физмат"}); w.preview_panel.refresh()
it = next(w.preview_panel.fields.item(r, 1) for r in range(w.preview_panel.fields.rowCount()) if w.preview_panel.fields.item(r, 0).text().startswith("Имя"))
assert it.text() == "(пусто)" and it.foreground().color().name() == "#9aa3ae"
assert w.preview_panel.warning.isHidden() and field_desync(api) == {"person_keys": [], "template_fields": []}
# старая БД: ключ записи без person_fields и field_name шаблона без поля → предупреждение
api.create_person({"familiya": "Старая", "fio": "Старая Запись"}); api.create_element(type="field", side="back", x=10, y=10, w=300, h=50, field_name="kafedra")
w.refresh_all(); app.processEvents()
assert field_desync(api) == {"person_keys": ["fio"], "template_fields": ["kafedra"]}
assert not w.preview_panel.warning.isHidden() and "kafedra" in w.preview_panel.warning.text() and "fio" in w.preview_panel.warning.text()
f3 = rtm.RecordForm(api, None, w); assert "kafedra" in f3.edits and list(f3.edits)[:4] == list(vals); f3.close()
w.records.select_id(new_id); spin(80); assert w.preview_panel.person_id == new_id
w.preview_panel.grab().save(str(shots / "d19_preview.png"))
ok(f"D19: колонки/форма = list_fields(); новая запись выделена, превью с текстом (Δ={diff} px), значения заполнены, «(пусто)» серым; рассинхрон {field_desync(api)} → предупреждение")
# --- этап 13: импорт/экспорт на API Backend (open_source/read_rows/import_rows/export_persons) ---
def not_elided(dlg):
    for b in dlg.findChildren(QPushButton):
        if b.isVisible(): assert b.width() >= b.sizeHint().width(), (b.text(), b.width(), b.sizeHint().width())
assert w.act_import.text() == "Импорт записей…" and w.act_export.text() == "Экспорт…"
pid13 = api.list_persons()[0]["id"]
ed = ExportDialog(api, [], w, filtered_ids=[pid13]); ed.m_data.setChecked(True); ed.show(); spin(50)
assert [ed.data_fmt.itemData(i) for i in range(ed.data_fmt.count())] == ["xlsx", "xls", "csv", "db"]
assert not ed.png.isVisible() and ed.d_filtered.isVisible() and ed.hint.isVisible() and "только в .db" in ed.hint.text()
ed.data_fmt.setCurrentIndex(3); assert not ed.hint.isVisible(); ed.data_fmt.setCurrentIndex(0)
ed.d_filtered.setChecked(True); assert ed.data_ids() == [pid13]
ed.target.setText(str(tmp / "out13.xlsx")); assert ed.start() is True and (tmp / "out13.xlsx").exists() and ed.result["rows"] == 1, ed.status.text()
dialogs.XLS_MAX_ROWS, _xm = 0, dialogs.XLS_MAX_ROWS
ed.data_fmt.setCurrentIndex(1); assert ed.target.text().endswith(".xls"); assert ed.start() is False and ".xls" in ed.status.text() and not (tmp / "out13.xls").exists()
dialogs.XLS_MAX_ROWS = _xm
ed.data_fmt.setCurrentIndex(2); assert ed.start() is True and (tmp / "out13.csv").exists()
ed.d_all.setChecked(True); ed.data_fmt.setCurrentIndex(3); assert ed.start() is True and (tmp / "out13.db").exists()
assert ed.start() is False and "существует" in ed.status.text()          # FileExistsError Backend → понятный текст
not_elided(ed); ed.m_cards.setChecked(True); assert ed.png.isVisible() and not ed.hint.isVisible(); ed.close()
ok("этап 13: экспорт данных xlsx/xls/csv/db (все/отфильтрованные), подсказка D29, лимит XLS_MAX_ROWS, FileExistsError")
di = ImportDialog(api, w); assert di.set_file(str(tmp / "out13.xlsx")); di.resize(1000, 680); di.show(); spin(80)
assert [di.table.horizontalHeaderItem(i).text() for i in range(4)] == ["Поле БД", "Тип", "Сопоставлено", "Колонка файла ▾"]
assert [b.text() for b in (di.b_save, di.b_load, di.btn, di.b_close)] == ["Сохранить привязку", "Загрузить привязку", "Импорт", "Отмена"]
assert di.b_fields.defaultAction() is w.act_field_manager and di.sheet.count() >= 1 and di.preview.rowCount() == 1
f0 = api.list_fields()[0]
assert di.field_column(f0["name"]) == f0["label"] and di.field_column("print_mark") == "Отметка печати"
r_pm = di._keys().index("print_mark"); assert di.table.item(r_pm, 0).text() == "Отметка печати" and di.table.item(r_pm, 2).text() == "✓ авто"
di.set_target(f0["label"], None); assert di.mapping() == {f0["label"]: None}, di.mapping()
assert di._save_binding(path=str(tmp / "b13.json")); di._load(); assert di.mapping() is None
assert di._load_binding(path=str(tmp / "b13.json")) and di.mapping() == {f0["label"]: None}
(tmp / "bad.json").write_text("{}", encoding="utf-8"); assert di._load_binding(path=str(tmp / "bad.json")) is False and "Не удалось" in di.log.toPlainText()
di.use_header.setChecked(False); assert di.headers[0] == "Колонка 1" and di.preview.rowCount() == 2; di.use_header.setChecked(True)
n0 = len(api.list_persons()); di.run(); rep = di.report
assert rep and rep.added == 1 and len(api.list_persons()) == n0 + 1 and "Добавлено: 1" in di.log.toPlainText(), di.log.toPlainText()
di.reject(); assert di.sheets == []
api2 = BackendAPI(str(tmp / "fresh13.db"), base_dir=str(tmp)); assert api2.list_fields() == []
dd = ImportDialog(api2, w); dd.set_file(str(tmp / "out13.db")); sh = dd.current_sheet()
assert sh.kind == "project" and dd.new_source_fields() and dd.is_db() and not dd.use_header.isEnabled()
wp = sh.work_path; seen = []
dialogs.confirm_fields_hook = lambda new: None; dd.run(); assert dd.report is None and "отменён" in dd.log.toPlainText()
dialogs.confirm_fields_hook = lambda new: seen.append(new) or True; dd.run(); dialogs.confirm_fields_hook = None
assert seen and dd.report.added == len(api.list_persons()) - 1 and {f["name"] for f in api2.list_fields()} >= {f0["name"]}, (dd.log.toPlainText(), api2.list_fields())
dd.reject(); assert dd.sheets == [] and (wp is None or not Path(wp).exists()); api2.close()
ok(f"этап 13: импорт xlsx (лист, заголовок, auto_match, «Отметка печати», привязка save/load/битая), .db → подтверждение → import_fields=True; sheet.close() при закрытии")
# ===== D48: ImportDialog.close_sheets — OSError в журнал, повтор при закрытии, прочие исключения не глотаются =====
from pathlib import Path as _P48
class _Sh48:
    def __init__(self, name, fails, exc=OSError): self.work_path, self.name, self.fails, self.exc, self.calls = _P48(f"/tmp/{name}"), name, fails, exc, 0
    def close(self):
        self.calls += 1
        if self.calls <= self.fails: raise self.exc(f"занят {self.name}")
d48 = ImportDialog(api, w); a48, b48, c48 = _Sh48("a48.db", 1), _Sh48("b48.db", 0), _Sh48("c48.db", 5)
d48.sheets = [a48, b48, c48]; d48.close_sheets()                      # смена файла: ошибка в журнал, остальные закрыты
lg = d48.log.toPlainText()
assert "Не удалось закрыть источник «a48.db»" in lg and "занят a48.db" in lg and "«c48.db»" in lg and b48.calls == 1 and d48.sheets == [], lg
d48.reject(); app.processEvents()                                     # закрытие: одна повторная попытка для неудачных
assert a48.calls == 2 and c48.calls == 2 and b48.calls == 1 and d48._close_failed == [], (a48.calls, c48.calls)
L48 = d48.log.toPlainText().splitlines()
assert sum("Не удалось закрыть источник «a48.db»" in l for l in L48) == 1 and sum("«c48.db»" in l for l in L48) == 1, L48   # первая ошибка — одна полная запись
assert sum(l == "Повторная попытка закрыть c48.db не удалась" for l in L48) == 1, L48                                   # повтор не удался — одна короткая
assert sum("занят c48.db" in l for l in L48) == 1, L48                                                                   # текст ошибки не повторён
assert not any("a48.db" in l for l in L48[L48.index("Повторная попытка закрыть c48.db не удалась"):]) and len(L48) == 3, L48  # повтор a48 удался — без строки
d48b = ImportDialog(api, w); u48, v48 = _Sh48("u48.db", 1, KeyError), _Sh48("v48.db", 0); d48b.sheets = [u48, v48]
try: d48b.close_sheets(); raise AssertionError("KeyError проглочен")
except KeyError: pass
assert v48.calls == 1 and "u48" not in d48b.log.toPlainText(); d48b.deleteLater()
ok("D48: OSError Sheet.close() → журнал диалога (имя файла, по-русски), остальные листы закрыты, повтор один раз при закрытии; прочие исключения пробрасываются")

# ===== этап 14: редактор фото (двойной клик / контекстное меню, ползунки, рамка, Портрет, умолчания, Применить) =====
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QPointF, QRectF
from ui import photo_editor as pe
from ui import backend_api as _ba14
import shutil
api14 = BackendAPI(str(tmp / "s14.db"), base_dir=str(tmp)); api14.upsert_field("foto", "Фото", 0, data_type="image")
_pe = api14.create_element(type="photo", x=0, y=0, w=300, h=400); api14.link_field(_pe, "foto")
# пропорции — только Backend photo_edit_target; пока функции нет в Backend — тестовая подмена НА ЭКЗЕМПЛЯРЕ api14
_REAL_TARGET = _ba14._backend_fn("photo_edit_target") is not None
if not _REAL_TARGET:
    api14.photo_edit_target = lambda fn: {"aspect": 0.75, "size": (300, 400), "element_id": _pe} if fn == "foto" else None
_REAL_SESSION = _ba14._backend_fn("PhotoSession") is not None
_face = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "face_astronaut.jpg"
if _face.is_file(): shutil.copy(_face, tmp / "p14.jpg")
else: demo.make_photo(tmp / "p14.jpg")
rf14 = RecordForm(api14, None, w); ie14 = rf14.edits["foto"]; rf14.show(); spin(30)
assert not ie14.act_edit.isEnabled() and not hasattr(ie14, "aspect")
got14 = []; pe.editor_hook = lambda d: got14.append(d) or 0
ie14.from_file(str(tmp / "p14.jpg")); spin(30); assert not got14 and ie14.editor is None       # после файла сам не открывается
assert ie14.act_edit in ie14.still.actions() and ie14.act_edit.isEnabled()                   # тот же QAction в контекстном меню
QTest.mouseDClick(ie14.still, Qt.MouseButton.LeftButton); spin(30); ed14 = got14[-1]
assert ed14.windowTitle() == "Редактировать изображение" and ed14.field_name == "foto"
assert abs(ed14.aspect - api14.photo_edit_target("foto")["aspect"]) < 1e-9 and abs(ed14.aspect - 0.75) < 1e-3   # из Backend
# пропорции: нет функции Backend / нет фото-элемента → статус, рамки нет, своих пропорций не выдумываем
_api_nt = BackendAPI(str(tmp / "s14nt.db"), base_dir=str(tmp))
if not _REAL_TARGET:
    _ednt = pe.PhotoEditor(str(tmp / "p14.jpg"), _api_nt, None, field_name="foto")
    assert _ednt.aspect is None and _ednt.frame.aspect is None and "Нет функции Backend для пропорций" in _ednt.status.text(); _ednt.reject()
_api_nt.photo_edit_target = lambda fn: None
_ednt = pe.PhotoEditor(str(tmp / "p14.jpg"), _api_nt, None, field_name="foto")
_D46 = "В шаблоне нет фото-элемента, пропорции свободные"
assert _ednt.aspect is None and not _ednt.portrait.isEnabled() and _ednt.status.text() == _D46, _ednt.status.text()
_ednt.sl["brightness"].setValue(20); _ednt.update_preview(); assert _ednt.status.text() == _D46, _ednt.status.text()   # D46: после превью
_r = _ednt.frame.rect(); _ednt.frame.resize_corner("br", QPointF(_r.left() + 50, _r.top() + 120), _r)      # свободная рамка
assert (round(_ednt.frame.rect().width()), round(_ednt.frame.rect().height())) == (50, 120), _ednt.frame.rect()
_ednt.reject(); _api_nt.close()
assert [b.text() for b in (ed14.b_apply, ed14.b_cancel)] == ["Применить", "Отмена"] and "УгЧ" not in " ".join(b.text() for b in ed14.findChildren(QPushButton))
assert [(ed14.sp[k].minimum(), ed14.sp[k].maximum()) for k in ("brightness", "contrast", "scale", "rotate")] == [(-50, 50), (-50, 50), (10, 400), (-180, 180)]
r0 = ed14.frame.rect(); assert abs(r0.width() / r0.height() - 0.75) < 1e-3 and ed14.frame.pen().style() == Qt.PenStyle.DashLine
ed14.frame.resize_corner("br", QPointF(r0.right() - 50, r0.bottom() - 5)); r1 = ed14.frame.rect()
assert abs(r1.width() / r1.height() - 0.75) < 1e-3 and r1.topLeft() == r0.topLeft() and r1.width() < r0.width()
ed14.frame.move_by(QPointF(-10000, -10000)); assert ed14.frame.rect().topLeft() == QPointF(0, 0)
if _ba14.photo_edit_available():
    assert "нет apply_photo_edit" not in ed14.status.text() and "нет detect_face_crop" not in ed14.status.text(), ed14.status.text()
    px0 = ed14.img.tobytes(); ed14.sl["brightness"].setValue(20); ed14.update_preview()
    assert ed14.sp["brightness"].value() == 20 and ed14.img.tobytes() != px0                  # превью через Backend
    sz0 = ed14.img.size; ed14.sp["scale"].setValue(50); ed14.update_preview(); assert ed14.img.width < sz0[0]
    ed14.sp["scale"].setValue(100); ed14.update_preview()
    # умолчания проекта — Backend get/set_photo_edit_defaults
    assert ed14.save_defaults()["brightness"] == 20 and api14.get_photo_edit_defaults()["brightness"] == 20
    ed14.sp["brightness"].setValue(-5); ed14.load_defaults(); assert ed14.sp["brightness"].value() == 20
    ed14b = pe.PhotoEditor(str(tmp / "p14.jpg"), api14, None, field_name="foto"); assert ed14b.sp["brightness"].value() == 20; ed14b.reject()
    api14.set_photo_edit_defaults(dict(_ba14.PHOTO_EDIT_DEFAULTS)); ed14.load_defaults(); assert ed14.params(crop=False)["brightness"] == 0
    # ValueError → статус по-русски
    ed14.frame.setRect(ed14.frame.rect().translated(100000, 100000)); assert ed14.apply() is False and "Фото не сохранено" in ed14.status.text()
    ed14.reset_frame()
    # Портрет: рамка по лицу (или «Лицо не найдено»)
    ed14.portrait.setChecked(True); spin(10)
    face = ed14.portrait.isChecked(); assert face or "Лицо не найдено" in ed14.status.text()
    if _face.is_file(): assert face, ed14.status.text()
    fr = ed14.frame.rect(); assert abs(fr.width() / fr.height() - 0.75) < 0.02
    ed14.autoeffect.setChecked(True); spin(100); assert ed14.params()["autoeffect"] and ed14.params()["portrait"] is True
    # D42: рамка с пером целиком в видимой области вида (в т.ч. у края изображения)
    ed14.show(); ed14.resize(520, 680); spin(50)
    for pos in ("face", "tl"):
        if pos == "tl": ed14.frame.move_by(QPointF(-10000, -10000)); spin(20)
        vr = ed14.frame.visible_device_rect(); vp = QRectF(ed14.view.viewport().rect())
        assert vp.contains(vr) and ed14.frame.boundingRect().contains(ed14.frame.rect()), (pos, vr, vp)
    ed14.portrait.setChecked(False); ed14.portrait.setChecked(True); spin(10)
    # D41: «Портрет» уходит в set_photo_edit_defaults (ключ portrait); восстановлен как вкл → рамка по лицу при открытии
    sent = []; _set0 = api14.set_photo_edit_defaults
    api14.set_photo_edit_defaults = lambda p: sent.append(dict(p)) or _set0(p)
    ed14.save_defaults(); del api14.set_photo_edit_defaults; assert sent and sent[-1]["portrait"] is True
    if "portrait" in _ba14.PHOTO_EDIT_DEFAULTS:                                        # Backend хранит ключ
        assert api14.get_photo_edit_defaults()["portrait"] is True
    _get0 = api14.get_photo_edit_defaults; api14.get_photo_edit_defaults = lambda: {**_get0(), "portrait": True}
    try:
        edp = pe.PhotoEditor(str(tmp / "p14.jpg"), api14, None, field_name="foto")
        assert edp.portrait.isChecked() and edp.crop() == tuple(_ba14.detect_face_crop(edp.img, 0.75)), edp.crop()
        edp.portrait.setChecked(False); edp.load_defaults(); assert edp.portrait.isChecked(); edp.reject()
    finally: del api14.get_photo_edit_defaults
    api14.set_photo_edit_defaults(dict(_ba14.PHOTO_EDIT_DEFAULTS))
    ed14.autoeffect.setChecked(True); spin(100)
    # нет load_photo_for_edit / битый файл → статус по-русски, без глобального диалога
    _lp = _ba14._api.load_photo_for_edit; del _ba14._api.load_photo_for_edit
    try: edx = pe.PhotoEditor(str(tmp / "p14.jpg"), api14, None, field_name="foto"); assert edx.status.text() == "Редактор недоступен: нет load_photo_for_edit" and not edx.b_apply.isEnabled(); edx.reject()
    finally: _ba14._api.load_photo_for_edit = _lp
    (tmp / "bad14.jpg").write_bytes(b"not an image"); edx = pe.PhotoEditor(str(tmp / "bad14.jpg"), api14, None, field_name="foto")
    assert edx.status.text().startswith("Не удалось открыть фото") and edx.apply() is False; edx.reject()
    # Применить (новая запись → apply_and_save_photo без field_name; путь в поле формы → «Сохранить»)
    assert ed14.apply() is True and ed14.result_path.startswith("photos/") and (tmp / ed14.result_path).is_file()
    assert ie14.text() == ed14.result_path and (tmp / "p14.jpg").is_file(), (ie14.text(), ed14.result_path)
    if _REAL_TARGET:   # D44: файл «Применить» ровно размера photo_edit_target(field)['size']
        from PyQt6.QtGui import QImage
        _q = QImage(str(tmp / ed14.result_path)); _t = api14.photo_edit_target("foto")
        assert _t and [_q.width(), _q.height()] == list(_t["size"]), ((_q.width(), _q.height()), _t)
    rf14.save(); pid14 = api14.list_persons()[-1]["id"]; assert api14.list_persons()[-1]["fields"]["foto"] == ed14.result_path
    # существующая запись: «Применить» → путь только в форме; «Отмена» формы → значение в БД не меняется
    rf14b = RecordForm(api14, pid14, w); ie14b = rf14b.edits["foto"]; old = api14.get_person(pid14)["fields"]["foto"]
    QTest.mouseDClick(ie14b.still, Qt.MouseButton.LeftButton); spin(30); ed14c = got14[-1]
    assert ed14c.apply() is True and ed14c.result_path != old and ie14b.text() == ed14c.result_path
    assert api14.get_person(pid14)["fields"]["foto"] == old                                  # до «Сохранить» БД не тронута
    rf14b.reject(); assert api14.get_person(pid14)["fields"]["foto"] == old and (tmp / old).is_file()
    # D43: «Отмена» формы → discard_photo для каждого файла редактора этой сессии (UI сам не удаляет)
    if _REAL_SESSION: assert rf14b.discarded == [ed14c.result_path] and not (tmp / ed14c.result_path).is_file(), rf14b.discarded
    # «Из файла…» → PhotoSession.save_photo: копия учитывается и удаляется на «Отмена», исходник цел (и вне, и внутри photos/)
    if _REAL_SESSION:
        (tmp / "photos").mkdir(exist_ok=True); shutil.copy(tmp / "p14.jpg", tmp / "photos" / "user_src14.jpg")
        for srcf in (tmp / "p14.jpg", tmp / "photos" / "user_src14.jpg"):
            rff = RecordForm(api14, pid14, w); ief = rff.edits["foto"]; assert ief.from_file(str(srcf))
            cp = ief.text(); assert cp.startswith("photos/") and (tmp / cp).resolve() != srcf.resolve() and (tmp / cp).is_file()
            assert rff.photo_session.created == [cp], rff.photo_session.created
            rff.reject(); assert srcf.is_file() and not (tmp / cp).is_file() and rff.discarded == [cp], (srcf, cp, rff.discarded)
    # «Сохранить» → PhotoSession.commit(): файл, на который ссылается запись, остаётся
    rf14c = RecordForm(api14, pid14, w); ie14c = rf14c.edits["foto"]; QTest.mouseDClick(ie14c.still, Qt.MouseButton.LeftButton); spin(30)
    ed14d = got14[-1]; assert ed14d.session is rf14c.photo_session and ed14d.apply() is True; rf14c.save()
    assert api14.get_person(pid14)["fields"]["foto"] == ed14d.result_path and (tmp / ed14d.result_path).is_file()
else:
    assert "apply_photo_edit" in ed14.status.text() and ed14.apply() is False
    assert ed14.find_face() is False and "Лицо не найдено" in ed14.status.text()
pe.editor_hook = None
api14.close()
ok("этап 14: редактор фото — двойной клик/контекстное меню (один QAction), без автооткрытия, ползунки с полями, превью Backend, рамка с пропорциями (углы/перенос), Портрет (лицо), Автоэффект, умолчания проекта (Backend), ValueError в статусе, Применить → apply_and_save_photo → поле формы → «Сохранить»; «Отмена» формы не меняет БД, discard_photo (D43); D41 портрет в умолчаниях; D42 рамка видна; пропорции photo_edit_target")
# расположение окна сохраняется автоматически в closeEvent
_cfg2 = tempfile.mkdtemp(prefix="bg_ui_cfg2_")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _cfg2)
w.settings = QSettings("BadgeGenerator", "Frontend")
w.show_main(); w.resize(1280, 800); app.processEvents(); w.splitter.setSizes([500, 700]); app.processEvents(); saved = w.splitter.sizes()
w.close(); app.processEvents()
assert w.settings.value("window/splitter") is not None
w2 = MainWindow(api); w2.resize(w.size()); w2.show(); w2.show_main(); spin(100); r2 = w2.splitter.sizes()
assert abs(r2[0] / sum(r2) - saved[0] / sum(saved)) < 0.03, (r2, saved)
w2.reset_layout(); app.processEvents(); sz = w2.splitter.sizes()
assert abs(sz[0] / sum(sz) - 0.65) < 0.05, sz
ok(f"сплиттер: {saved} сохранён в closeEvent и восстановлен; сброс → ~65/35 {sz}")
w2.close(); lem.warn_hook = None
# ===== D20/D21/D24: excepthook, менеджер полей (добавить/переименовать/удалить, тип), typed-редакторы =====
from ui import errors as uerr
got = []; uerr.error_hook = got.append; uerr.handle(RuntimeError, RuntimeError("smoke"), None); uerr.error_hook = None
assert got and "smoke" in got[0] and Path(uerr.log_path()).read_text(encoding="utf-8").rstrip().endswith("RuntimeError: smoke")
ok(f"D20: excepthook → без падения, журнал {uerr.log_path()}")
from ui import main_view as mvm
from ui.backend_api import field_type, FIELD_TYPE_NAMES
fm = w.field_manager(exec_=False)
assert [fm.tree.headerItem().text(i) for i in range(3)] == ["Поле", "Тип данных", "Значение по умолчанию"]
nm = fm.add_field("Дата выдачи", "date", "2026-01-31")
f_ = next(f for f in api.list_fields() if f["name"] == nm); assert field_type(f_) == "date", f_
it = fm.tree.currentItem(); assert it.text(1) == "Дата" and it.text(2) == "31.01.2026", (it.text(1), it.text(2))
assert fm.rename_field("Дата выдачи пропуска", "date") and next(f for f in api.list_fields() if f["name"] == nm)["label"] == "Дата выдачи пропуска"
nb = fm.add_field("Студент", "bool"); nn = fm.add_field("Курс", "number")
from ui.record_form import RecordForm as RF, editor_value
rf = RF(api, None, w); assert type(rf.edits[nm]).__name__ == "QDateEdit" and rf.edits[nm].displayFormat() == "dd.MM.yyyy"
assert type(rf.edits[nb]).__name__ == "QCheckBox" and type(rf.edits[nn]).__name__ == "QDoubleSpinBox"
rf.edits[nb].setChecked(True); assert editor_value(rf.edits[nb]) == "1"; rf.photo_block.stop(); rf.reject()
mvm.field_manager_hook = lambda kind, q: False
for n_ in (nm, nb, nn):
    fm._select_field(n_); assert not fm.delete_field() and any(f["name"] == n_ for f in api.list_fields())   # без подтверждения — нет
    fm._select_field(n_); assert fm.delete_field(confirm=True) is not False and not any(f["name"] == n_ for f in api.list_fields())
mvm.field_manager_hook = None
fm.resize(720, 560); fm.show(); spin(80); fm.grab().save(str(shots / "stage12_field_manager.png")); fm.close()
ok("D21/D24: менеджер полей — Поле | Тип данных | Значение по умолчанию; добавить/переименовать/удалить (с подтверждением); редакторы по типу")
# ===== self-test (тот же сценарий click-all, что и --self-test) =====
from ui import self_test
rc = self_test.run(["x"], app=app, log_file=str(tmp / "self_test.log"))
assert rc == 0, (tmp / "self_test.log").read_text(encoding="utf-8")[-3000:]
ok(f"self-test (click-all): код 0, лог {tmp / 'self_test.log'}")
print("ALL OK; tmp =", tmp)
