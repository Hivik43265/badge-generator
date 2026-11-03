"""QA этап 12 (Контролёр, независимо от smoke_test). Запуск:
QT_QPA_PLATFORM=offscreen .venv/bin/python reports/qa/e2e_stage12.py"""
import os, sys, re, ast, json, tempfile, pathlib, collections
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]; QA = ROOT / "reports/qa"; sys.path.insert(0, str(ROOT))
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QAbstractButton, QToolButton, QMenuBar, QToolBar, QMenu
from PyQt6.QtGui import QAction
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa12_"))
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(TMP / "cfg"))
app = QApplication([])
from badge_backend import api, db as bdb
from ui.backend_api import BackendAPI
from ui.main_window import MainWindow
RES = []
def chk(n, ok, ev=""): RES.append((n, bool(ok), str(ev))); print(("PASS" if ok else "FAIL"), "|", n, "|", ev)

# --- реестр 58 действий из stage-12-actions.md §1 ---
md = (ROOT / "reports/stage-12-actions.md").read_text(encoding="utf-8")
sec1 = md.split("## 2.")[0]
rows = [l for l in sec1.splitlines() if re.match(r"\|\s*\d+\s*\|", l) and "~~" not in l.split("|")[2]]  # этап 13: строки «~~…~~ удалено» (D22) не считаются
exp = {}
for l in rows:
    num = int(l.split("|")[1]); names = re.findall(r"`(act_\w+\*?)`", l.split("|")[2]); exp[num] = names[0]
# Изменение ожиданий (этап 13, решение Архитектора D22): act_capture удалён → 57 действий.
REMOVED = {"act_capture"}
exp = {k: v for k, v in exp.items() if v not in REMOVED}
N_ACT = 57
chk(f"1.0 Реестр: {N_ACT} действий (58 − act_capture, D22)", len(exp) == N_ACT, f"{len(exp)}")

w = MainWindow(BackendAPI(TMP / "qa.db")); w.show(); app.processEvents()
acts = [a for a in w.findChildren(QAction) if a.objectName().startswith("act_")]
byname = collections.Counter(a.objectName() for a in acts)
dupname = [n for n, c in byname.items() if c > 1]
chk("1.1 objectName act_* уникальны", not dupname, dupname or "нет")
missing = []
for num, n in exp.items():
    if n == "act_display_*":
        if len([k for k in byname if k.startswith("act_display_")]) != 3: missing.append(n)
    elif n not in byname: missing.append(n)
chk(f"1.2 Все {N_ACT} действий существуют как QAction", not missing, missing or "все есть")
extra = sorted(k for k in byname if k not in exp.values() and not k.startswith(("act_display_", "act_align_")))
chk("1.3 Нет лишних act_* вне реестра (act_capture отсутствует)", not extra and "act_capture" not in byname, extra or "нет")
top = [a for a in acts if not a.objectName().startswith("act_align_")]
texts = collections.Counter(a.text().replace("&", "") for a in top)
# Правило дублей (Архитектор, этап 13): дубль — только отдельный QAction или отдельный обработчик той же функции; повтор подписи — не дубль.
chk("1.4 Подписи QAction (информ.; повтор подписи не дубль)", True, [t for t, c in texts.items() if c > 1] or "нет")
places = w.ribbon.places
in_ribbon = collections.Counter(a.objectName() for a in places)
not_placed = [n for n in exp.values() if n not in ("act_display_*", "act_filter_apply") and in_ribbon.get(n, 0) != 1]
chk("1.5 Каждое действие ровно в одном месте ленты", not not_placed, not_placed or "ok")
fb = [b for b in w.records.filter.findChildren(QToolButton) if b.defaultAction() is getattr(w, "act_filter_apply", None)]
chk("1.6 act_filter_apply: одна кнопка в блоке фильтра, не в ленте", len(fb) == 1 and in_ribbon.get("act_filter_apply") == 1 and places[w.act_filter_apply][1] == "Блок фильтра", f"кнопок={len(fb)}, место={places.get(w.act_filter_apply)}")
chk("1.7 Нет QMenuBar с пунктами и QToolBar", not w.menuBar().actions() and not w.findChildren(QToolBar),
    f"menuBar={len(w.menuBar().actions())}, toolbars={len(w.findChildren(QToolBar))}")
# 1.8/1.9 (новое правило Архитектора): каждый QAction — уникальный объект; кнопки вне ленты не имеют своих
# обработчиков функций действий — только setDefaultAction(<QAction>) или clicked→<action>.trigger.
ids_ = collections.Counter(id(a) for a in acts)
objs = collections.defaultdict(set)
for a in acts: objs[a.objectName()].add(id(a))
chk("1.8a QAction — уникальные объекты (один объект на objectName)", all(len(v) == 1 for v in objs.values()) and all(c == 1 for c in ids_.values()),
    [n for n, v in objs.items() if len(v) > 1] or "ok")
fb_ok = []
for b in w.findChildren(QToolButton):
    da = b.defaultAction()
    if da is not None and da.objectName().startswith("act_") and da not in acts: fb_ok.append(da.objectName())
chk("1.8b Кнопки с defaultAction ссылаются на существующие QAction окна", not fb_ok, fb_ok or "ok")
src_ui = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "ui").glob("*.py") if p.name not in ("smoke_test.py", "qa_click_all.py", "self_test.py")}
mw_src = src_ui.get("main_window.py", "")
slot_of = dict(re.findall(r'A\("(act_\w+)",\s*"[^"]*",\s*self\.(\w+)', mw_src))
dup_handlers = []
for f, s_ in src_ui.items():
    for m in re.finditer(r"\.(?:clicked|triggered|pressed)\.connect\(([^\n]*)\)", s_):
        tgt = m.group(1)
        if ".trigger" in tgt: continue
        for act, slot in slot_of.items():
            if re.search(rf"\b{slot}\b", tgt) and not (f == "main_window.py" and "A(" in s_[max(0, m.start()-200):m.start()]):
                dup_handlers.append(f"{f}:{s_[:m.start()].count(chr(10))+1} {tgt.strip()} (функция {act})")
chk("1.8c Нет отдельных обработчиков, повторяющих функции QAction (кнопки → action.trigger/setDefaultAction)", not dup_handlers, dup_handlers or "нет")
# 1.9: кнопка «Менеджер полей…» в диалоге импорта — тот же QAction act_field_manager
dl = src_ui.get("dialogs.py", "")
# Основной путь: в диалоге импорта QToolButton.setDefaultAction(<act_field_manager главного окна>).
m_def = re.search(r'act\s*=\s*getattr\(parent,\s*"act_field_manager"[^\n]*\n(?:[^\n]*\n){0,3}?[^\n]*(self\.\w+)\.setDefaultAction\(act\)', dl)
cap = re.search(re.escape(m_def.group(1)) + r'\.setText\("([^"]+)"\)', dl) if m_def else None
chk("1.9 Импорт: кнопка «Менеджер полей…» = QAction act_field_manager (setDefaultAction), не свой обработчик", bool(m_def),
    f"{m_def.group(1)}.setDefaultAction(act_field_manager)" if m_def else "нет setDefaultAction(act_field_manager)")
chk("1.9b Подпись кнопки импорта по эталону «Менеджер полей…» (не «Открыть менеджер полей…»)", cap and cap.group(1) == "Менеджер полей…" and "Открыть менеджер полей" not in dl,
    cap.group(1) if cap else "подписи нет")
fb_own = re.search(r'QPushButton\("Менеджер полей…"\);[^\n]*clicked\.connect', dl)
chk("1.9c (информ.) запасная ветка без родительского QAction — своя кнопка (диалог вне MainWindow)", True, "есть" if fb_own else "нет")
# контекстные меню — только те же QAction
w.ribbon.select("База данных"); app.processEvents()
cm_bad = []
for name in dir(w):
    v = getattr(w, name, None)
    if isinstance(v, QMenu):
        for a in v.actions():
            if not a.isSeparator() and a not in places and not a.objectName().startswith("act_align_"): cm_bad.append(f"{name}:{a.text()}")
chk("1.10 Меню-атрибуты окна содержат только QAction ленты", not cm_bad, cm_bad or "ok")
old = [n for n in ("act_save", "act_front", "act_back", "act_printed_filter", "act_add_element", "act_text", "act_editor", "act_main",
                   "act_full_preview", "act_mark_all", "act_unmark_all", "act_rec_add", "act_rec_edit", "act_rec_del", "act_up", "act_down", "act_delete")
       if re.search(rf"\b{n}\b", "\n".join(src_ui.values()))]
chk("1.11 Старые дубли (имена из §2) удалены из ui/", not old and not (ROOT / "ui/preview.py").exists() and "make_icon" not in src_ui.get("main_view.py", "")
    and "QMenuBar" not in src_ui["main_window.py"] and "QToolBar" not in src_ui["main_window.py"], old or "ok")
le_src = src_ui["layout_editor.py"]; rt_src = src_ui["records_table.py"]; rf_src = src_ui["record_form.py"]
chk("1.12 §2 #14/#18/#19/#24: чекбокс рендера, printed_box, строка поиска, флажок печати в форме удалены",
    not re.search(r'QCheckBox\([^)]*рендер', le_src, re.I) and "printed_box" not in rt_src and "col_box" not in rt_src and not re.search(r'QCheckBox\([^)]*печат', rf_src, re.I), "ok")
chk("1.15 (=D13, статически) Колонка-чекбокс «Печать» в таблице — второй путь к set_print_mark мимо act_queue_toggle", "set_print_mark" not in rt_src,
    "records_table.py: setData → api.set_print_mark (чекбокс в колонке)" if "set_print_mark" in rt_src else "нет")
chk("1.13 §2 #16: кнопка «Применить» в панели свойств удалена", "QPushButton(\"Применить\")" not in le_src,
    "ui/layout_editor.py:203 apply_btn есть" if "QPushButton(\"Применить\")" in le_src else "нет")
# --- решения Архитектора по D13–D16 ---
rt_ast = ast.parse(rt_src)
setdata = [n for n in ast.walk(rt_ast) if isinstance(n, ast.FunctionDef) and n.name == "setData"]
sd_src = ast.get_source_segment(rt_src, setdata[0]) if setdata else ""
chk("D13 Чекбокс «Печать» таблицы — только через act_queue_toggle", "set_print_mark" not in rt_src and (not setdata or "queue_toggle" in sd_src or "CheckStateRole" not in sd_src),
    "records_table.py: setData → api.set_print_mark напрямую" if "set_print_mark" in rt_src else "ok")
ms = src_ui["main_view.py"]; pd = re.search(r"class PositionDialog.*?(?=\nclass |\Z)", ms, re.S)
pd_src = pd.group(0) if pd else ""
chk("D14 Диалог «Положение» без кнопок выравнивания", pd and "QPushButton" not in pd_src and "ALIGN" not in pd_src and "def align" not in pd_src,
    "PositionDialog: кнопки ALIGN есть" if "ALIGN" in pd_src else ("нет PositionDialog" if not pd else "ok"))
fm = re.search(r"class FieldManager.*?(?=\nclass |\Z)", ms, re.S); fm_src = fm.group(0) if fm else ""
# D16 (решение Архитектора, по эталону Ивана): подпись «Печать», подсказка «Печать списка полей»
pb_cap = re.search(r'QPushButton\("(Печать[^"]*)"\)', fm_src)
chk("D16 Менеджер полей: кнопка «Печать», tooltip «Печать списка полей»", pb_cap and pb_cap.group(1) == "Печать" and 'setToolTip("Печать списка полей")' in fm_src,
    f"подпись «{pb_cap.group(1) if pb_cap else '—'}», tooltip={'есть' if 'setToolTip(\"Печать списка полей\")' in fm_src else 'нет'}")
mock_dir = ROOT / "ui/mockup"
chk("D15/1.14 ui/mockup отсутствует (второй вариант ленты)", not mock_dir.exists(), sorted(p.name for p in mock_dir.glob("*.py")) if mock_dir.exists() else "нет")

# --- 3. 1024 px: каждая кнопка QAction ленты целиком видна в видимой области вкладки ---
from PyQt6.QtCore import QRect, QPoint
w.resize(1024, 700); app.processEvents(); res = []
for i in range(w.ribbon.count()):
    w.ribbon.setCurrentIndex(i); app.processEvents()
    tab = w.ribbon.tabText(i); sc = w.ribbon.widget(i); vp = sc.viewport() if hasattr(sc, "viewport") else sc
    vr = QRect(vp.mapTo(w, QPoint(0, 0)), vp.size()) & QRect(QPoint(0, 0), w.size())
    w.grab().save(str(QA / f"s12_1024_tab{i+1}.png"))
    bad = []
    for act, (t, grp) in places.items():
        if t != tab or grp == "Блок фильтра": continue
        btn = w.ribbon.buttons.get(act)
        if btn is None and hasattr(act, "requestWidget"):   # QWidgetAction
            btn = act.defaultWidget() or next(iter(act.createdWidgets()), None)
        if btn is None: bad.append(f"{act.objectName()}: нет виджета"); continue
        br = QRect(btn.mapTo(w, QPoint(0, 0)), btn.size())
        if not btn.isVisible(): bad.append(f"{act.objectName()}: не isVisible")
        elif not vr.contains(br): bad.append(f"{act.objectName()}({grp}): вне видимой области x={br.left()}..{br.right()} > {vr.right()}")
    res.append((tab, bad))
chk("3.1 1024 px: все кнопки QAction ленты целиком в видимой области, isVisible", w.width() <= 1024 and all(not r[1] for r in res),
    [r for r in res if r[1]] or "все вкладки ok")
# 3.3 подписи кнопок не обрезаны (высота/ширина ≥ sizeHint) при 1024 px
w.resize(1024, 700); clip = []
for i in range(w.ribbon.count()):
    w.ribbon.setCurrentIndex(i); app.processEvents()
    for act, b in w.ribbon.buttons.items():
        if b.isVisible() and (b.height() + 3 < b.sizeHint().height() or b.width() + 3 < b.sizeHint().width()):
            clip.append(f"{w.ribbon.tabText(i)}/{act.objectName()}: {b.width()}×{b.height()} < {b.sizeHint().width()}×{b.sizeHint().height()} ({act.iconText()!r})")
chk("3.3 1024 px: подписи кнопок ленты не обрезаны (допуск 3 px)", not clip, clip or "ok")

# 3.2 свёрнутые группы «<группа> ▾»: те же QAction, без новых обработчиков
R = w.ribbon; rec0 = {a: a.receivers(a.triggered) for a in places}; bad32 = []; ncol = 0
if hasattr(R, "groups") and hasattr(R, "relayout"):
    for tab in R.groups:
        R.relayout(tab, avail=500)
        for g in R.groups[tab]:
            if not g.collapsed: continue
            ncol += 1; ma = [a for a in g.menu.actions() if not a.isSeparator()]
            if g.button.text() != f"{g.title} ▾": bad32.append(f"{tab}/{g.title}: подпись {g.button.text()!r}")
            exp_ = [a for a, pl in places.items() if pl == (tab, g.title)]
            if set(ma) != set(exp_): bad32.append(f"{tab}/{g.title}: меню≠QAction группы")
            if g.button.defaultAction() is not None and g.button.defaultAction() not in places: bad32.append(f"{tab}/{g.title}: новый QAction у кнопки")
        R.relayout(tab)
    rec1 = {a: a.receivers(a.triggered) for a in places}
    bad32 += [f"{a.objectName()}: обработчиков {rec0[a]}→{rec1[a]}" for a in places if rec0[a] != rec1[a]]
    acts2 = [a for a in w.findChildren(QAction) if a.objectName().startswith("act_")]
    if len(acts2) != len(acts): bad32.append(f"QAction act_*: {len(acts)}→{len(acts2)}")
chk("3.2 Свёрнутые группы «<группа> ▾» (avail=500): те же QAction, без новых обработчиков", ncol > 0 and not bad32, f"свёрнуто групп={ncol}; {bad32 or 'ok'}")

# --- 4. SQL в ui/ ---
sql_hits = []
for f, s in src_ui.items():
    t = ast.parse(s)
    for n in ast.walk(t):
        if isinstance(n, (ast.Import, ast.ImportFrom)) and any("sqlite" in (a.name or "") for a in n.names) or (isinstance(n, ast.ImportFrom) and "sqlite" in (n.module or "")):
            sql_hits.append(f"{f}:{n.lineno} import")
        if isinstance(n, ast.Attribute) and n.attr in ("execute", "executemany", "executescript"): sql_hits.append(f"{f}:{n.lineno} .{n.attr}")
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.search(r"\b(SELECT .* FROM|INSERT INTO|UPDATE \w+ SET|DELETE FROM|PRAGMA)\b", n.value, re.I):
            sql_hits.append(f"{f}:{n.lineno} SQL-строка")
chk("4.1 Нет SQL в ui/ (AST)", not sql_hits, sql_hits or "нет")

# --- 5. Backend v4 ---
c = api.connect(":memory:")
uv = c.execute("PRAGMA user_version").fetchone()[0]
te = c.execute("SELECT sql FROM sqlite_master WHERE name='template_elements'").fetchone()[0]
pf = [r[1] for r in c.execute("PRAGMA table_info(person_fields)")]
# Изменение ожиданий (этап 13, D24): схема v5 (data_type); версия берётся из LATEST
chk(f"5.1 схема: user_version == LATEST ({bdb.LATEST}) ≥ 5, ellipse в CHECK, person_fields.default_value + data_type",
    uv == bdb.LATEST >= 5 and "'ellipse'" in te and "default_value" in pf and "data_type" in pf, f"uv={uv}, LATEST={bdb.LATEST}, cols={pf}")
eid = api.create_element(c, "ellipse", 100, 100, 400, 200, style={"fill": "#FF0000", "stroke": "#0000FF", "stroke_width": 4})
im, _ = api.render_card_db(c, None, "front") if isinstance(api.render_card_db(c, None, "front"), tuple) else (api.render_card_db(c, None, "front"), None)
cen, corner = im.convert("RGB").getpixel((300, 200)), im.convert("RGB").getpixel((104, 104))
chk("5.2 Эллипс рендерится (центр заливка, угол рамки пуст)", cen == (255, 0, 0) and corner != (255, 0, 0), f"центр={cen}, угол={corner}")
im.save(QA / "s12_ellipse.png")
api.upsert_field(c, "dept", "Отдел"); api.set_field_default(c, "dept", "ДЕФОЛТ")
fd = {f["name"]: f.get("default_value") for f in api.list_fields(c)}
pid = api.create_person(c, {"last_name": "Иванов"})
snap = api.snapshot(c, [pid]) if hasattr(api, "snapshot") else None
txt_id = api.create_element(c, "field", 10, 10, 500, 60, field_name="dept")
els = bdb.load_elements(c, "front") if hasattr(bdb, "load_elements") else None
from badge_backend import render as BR
le_ = getattr(BR, "load_elements", None) or getattr(api, "load_elements", None)
els = le_(c, "front") if le_ else []
dv = [e.get("default_value") for e in els if e["id"] == txt_id]
chk("5.3 default_value сохранён и проброшен в элементы рендера", fd.get("dept") == "ДЕФОЛТ" and dv == ["ДЕФОЛТ"], f"fields={fd.get('dept')}, el={dv}")
# пиксельно: с дефолтом и без — отличаются
r1 = api.render_card_db(c, pid, "front"); r1 = r1[0] if isinstance(r1, tuple) else r1
api.set_field_default(c, "dept", None)
r2 = api.render_card_db(c, pid, "front"); r2 = r2[0] if isinstance(r2, tuple) else r2
chk("5.4 default_value реально рисуется для пустого поля", r1.tobytes() != r2.tobytes(), "рендер с/без default различается")
cyc = []
for t, kw in (("text", dict(static_value="Статика")), ("barcode", dict(static_value="123")), ("qr", dict(static_value="Q"))):
    i = api.create_element(c, t, 10, 300, 300, 100, **kw)
    a = api.link_field(c, i, "dept"); e1 = next(e for e in api.list_elements(c, "front") if e["id"] == i)
    b = api.unlink_field(c, i, "X"); e2 = next(e for e in api.list_elements(c, "front") if e["id"] == i)
    d = api.link_field(c, i, "dept"); e3 = next(e for e in api.list_elements(c, "front") if e["id"] == i)
    links = api.list_field_links(c).get("dept", [])
    ok = a and b and d and e1["field_name"] == "dept" and not e2["field_name"] and e3["field_name"] == "dept" and any(l["element_id"] == i or l.get("id") == i for l in links)
    cyc.append((t, e1["type"], e2["type"], e3["type"], ok))
chk("5.5 link→unlink→link для text/barcode/qr", all(x[-1] for x in cyc), cyc)

print(f"\nИТОГО: {sum(r[1] for r in RES)}/{len(RES)} PASS; tmp={TMP}")
json.dump([dict(name=a, ok=b, ev=c_) for a, b, c_ in RES], open(QA / "e2e_stage12_results.json", "w"), ensure_ascii=False, indent=1)
