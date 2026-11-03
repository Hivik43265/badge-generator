"""QA этап 10: пустой шаблон, barcode/qr/line, миграция v3, фон, типы CHECK, UI. Только чтение продукта."""
import os, sys, re, json, sqlite3, subprocess, warnings, tempfile, pathlib, shutil
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
QA = ROOT / "reports/qa"; TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa10_"))
from PIL import Image
import zxingcpp
from badge_backend import api, db as bdb
from badge_backend.render import barcode as BC, qr as QRM
RES = []
def chk(n, ok, ev): RES.append((n, bool(ok), ev)); print("PASS" if ok else "FAIL", "|", n, "|", ev)
def W(fn, *a, **k):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always"); r = fn(*a, **k)
    return r, [str(x.message) for x in w]
def el(t, x, y, w, h, id=1, **kw):
    st = kw.pop("style", {}); return {"id": id, "type": t, "x": x, "y": y, "w": w, "h": h, "side": "front", "z_order": kw.pop("z", 0), "style_json": json.dumps(st), **kw}
def g(cmd): return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT).stdout.strip()

# 1
con = api.connect(str(TMP / "fresh.db"))
n_el = con.execute("SELECT count(*) FROM template_elements").fetchone()[0]; uv = con.execute("PRAGMA user_version").fetchone()[0]
nbg = con.execute("SELECT count(*) FROM template_backgrounds").fetchone()[0]
chk("1a Свежая БД: 0 template_elements, user_version=3", n_el == 0 and uv == 3, f"elements={n_el}, backgrounds={nbg}, user_version={uv}")
seed = g(["grep", "-rnE", "INSERT INTO template_elements|build_demo\\(|apply_layout\\(", "--include=*.py", "--include=*.sql", "badge_backend"])
seed_calls = [l for l in seed.splitlines() if not re.search(r"demo\.py:\d+:\s*(def |return apply_layout)|db\.py:\d+:.*SELECT \{cols\} FROM _te_old|api\.py:\d+:.*VALUES \(\{", l)]  # копирование при миграции и CRUD create_element — не seed
chk("1b Нет seed-макетов в badge_backend/ и миграциях", not seed_calls and "INSERT" not in bdb.SCHEMA.upper().split("CREATE TRIGGER")[0], f"вызовы вне определений: {seed_calls or 'нет'}")
hits = g(["grep", "-rlE", "Гость|ООО «Пример»|ООО Пример", ".", "--exclude-dir=.venv", "--exclude-dir=__pycache__", "--exclude-dir=.pytest_cache", "--exclude-dir=.git"]).splitlines()
# Исключение: юнит-assert element_caption в ui/smoke_test.py (строка «Гость» — тестовое значение, не демо-данные)
def _only_unit_assert(h):
    if h != "./ui/smoke_test.py": return False
    lines = [l for l in open(h, encoding="utf-8") if re.search(r"Гость|ООО «Пример»|ООО Пример", l)]
    return bool(lines) and all(l.lstrip().startswith("assert element_caption(") for l in lines)
bad = [h for h in hits if not (h.startswith("./tests/") or h.startswith("./reports/") or _only_unit_assert(h))]
chk("1c «Гость»/«ООО Пример» только в tests/ и reports/", not bad, f"вне tests/reports: {bad or 'нет'}; всего файлов {len(hits)}")

# 2
img, wr = W(api.render_card_db, con, None, "front")
ext = img.convert("L").getextrema()
chk("2a Пустой шаблон → белое 1011×638", img.size == (1011, 638) and ext == (255, 255), f"size={img.size}, extrema(L)={ext}")
pid = api.create_person(con, {"last_name": "Пустов"}); api.set_print_mark(con, [pid])
try:
    pn, w1 = W(api.export_png, con, out_dir=TMP / "png", allow_missing_photo=True)
    pd, w2 = W(api.export_pdf, con, out_path=TMP / "e.pdf", allow_missing_photo=True)
    from PyQt6.QtWidgets import QApplication; from PyQt6.QtPrintSupport import QPrinter
    app = QApplication.instance() or QApplication([])
    pr = QPrinter(); pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(str(TMP / "p.pdf"))
    pp, w3 = W(api.print_cards, con, pr, allow_missing_photo=True)
    ok = all(getattr(r, "empty_template", False) and r.warnings for r in (pn, pd, pp)) and w1 and w2 and w3
    ev = f"PNG: {len(pn)} файлов, empty_template={pn.empty_template}, warnings={pn.warnings}; PDF: {pd.empty_template}; печать: {int(pp)} стр., {pp.empty_template}; RuntimeWarning: {len(w1)}/{len(w2)}/{len(w3)}"
except Exception as e: ok, ev = False, repr(e)
chk("2b Экспорт PNG/PDF и печать пустого шаблона: warning, без исключения", ok, ev)

# 3 barcode
def mod_px(fmt, val, w, h, st=None):
    st = {"format": fmt, "show_text": False, **(st or {})}
    tile, wn = W(BC.render_barcode, w, h, val, st)
    code, _ = BC.modules(fmt, val); m, x0 = BC.layout(len(code), w, int(st.get("quiet_zone", BC.DEFAULT_QUIET)))
    row = [tile.convert("L").getpixel((x, h // 2)) < 128 for x in range(w)]
    runs, cur, n = [], row[0], 0
    for b in row:
        if b == cur: n += 1
        else: runs.append((cur, n)); cur, n = b, 1
    runs.append((cur, n)); bars = [n for b, n in runs[1:-1]]
    integer = m >= 1 and all(r % m == 0 for r in bars)
    big = Image.new("RGB", (w, h), "white"); big.paste(tile, (0, 0), tile)
    dec = zxingcpp.read_barcodes(big)
    return m, integer, [(str(d.format), d.text) for d in dec], wn, big
for fmt, val, exp in (("code128", "BG-000123", "BG-000123"), ("ean13", "460123456789", None)):
    m, integer, dec, wn, big = mod_px(fmt, val, 600, 150)
    if exp is None: exp = val + str(BC.ean13_checksum(val))
    big.save(QA / f"s10_{fmt}.png")
    chk(f"3 {fmt}: модуль целый px, декодируется в исходное", integer and any(t == exp for _, t in dec) and not wn, f"модуль={m}px, все полосы кратны модулю={integer}, decode={dec}, ожидалось {exp!r}")
r = None
try: (r, wn) = W(api.render_card, None, [el("barcode", 10, 10, 600, 150, static_value="4601234567890", style={"format": "ean13"})], "front"); ok = bool(wn)
except Exception as e: ok, wn = False, [repr(e)]
chk("3c Невалидный EAN-13 (контрольная цифра) → warning без исключения", ok and r is not None, f"warnings={wn}")
im, wn = W(api.render_card, None, [el("barcode", 10, 10, 600, 150, static_value="BG-1", style={"symbology": "ean13"})], "front")
chk("3d UI-ключ style['symbology'] принимается (ean13 + не цифры → warning)", any("EAN" in m for m in wn), f"warnings={wn}")

# 4 QR
qrok, ev = True, []
for lv in "LMQH":
    w, h = 300, 220
    tile, wn = W(QRM.render_qr, w, h, "https://example.com/badge/42", {"error_correction": lv})
    a = tile.getchannel("A").getbbox(); side = (a[2] - a[0], a[3] - a[1])
    n = len(QRM.matrix("https://example.com/badge/42", lv)) + 2 * QRM.DEFAULT_BORDER
    m = min(w, h) // n
    big = Image.new("RGB", (w, h), "white"); big.paste(tile, (0, 0), tile)
    dec = zxingcpp.read_barcodes(big); ecl = [getattr(d, "ec_level", "?") for d in dec]
    ok = side[0] == side[1] == m * n and side[0] <= min(w, h) and dec and dec[0].text == "https://example.com/badge/42" and not wn
    qrok &= bool(ok); ev.append(f"{lv}: {side[0]}×{side[1]} px = {n} мод×{m}px, decode={[d.text for d in dec]}, ec={ecl}")
    if lv == "H": big.save(QA / "s10_qr_H.png")
chk("4 QR L/M/Q/H: квадрат в min(w,h), модуль целый, декодируется", qrok, "; ".join(ev))

# 5 line
els = [el("line", 50, 100, 400, 0, 1, style={"stroke": "#FF0000", "stroke_width": 4}), el("line", 600, 50, 0, 300, 2, style={"stroke": "#00AA00", "stroke_width": 4}),
       el("line", 950, 600, -300, -200, 3, style={"stroke": "#0000FF", "stroke_width": 4})]
im, wn = W(api.render_card, None, els, "front"); px = im.load()
hz = px[250, 100][0] > 200 and px[250, 100][1] < 80; vt = px[600, 200][1] > 120 and px[600, 200][0] < 80
dg = px[800, 500][2] > 200 and px[800, 500][0] < 80
chk("5a line: горизонтальная, вертикальная, диагональ с отрицательными w/h", hz and vt and dg and not wn, f"(250,100)={px[250,100]} (600,200)={px[600,200]} (800,500)={px[800,500]}")
im.save(QA / "s10_lines.png")
try: api.create_element(con, "line", 10, 10, 0, 0); ok, ev = False, "вставлено"
except sqlite3.IntegrityError as e: ok, ev = True, f"IntegrityError: {e}"
try: i2 = api.create_element(con, "line", 10, 10, -50, -20); api.delete_element(con, i2); neg = "w=-50,h=-20 принято"
except Exception as e: neg = f"отклонено: {e}"
chk("5b line w=h=0 отклоняется (отрицательные w/h разрешены)", ok and "принято" in neg, f"{ev}; {neg}")
# UI-стиль линии
import ast
ui_src = (ROOT / "ui/layout_editor.py").read_text(encoding="utf-8")
DS = ast.literal_eval(re.search(r"DEFAULT_STYLE = (\{.*?\})\n[A-Z]", ui_src, re.S).group(1))
lst = DS["line"]; want = int(lst.get("stroke_width", lst.get("width", 1)))
im, _ = W(api.render_card, None, [el("line", 100, 300, 600, 0, 1, style=lst)], "front")
thick = sum(1 for y in range(290, 311) if im.getpixel((400, y)) != (255, 255, 255))
chk("5c Линия со стилем UI по умолчанию рисуется заданной толщиной", thick == want, f"UI DEFAULT_STYLE['line']={lst}; толщина по факту={thick}px, ожидалось {want}")

# 6 migration
def mk_old(ver):
    p = TMP / f"v{ver}.db"; c = sqlite3.connect(p)
    c.executescript("BEGIN;\n" + bdb.SCHEMA + "\nPRAGMA user_version=1;\nCOMMIT;")
    if ver == 2: c.execute("ALTER TABLE persons ADD COLUMN printed_at TEXT NULL"); c.execute("PRAGMA user_version=2")
    for i in (3, 7, 10): c.execute("INSERT INTO persons(id,fields_json,print_mark) VALUES (?,?,1)", (i, json.dumps({"last_name": f"P{i}"})))
    for i, t in ((5, "text"), (9, "rect"), (12, "qr"), (20, "barcode")):
        c.execute("INSERT INTO template_elements(id,type,x,y,w,h,static_value,style_json,z_order) VALUES (?,?,1,2,30,40,'v','{\"a\":1}',?)", (i, t, i))
    c.execute("INSERT INTO template_backgrounds(side,color) VALUES ('front','#ABCDEF')"); c.commit()
    snap = (c.execute("SELECT * FROM persons ORDER BY id").fetchall(), c.execute("SELECT * FROM template_elements ORDER BY id").fetchall())
    c.close(); return p, snap
for ver in (2, 1):
    p, (pb, eb) = mk_old(ver)
    c = api.connect(str(p)); c.row_factory = None
    pa = c.execute("SELECT " + ",".join(["id", "fields_json", "photo_path", "photo_config", "print_mark", "created_at", "updated_at"]) + " FROM persons ORDER BY id").fetchall()
    ea = c.execute("SELECT id,type,x,y,w,h,field_name,static_value,style_json,side,z_order FROM template_elements ORDER BY id").fetchall()
    v = c.execute("PRAGMA user_version").fetchone()[0]; sql = c.execute("SELECT sql FROM sqlite_master WHERE name='template_elements'").fetchone()[0]
    idx = c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='template_elements'").fetchall()
    fk = c.execute("PRAGMA integrity_check").fetchone()[0]; c.close()
    v2 = api.connect(str(p)).execute("PRAGMA user_version").fetchone()[0]
    ok = v == 3 and v2 == 3 and [tuple(r[:7]) for r in pb] == pa and [tuple(r) for r in eb] == ea and "'line'" in sql and idx and fk == "ok"
    chk(f"6 Миграция v{ver}→v3: persons/template_elements и id сохранены", ok, f"user_version {ver}→{v} (повторно {v2}); persons ids={[r[0] for r in pa]}, elements ids={[r[0] for r in ea]}; данные совпали={[tuple(r[:7]) for r in pb] == pa and [tuple(r) for r in eb] == ea}; индекс={idx}; integrity={fk}")

# 7 background
c = api.connect(":memory:"); bgp = TMP / "bg.png"; Image.new("RGB", (50, 50), (200, 0, 0)).save(bgp)
api.set_background(c, "front", "#00FF00", str(bgp)); api.create_element(c, "rect", 100, 100, 200, 200, style={"fill": "#0000FF"})
im, _ = W(api.render_card_db, c, None, "front")
chk("7 Фон template_backgrounds рисуется под элементами", im.getpixel((10, 10)) == (200, 0, 0) and im.getpixel((200, 200)) == (0, 0, 255),
    f"вне элемента={im.getpixel((10,10))} (картинка фона), внутри rect={im.getpixel((200,200))} (элемент поверх)")
api.set_background(c, "back", "#00FF00"); imb, _ = W(api.render_card_db, c, None, "back")
chk("7b Фон-цвет без картинки", imb.getpixel((500, 300)) == (0, 255, 0), f"{imb.getpixel((500,300))}")

# 8 all CHECK types
c = api.connect(":memory:"); sql = c.execute("SELECT sql FROM sqlite_master WHERE name='template_elements'").fetchone()[0]
types = re.findall(r"'(\w+)'", re.search(r"type IN \(([^)]*)\)", sql).group(1))
logo = TMP / "logo.png"; Image.new("RGB", (80, 80), "red").save(logo)
pid = api.create_person(c, {"last_name": "Иванов", "code": "BG-1"})
spec = {"text": dict(static_value="Текст"), "field": dict(field_name="last_name"), "photo": {}, "image": dict(static_value=str(logo)),
        "rect": dict(style={"fill": "#EEE"}), "qr": dict(static_value="QR-1"), "barcode": dict(field_name="code"), "line": {}}
y = 0; miss = [t for t in types if t not in spec]
for t in types:
    api.create_element(c, t, 10 + (y % 3) * 330, 10 + (y // 3) * 210, 300 if t != "line" else 300, 200 if t != "line" else 0, **spec.get(t, {})); y += 1
im, wn = W(api.render_card_db, c, pid, "front")
im.save(QA / "s10_all_types.png")
bad = [m for m in wn if re.search(r"reserved|зарезерв|не поддерживается|пропущен", m, re.I)]
chk("8 Все типы CHECK рендерятся без warning «reserved/пропущен»", not bad and not miss, f"types={types}; warnings={wn}")

# 9 UI
sq = g(["grep", "-rnEi", r"import sqlite3|\.execute\(|\b(SELECT|INSERT|UPDATE|DELETE)\b .*(FROM|INTO|SET)|PRAGMA", "--include=*.py", "ui", "--exclude=smoke_test.py"])
chk("9a Нет SQL в ui/ (кроме smoke_test)", not sq, sq or "grep пусто")
src = (ROOT / "ui/layout_editor.py").read_text(encoding="utf-8")
tools = dict((k, t) for k, _, t in re.findall(r'\("(\w+)", "([^"]+)", "?(\w+|None)"?\)', src.split("DEFAULT_SIZE")[0]))
missing = [t for t in types if t not in tools.values()]
chk("9b UI: кнопка добавления для каждого типа + удалить + z_order", not missing and "act_delete" in src and "move_z(+1)" in src and "move_z(-1)" in src,
    f"TOOLS→types={sorted(set(tools.values()) - {'None'})}; нет кнопки для {missing or '—'}; act_delete/«Выше»/«Ниже» есть")
print(f"\nИТОГО: {sum(r[1] for r in RES)}/{len(RES)} PASS; tmp={TMP}")
json.dump([dict(name=a, ok=b, ev=c) for a, b, c in RES], open(QA / "e2e_stage10_results.json", "w"), ensure_ascii=False, indent=1)
