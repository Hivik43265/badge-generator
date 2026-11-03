"""QA: нажать КАЖДЫЙ QAction ленты и открыть каждый диалог (offscreen); модальные окна закрываются QTimer.
Любое исключение (в т.ч. в слоте Qt) или падение → FAIL. Плюс сценарий «добавить запись → текст на превью» (D19).

Запуск из исходников:
    QT_QPA_PLATFORM=offscreen .venv/bin/python reports/qa/e2e_click_all.py [--root <каталог проекта>]
Решение Архитектора (этап 13): --qa-run отклонён. Сценарий переезжает в ui/qa_click_all.py (пишет Frontend)
и запускается из exe через --self-test. Этот файл — тонкая обёртка: если ui/qa_click_all.py есть, вызывается
его run(); иначе — собственная реализация ниже (fallback). Exit code: 0 — все PASS, 1 — есть FAIL.
"""
import os, sys, tempfile, pathlib, traceback, json, faulthandler
faulthandler.enable()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve()
ROOT = pathlib.Path(sys.argv[sys.argv.index("--root") + 1]).resolve() if "--root" in sys.argv else HERE.parents[2]
if not getattr(sys, "frozen", False): sys.path.insert(0, str(ROOT))
try:
    import importlib.util as _u
    if "--fallback" not in sys.argv and _u.find_spec("ui.qa_click_all") is not None:
        try: from ui import qa_click_all as _q
        except Exception as _e: print("WARN | ui.qa_click_all не импортируется, fallback |", repr(_e)[:200], flush=True); raise ImportError
        rc = _q.run(sys.argv) if hasattr(_q, "run") else _q.main(sys.argv)
        sys.stdout.flush(); os._exit(int(bool(rc)))
except ImportError:
    pass
from PyQt6.QtCore import QSettings, QTimer, QEventLoop, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QLineEdit, QWidget, QMenu
from PyQt6.QtGui import QAction
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa_click_"))
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(TMP / "cfg"))
app = QApplication.instance() or QApplication([])
from badge_backend import api as B
from ui.backend_api import BackendAPI
from ui.main_window import MainWindow

RES, EXC = [], []
def chk(n, ok, ev=""): RES.append((n, bool(ok), str(ev))); print(("PASS" if ok else "FAIL"), "|", n, "|", ev, flush=True)
def hook(t, v, tb): EXC.append("".join(traceback.format_exception(t, v, tb))[-600:])
sys.excepthook = hook
def spin(ms=30):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()

# --- автозакрытие модальных окон ---
OPENED = []; FILL = {}; HOLD = []
def closer():
    if HOLD: return
    w = QApplication.activeModalWidget() or next((x for x in QApplication.topLevelWidgets() if isinstance(x, QDialog) and x.isVisible()), None)
    if w is None:
        for m in QApplication.topLevelWidgets():
            if isinstance(m, QMenu) and m.isVisible(): m.close()
        return
    OPENED.append(f"{type(w).__name__}«{w.windowTitle()}»")
    try:
        if FILL and type(w).__name__ == "RecordForm":
            for k, v in FILL.items():
                e = getattr(w, "edits", {}).get(k)
                if e is not None: e.setText(v)
            FILL.clear(); (w.save() if hasattr(w, "save") else w.accept()); return
        if isinstance(w, QMessageBox): w.done(QMessageBox.StandardButton.No.value if w.buttons() else 0); return
        if isinstance(w, QDialog): w.reject()
        else: w.close()
    except Exception: EXC.append(traceback.format_exc()[-600:])
tm = QTimer(); tm.setInterval(80); tm.timeout.connect(closer); tm.start()

def make_db(path, with_fields=True):
    c = B.connect(str(path))
    if with_fields:
        for i, (n, l) in enumerate((("last_name", "Фамилия"), ("first_name", "Имя"), ("faculty", "Факультет"))): B.upsert_field(c, n, l, i)
    B.create_element(c, "field", 40, 40, 900, 120, field_name="last_name", style={"font_size": 40})
    B.create_element(c, "field", 40, 200, 900, 100, field_name="first_name", style={"font_size": 36})
    B.create_element(c, "field", 40, 330, 900, 90, field_name="faculty", style={"font_size": 30})
    B.create_element(c, "rect", 20, 20, 970, 600, style={"stroke": "#000", "stroke_width": 2})
    B.create_element(c, "ellipse", 800, 450, 150, 120, style={"stroke": "#000", "stroke_width": 2})
    pid = B.create_person(c, {"last_name": "Иванов", "first_name": "Иван", "faculty": "Физфак"})
    c.close(); return pid

def get_pm(panel):
    pm = getattr(panel, "pixmap", None)
    pm = pm() if callable(pm) else pm
    if pm is None and hasattr(panel, "pixmaps"): pm = panel.pixmaps.get("front")
    return pm

def img_bytes(pm):
    if pm is None or pm.isNull(): return None
    im = pm.toImage(); return bytes(im.constBits().asarray(im.sizeInBytes()))

def add_record_scenario(tag, with_fields):
    print('ADD start', tag, flush=True); db = TMP / f"add_{tag}.db"; make_db(db, with_fields)
    w = MainWindow(BackendAPI(db)); w.show(); spin(100)
    w.ribbon.select("База данных"); spin(50)
    try:
        if hasattr(w.records, "select_id"): w.records.select_id(None)
    except Exception: pass
    w.records.view.clearSelection(); spin(50)
    empty = img_bytes(get_pm(w.preview_panel))
    vals = {"last_name": "Щёголева", "first_name": "Юлия", "faculty": "Химфак «Ё»"}
    FILL.update(vals); n0 = len(w.api.list_persons()) if hasattr(w.api, "list_persons") else None
    w.act_card_add.trigger(); spin(600)
    persons = w.api.list_persons()
    new = [p for p in persons if p["fields"].get("last_name") == "Щёголева"]
    chk(f"ADD[{tag}] запись сохранена с кириллицей в ключах шаблона", new and all(new[0]["fields"].get(k) == v for k, v in vals.items()),
        new[0]["fields"] if new else f"записей {n0}→{len(persons)}; ключи: {[p['fields'] for p in persons[-1:]]}")
    spin(300); after = img_bytes(get_pm(w.preview_panel))
    diff = None if (empty is None or after is None) else sum(a != b for a, b in zip(empty, after))
    chk(f"ADD[{tag}] превью после «Добавить» отличается от пустого шаблона", after is not None and (empty is None or diff > 200), f"diff_bytes={diff}, empty={'нет' if empty is None else 'есть'}")
    t = w.preview_panel.fields; vals_shown = [(t.item(r, 0).text() if t.item(r, 0) else "", t.item(r, 1).text() if t.item(r, 1) else "") for r in range(t.rowCount())]
    ok = all(any(v == s for _, s in vals_shown) for v in vals.values())
    chk(f"ADD[{tag}] панель «Поле шаблона | Значение из БД» показывает значения", ok, vals_shown)
    if after is not None: get_pm(w.preview_panel).save(str(HERE.parent / f"click_add_{tag}.png"))
    w.close(); spin(50)

# --- 1. каждый QAction ---
db = TMP / "all.db"; PID = make_db(db)
w = MainWindow(BackendAPI(db)); w.show(); spin(150)
places = dict(w.ribbon.places)
# D30 (причина в скрипте): act_disconnect/act_connect/act_card_delete раньше шли в середине и убирали запись/БД,
# после чего записевые действия честно становились disabled. Разрушающие действия — в конец.
LATE = ("act_card_delete", "act_connect", "act_disconnect", "act_compact")
acts = [a for a in places if a.objectName() not in LATE + ("act_exit",)] + [a for n in LATE for a in places if a.objectName() == n]
extra = [a for a in w.findChildren(QAction) if a.objectName().startswith("act_align_")]
skipped = []
for a in acts + extra + [w.act_exit] if hasattr(w, "act_exit") else []:
    tab = places.get(a, ("Рисование", ""))[0]
    try:
        w.ribbon.select(tab); spin(30)
        if tab == "База данных":
            # предыдущие act_display_printed/фильтр могли скрыть все строки — вернуть «Все» и выделить запись
            if a.objectName() not in ("act_display_printed", "act_display_unprinted"): (w.findChild(QAction, "act_display_all") or QAction()).trigger(); spin(30)
            if a.objectName() not in ("act_filter_apply", "act_filter_reset"): w._select_person(PID) if hasattr(w, "_select_person") else w.records.view.selectRow(0)
        else:
            le = w.layout_editor; items = [i for i in le.scene.items() if i.flags() & i.GraphicsItemFlag.ItemIsSelectable]
            if items and a.objectName() != "act_paste": le.scene.clearSelection(); items[0].setSelected(True)
        spin(30)
        if not a.isEnabled(): skipped.append(a.objectName()); continue
        n = len(EXC); OPENED.clear()
        a.trigger(); spin(250)
        if a.isCheckable() and a.objectName() not in ("act_display_all", "act_display_printed", "act_display_unprinted"): a.trigger(); spin(80)
        chk(f"ACT {a.objectName()} «{a.text()}»", len(EXC) == n, (EXC[-1] if len(EXC) > n else f"диалоги: {OPENED or '—'}"))
    except Exception:
        chk(f"ACT {a.objectName()}", False, traceback.format_exc()[-600:])
chk("Все действия ленты были доступны (не disabled) в подготовленном состоянии", not skipped, skipped or "все нажаты")

# --- 2. диалоги напрямую (если не открылись через действия) ---
w2 = MainWindow(BackendAPI(db)); w2.show(); spin(100)
for name, title in (("act_settings", "Настройки"), ("act_field_manager", "Настр. поля"), ("act_card_add", "Карта: добавить"),
                    ("act_card_edit", "Карта: изменить"), ("act_import", "Импорт"), ("act_export", "Экспорт"),
                    ("act_position", "Положение"), ("act_queue", "Очередь печати"), ("act_about", "О программе")):
    a = getattr(w2, name, None) or w2.findChild(QAction, name)
    if a is None: chk(f"DLG {title}", False, f"нет {name}"); continue
    w2.ribbon.select(places.get(getattr(w, name), ("Главная",))[0] if hasattr(w, name) else "Главная"); spin(30)
    if name.startswith("act_card") or name in ("act_queue",): w2._select_person(PID) if hasattr(w2, "_select_person") else w2.records.view.selectRow(0)
    else:
        le = w2.layout_editor; its = [i for i in le.scene.items() if i.flags() & i.GraphicsItemFlag.ItemIsSelectable]
        if its: le.scene.clearSelection(); its[0].setSelected(True)
    spin(30); OPENED.clear(); n = len(EXC); a.trigger(); spin(400)
    chk(f"DLG {title} открылся и закрылся без исключений", OPENED and len(EXC) == n, (EXC[-1] if len(EXC) > n else OPENED or "диалог не открылся (действие disabled или без диалога)"))
w2.close()

chk("D22: act_capture отсутствует (захват камерой — внутри «добавить фото»)", w2.findChild(QAction, "act_capture") is None, "нет act_capture" if w2.findChild(QAction, "act_capture") is None else "act_capture есть")

# --- 2b. D22: «добавить фото» → камера/файл внутри RecordForm ---
def photo_scenario():
    from PyQt6.QtGui import QImage, QColor
    db = TMP / "photo.db"; pid = make_db(db)
    w = MainWindow(BackendAPI(db)); w.show(); spin(100); w.ribbon.select("База данных"); w._select_person(pid); spin(50)
    st = {}
    def act():
        f = QApplication.activeModalWidget()
        if f is None or type(f).__name__ != "RecordForm": QTimer.singleShot(50, act); return
        try:
            pb = f.photo_block; st["has_camera"] = pb.has_camera
            st["shoot_no_cam"] = pb.shoot()            # offscreen камеры нет — не должно падать
            img = QImage(80, 100, QImage.Format.Format_RGB32); img.fill(QColor("green"))
            st["captured"] = pb.set_captured(img); st["retake_enabled"] = pb.b_retake.isEnabled()
            f.save() if hasattr(f, "save") else f.accept()
        except Exception: st["exc"] = traceback.format_exc()[-600:]; f.reject()
    HOLD.append(1); n = len(EXC); QTimer.singleShot(80, act); (w.findChild(QAction, "act_card_edit")).trigger(); spin(600); HOLD.clear()
    p = next(x for x in w.api.list_persons() if x["id"] == pid)
    chk("D22 «добавить фото»: снимок через PhotoBlock сохраняется в photos/ без исключений",
        "exc" not in st and len(EXC) == n and st.get("captured") and (p["photo_path"] or "").startswith("photos/") and (db.parent / p["photo_path"]).is_file(),
        st.get("exc") or (EXC[-1] if len(EXC) > n else f"{st}, photo_path={p['photo_path']}"))
    w.close(); spin(50)
try: photo_scenario()
except Exception: chk("D22 сценарий фото без исключений", False, traceback.format_exc()[-600:])

# --- 3. добавить запись → текст на превью ---
for tag, wf in (("поля_есть", True), ("D19_старая_БД_без_person_fields", False)):
    try: add_record_scenario(tag, wf)
    except Exception: chk(f"ADD[{tag}] сценарий без исключений", False, traceback.format_exc()[-800:])

tm.stop()
print(f"\nИТОГО: {sum(r[1] for r in RES)}/{len(RES)} PASS; исключений в слотах: {len(EXC)}; tmp={TMP}")
json.dump([dict(name=a, ok=b, ev=c) for a, b, c in RES], open(HERE.parent / "e2e_click_all_results.json", "w"), ensure_ascii=False, indent=1)
os._exit(0 if all(r[1] for r in RES) else 1)
