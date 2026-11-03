"""QA e2e: импорт→рендер→экспорт→печать. Только чтение продукта; вывод в reports/qa и /tmp."""
import os, sys, csv, json, re, subprocess, warnings, tempfile, shutil, pathlib, ast
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
QA = ROOT / "reports/qa"; TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa_")); SETS = ROOT / "data_tools/testdata/sets"
from PIL import Image
from badge_backend import api, demo
R = []
def chk(name, ok, ev): R.append((name, bool(ok), ev)); print(("PASS" if ok else "FAIL"), "|", name, "|", ev)
def W(fn, *a, **k):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always"); r = fn(*a, **k)
    return r, [str(x.message) for x in w]
def newdb(name):
    con = api.connect(str(TMP / f"{name}.db")); shutil.copy(SETS/"clean/photos/p1.jpg", TMP/"p1.jpg")
    os.chdir(TMP); demo.make_logo(TMP/"demo_logo.png"); demo.build_demo(con); return con

# 1 photo_config
pc = api.PHOTO_CONFIG_DEFAULT
r1, w1 = W(api.normalize, "1;2;1,5;0.5;0;0"); r2, w2 = W(api.normalize, "abc"); r3, _ = W(api.normalize, "5;-3;1.25;10;20;15.5")
chk("photo_config default/формат/невалидное→default+warning", pc == "0;0;1.0;0;0;0" and r1 == pc and w1 and r2 == pc and w2 and r3 == "5;-3;1.25;10;20;15.5",
    f"default={pc}; '1;2;1,5;0.5;0;0'→{r1} warn={len(w1)}; 'abc'→{r2} warn={len(w2)}; valid→{r3}")
con = newdb("schema")
cols = [r[1] for r in con.execute("PRAGMA table_info(persons)")]
dflt = [r[4] for r in con.execute("PRAGMA table_info(persons)") if r[1] == "photo_config"]
chk("Схема persons", {"id","fields_json","photo_path","photo_config","print_mark"} <= set(cols), f"cols={cols}; photo_config DEFAULT={dflt}")
pid, wn = W(api.create_person, con, {"last_name": "X"}, None, "bad;cfg")
chk("create_person с невалидным photo_config", api.get_person(con, pid)["photo_config"] == pc and wn, f"saved={api.get_person(con,pid)['photo_config']} warn={len(wn)}")

# 2 import sets
src = list(csv.DictReader(open(SETS/"large/persons.csv", encoding="utf-8")))[:600]
hdr = list(src[0].keys())
def cmp(con, ids):
    bad = 0
    for s, i in zip(src, ids):
        p = api.get_person(con, i)
        for k, v in s.items():
            if k in ("photo_path",): got = p["photo_path"] or ""
            elif k == "photo_config": got = p["photo_config"]; v = api.normalize(v) if v else pc
            else: got = p["fields"].get(k, "")
            if str(got).strip() != v.strip(): bad += 1
    return bad
variants = []
for enc in ("utf-8-sig", "utf-8", "cp1251"):
    for d in (";", ","):
        f = TMP / f"imp_{enc}_{'sc' if d==';' else 'cm'}.csv"
        with open(f, "w", encoding=enc, newline="") as fh:
            w = csv.writer(fh, delimiter=d); w.writerow(hdr); [w.writerow(r.values()) for r in src]
        variants.append(f)
import openpyxl
wb = openpyxl.Workbook(); ws = wb.active; ws.append(hdr); [ws.append(list(r.values())) for r in src]
xf = TMP/"imp.xlsx"; wb.save(xf); variants.append(xf)
res = []
for f in variants:
    c = api.connect(":memory:"); rep, _ = W(api.import_file, c, f, photo_dir=SETS/"large/photos")
    n = c.execute("SELECT count(*) FROM persons").fetchone()[0]; bad = cmp(c, rep.ids)
    res.append((f.name, rep.added, rep.skipped, n, bad, rep.validator))
chk("Импорт 600 строк csv UTF-8±BOM/cp1251 (; ,) + xlsx без потерь", all(a == 600 and n == 600 and b == 0 for _, a, s, n, b, _ in res),
    "; ".join(f"{a}:{b} added/{c} skip/{d} rows/{e} mismatch/{v}" for a, b, c, d, e, v in res))
c = api.connect(":memory:"); rep, _ = W(api.import_file, c, SETS/"large/persons.csv", photo_dir=SETS/"large/photos")
chk("Импорт large (1000 строк)", rep.added + rep.skipped == 1000 and rep.added >= 500, f"added={rep.added} skipped={rep.skipped} errors={rep.errors[:2]}")
# rollback
c = api.connect(":memory:")
def boom(done, total):
    if done == 300: raise RuntimeError("fail@300")
try: api.import_file(c, variants[0], progress=boom); e = None
except RuntimeError as ex: e = ex
n = c.execute("SELECT count(*) FROM persons").fetchone()[0]
chk("Транзакция: сбой на 300-й → откат", e and n == 0, f"exc={e!r}; persons={n}")
c = api.connect(":memory:"); rep, _ = W(api.import_file, c, variants[0], progress=lambda d, t: d < 300)
chk("Отмена импорта → откат", rep.cancelled and c.execute("SELECT count(*) FROM persons").fetchone()[0] == 0, f"cancelled={rep.cancelled}")
for s in ("clean", "duplicates", "missing_fields", "zero_byte_and_broken"):
    c = api.connect(":memory:"); f = SETS/s/"persons.csv"; pd = SETS/s/"photos"
    rep, wn = W(api.import_file, c, f, photo_dir=pd if pd.exists() else None)
    rows = sum(1 for _ in open(f, encoding="utf-8")) - 1
    print(f"  set {s}: rows={rows} added={rep.added} skipped={rep.skipped} codes={sorted({e['code'] for e in rep.errors})} warn={sorted({e['code'] for e in rep.warnings})}")
    exp = {"clean": rep.added == rows and rep.skipped == 0, "duplicates": rep.skipped >= 1, "missing_fields": rep.skipped >= 1,
           "zero_byte_and_broken": rep.added + rep.skipped == rows}[s]
    chk(f"Набор {s}", exp, f"rows={rows} added={rep.added} skipped={rep.skipped} errors={sorted({e['code'] for e in rep.errors})} warnings={sorted({e['code'] for e in rep.warnings})}")
c = api.connect(":memory:"); rep, wn = W(api.import_file, c, SETS/"messy_headers/persons_raw.xlsx")
p = api.list_persons(c)
chk("Набор messy_headers (xlsx, маппинг Backend)", rep.added > 0 and p and "last_name" in p[0]["fields"], f"added={rep.added} skipped={rep.skipped} keys={sorted(p[0]['fields']) if p else None}")
# no data_tools
code = f"""import sys,warnings,shutil,tempfile,pathlib,sqlite3
d=pathlib.Path(tempfile.mkdtemp()); shutil.copytree(r'{ROOT}/badge_backend', d/'badge_backend'); sys.path=[str(d)]+[p for p in sys.path if p not in ('', r'{ROOT}')]
import os; os.chdir(d)
from badge_backend import api
c=api.connect(':memory:')
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always'); r=api.import_file(c, r'{variants[0]}')
print(r.validator, r.added, 'data_tools' in sys.modules)"""
o = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd="/tmp", env={**os.environ, "PYTHONPATH": ""})
chk("Импорт без data_tools", o.stdout.split()[:3] == ["builtin-fallback", "600", "False"], f"stdout={o.stdout.strip()!r} rc={o.returncode} {o.stderr[-200:]}")

# 3 render/export/print
con = newdb("e2e"); rep, _ = W(api.import_file, con, SETS/"clean/persons.csv", photo_dir=SETS/"clean/photos")
ids = rep.ids; base = SETS/"clean/photos"
nophoto = api.create_person(con, {"last_name": "Безфотов", "first_name": "Пётр", "position": "Гость"}, None)
longt = api.create_person(con, {"last_name": "Константинопольский-Водопьянов-Длиннофамильный", "first_name": "Ааааааааааааааааааа"*3,
    "position": "Очень длинная должность " * 20}, "p1.jpg", "40;-20;1.5;50;30;15")
qrid = api.create_element(con, "qr", 800, 450, 200, 160, static_value="BG-QR-1"); bcid = api.create_element(con, "barcode", 560, 560, 420, 70, side="back", static_value="BG-000123", style={"format": "code128", "show_text": False})
img, wn = W(api.render_card_db, con, api.get_person(con, ids[0]), "front", base_dir=base)
chk("Холст 1011×638 RGB", img.size == (1011, 638), f"size={img.size} mode={img.mode}")
_qr_ink = img.crop((800, 450, 1000, 610)).convert("L").getextrema()
_skip = [m for m in wn if re.search(r"qr|barcode|QR|штрихкод|пропущен|reserved", m)]
import zxingcpp
_qd = [d.text for d in zxingcpp.read_barcodes(api.render_card(None, [dict(api.list_elements(con, "front")[[e["id"] for e in api.list_elements(con, "front")].index(qrid)])], "front"))]
chk("v3: qr рисуется (не пропускается, без warning, декодируется)", _qr_ink[0] < 50 and not _skip and _qd == ["BG-QR-1"], f"ink(L) в рамке qr={_qr_ink}; decode={_qd}; warnings про qr/пропуск={_skip}")
_imb, wb_ = W(api.render_card_db, con, api.get_person(con, ids[0]), "back", base_dir=base)
_bc_ink = _imb.crop((560, 560, 980, 630)).convert("L").getextrema()
_skipb = [m for m in wb_ if re.search(r"barcode|штрихкод|пропущен|reserved", m)]
chk("v3: barcode (back) рисуется (не пропускается, без warning)", _bc_ink[0] < 50 and not _skipb, f"ink(L) в рамке barcode={_bc_ink}; warnings={_skipb}")
try:
    im2, wn2 = W(api.render_card_db, con, api.get_person(con, nophoto), "front", base_dir=base); ok = im2.size == (1011, 638); ev = "плейсхолдер, без исключения"
    im2.save(QA/"card_no_photo.png", dpi=(300, 300))
except Exception as ex: ok, ev = False, repr(ex)
chk("Запись без фото не роняет рендер", ok, ev + "; reports/qa/card_no_photo.png")
api.delete_element(con, qrid)
im3, wn3 = W(api.render_card_db, con, api.get_person(con, longt), "front", base_dir=TMP); im3.save(QA/"card_long_text_rotated_photo.png", dpi=(300, 300))
img.save(QA/"card_clean_front.png", dpi=(300, 300))
# text clipping: изолированные field-элементы на белом фоне
els = [{"id": 1, "type": "field", "x": 100, "y": 100, "w": 300, "h": 60, "field_name": "t", "style_json": json.dumps({"font_size": 30}), "side": "front"},
       {"id": 2, "type": "field", "x": 500, "y": 300, "w": 200, "h": 40, "field_name": "t", "style_json": json.dumps({"font_size": 20, "align": "center", "valign": "bottom"}), "side": "front"}]
txt = "Константинопольский Водопьянов " * 10
ci, wc = W(api.render_card, {"fields": {"t": txt}}, els, "front")
px = ci.load(); out = 0
for yy in range(638):
    for xx in range(1011):
        if px[xx, yy] != (255, 255, 255) and not any(e["x"] <= xx < e["x"]+e["w"] and e["y"] <= yy < e["y"]+e["h"] for e in els): out += 1
chk("Текст не выходит за рамку элемента (+warning при обрезке)", out == 0 and any("обрезан" in m for m in wc), f"пикселей вне рамок={out}; warnings={len(wc)}")
# demo-шаблон: перекрытие bbox
E = [e for e in api.list_elements(con) if e["type"] in ("text", "field", "photo", "image")]
ov = [(a["id"], b["id"]) for i, a in enumerate(E) for b in E[i+1:] if a["side"] == b["side"] and a["x"] < b["x"]+b["w"] and b["x"] < a["x"]+a["w"] and a["y"] < b["y"]+b["h"] and b["y"] < a["y"]+a["h"]]
chk("Демо-макет: контентные элементы не пересекаются", not ov, f"пересечения={ov}")
# export
api.set_print_mark(con, ids[:3]); api.set_print_mark(con, [nophoto])  # v2: флаг «к печати»
try: api.export_png(con, out_dir=TMP/"png", base_dir=base); mp = "нет исключения"
except api.MissingPhotosError as ex: mp = f"MissingPhotosError ids={ex.ids}"
pngs, _ = W(api.export_png, con, out_dir=TMP/"png", base_dir=base, allow_missing_photo=True)
info = [(Image.open(p).size, tuple(round(v) for v in Image.open(p).info.get("dpi", (0, 0)))) for p in pngs]
chk("Экспорт PNG 1011×638 @300 DPI (ids=None → print_mark=1)", len(pngs) == 8 and all(s == (1011, 638) and d == (300, 300) for s, d in info),
    f"{len(pngs)} файлов (4 записи×2 стороны); {set(info)}; без allow_missing_photo: {mp}")
pdf, _ = W(api.export_pdf, con, out_path=TMP/"cards.pdf", base_dir=base, allow_missing_photo=True)
pi = subprocess.run(["pdfinfo", "-f", "1", "-l", "99", str(pdf)], capture_output=True, text=True).stdout
sizes = set(re.findall(r"Page\s+\d+ size:\s+([\d.]+ x [\d.]+) pts", pi)); pages = re.search(r"Pages:\s+(\d+)", pi).group(1)
mm = {tuple(round(float(v)/72*25.4, 2) for v in s.split(" x ")) for s in sizes}
chk("Экспорт PDF страницы 85.6×54 мм", pages == "8" and all(abs(a-85.6) <= 0.1 and abs(b-54.0) <= 0.1 for a, b in mm), f"pages={pages}; sizes pts={sizes} → мм={mm} (допуск ±0.1 мм; 638 px/300 DPI = 54.02 мм)")
# print
from PyQt6.QtWidgets import QApplication; from PyQt6.QtGui import QPageLayout
from PyQt6.QtPrintSupport import QPrinter
app = QApplication.instance() or QApplication([])
pr = QPrinter(QPrinter.PrinterMode.HighResolution); pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(str(QA/"print_output.pdf"))
n, _ = W(api.print_cards, con, pr, base_dir=base, allow_missing_photo=True)
pi = subprocess.run(["pdfinfo", "-f", "1", "-l", "99", str(QA/"print_output.pdf")], capture_output=True, text=True).stdout
psz = set(re.findall(r"Page\s+\d+ size:\s+([\d.]+ x [\d.]+) pts", pi)); pmm = {tuple(round(float(v)/72*25.4, 3) for v in s.split(" x ")) for s in psz}
pp = re.search(r"Pages:\s+(\d+)", pi).group(1)
chk("Печать QPrinter→PDF: только print_mark=1, страница CR80 ±0.15 мм", int(n) == 8 and pp == "8" and all(abs(a-85.6) <= 0.15 and abs(b-54.0) <= 0.15 for a, b in pmm), f"print_cards={int(n)}, pdf pages={pp}, size={psz}→{pmm} мм (помечено 4 из {len(api.list_persons(con))}); reports/qa/print_output.pdf")
api.set_print_mark(con, [p["id"] for p in api.list_persons(con)], False)
pr2 = QPrinter(); pr2.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr2.setOutputFileName(str(TMP/"none.pdf"))
n0 = api.print_cards(con, pr2)
k = api.set_print_mark(con, ids[:2]); marked = [p["id"] for p in api.list_persons(con, only_marked=True)]
chk("set_print_mark / ничего не помечено → 0 страниц", int(n0) == 0 and k == 2 and marked == ids[:2], f"print пусто={int(n0)}; set_print_mark→{k}; marked={marked}")
from datetime import datetime, timedelta
t0 = datetime.now().astimezone()
km = api.mark_printed(con, ids[:2]); rows = [api.get_person(con, i) for i in ids[:2]]
def iso_ok(v):
    try: d = datetime.fromisoformat(v); return d.tzinfo is not None and abs(d - t0) < timedelta(minutes=1) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", v)
    except Exception: return False
other = api.get_person(con, ids[2])
chk("mark_printed: print_mark=0 и printed_at в ISO 8601 (со смещением)", km == 2 and all(r["print_mark"] == 0 and iso_ok(r["printed_at"]) for r in rows) and other["printed_at"] is None,
    f"mark_printed→{km}; {[(r['id'], r['print_mark'], r['printed_at']) for r in rows]}; непечатанная id={other['id']} printed_at={other['printed_at']}")
kk = api.set_print_mark(con, ids[:1]); r0 = api.get_person(con, ids[0])
chk("set_print_mark не трогает printed_at", r0["print_mark"] == 1 and r0["printed_at"] == rows[0]["printed_at"], f"print_mark={r0['print_mark']} printed_at={r0['printed_at']}")
# миграция v1 → v2
import sqlite3
from badge_backend import db as bdb
old = TMP / "old_v1.db"; c1 = sqlite3.connect(old)
c1.executescript("BEGIN;\n" + bdb.SCHEMA + "\nPRAGMA user_version=1;\nCOMMIT;")
c1.execute("INSERT INTO persons(fields_json,photo_path,photo_config,print_mark) VALUES (?,?,?,?)", (json.dumps({"last_name": "Старый", "first_name": "Ёж"}, ensure_ascii=False), "p1.jpg", "5;-3;1.25;10;20;15.5", 1))
c1.execute("INSERT INTO persons(fields_json) VALUES ('{}')"); c1.execute("INSERT INTO template_elements(type,x,y,w,h,field_name) VALUES ('field',1,2,300,40,'last_name')"); c1.commit()
before = [tuple(r) for r in c1.execute("SELECT id,fields_json,photo_path,photo_config,print_mark,created_at,updated_at FROM persons")]
els_b = [tuple(r) for r in c1.execute("SELECT * FROM template_elements")]; v1 = c1.execute("PRAGMA user_version").fetchone()[0]; c1.close()
c2 = api.connect(str(old)); v2 = c2.execute("PRAGMA user_version").fetchone()[0]
after = [tuple(r) for r in c2.execute("SELECT id,fields_json,photo_path,photo_config,print_mark,created_at,updated_at FROM persons")]
pa = [r[0] for r in c2.execute("SELECT printed_at FROM persons")]; els_a = [tuple(r) for r in c2.execute("SELECT * FROM template_elements")]; c2.close()
v3 = api.connect(str(old)).execute("PRAGMA user_version").fetchone()[0]
chk("Миграция user_version 1→LATEST=3 без потери данных (идемпотентна)", v1 == 1 and v2 == 3 and v3 == 3 and bdb.LATEST == 3 and before == after and els_b == els_a and pa == [None, None],
    f"user_version {v1}→{v2}, повторно {v3}; persons до==после: {before == after} ({len(after)} строк); template_elements сохранены: {els_b == els_a}; printed_at={pa}")
# текст: перенос по дефису и «…»
from badge_backend import render as BR
from PIL import ImageDraw
d0 = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
fam = "Константинопольский-Водопьянов-Длиннофамильный"
f, lines, ys, ws, bb, notes = BR._fit_text(d0, fam, 600, 300, 22*300/72, 8*300/72, None, True, None, True, 1.0)
chk("Перенос длинной двойной фамилии по дефису", len(lines) >= 2 and all(l.endswith("-") for l in lines[:-1]) and "".join(lines) == fam and not notes,
    f"рамка 600×300, 22pt (min 8pt): кегль {f.size}px, строки={lines}; notes={notes}")
long_ = "Очень длинная должность " * 20
f, lines, ys, ws, bb, notes = BR._fit_text(d0, long_, 600, 125, 12*300/72, 8*300/72, None, False, None, True, 1.0)
inside = (bb[3] - bb[1]) <= 125 and all(BR._tw(d0, l, f) <= 600 for l in lines)
el = {"id": 9, "type": "field", "x": 100, "y": 100, "w": 600, "h": 125, "field_name": "t", "style_json": json.dumps({"font_size": 12}), "side": "front"}
ci2, wc2 = W(api.render_card, {"fields": {"t": long_}}, [el], "front")
box = ci2.crop((100, 100, 700, 225)).convert("L"); ink_rows = [yy for yy in range(125) if min(box.getpixel((xx, yy)) for xx in range(600)) < 200]
chk("Частично видимые строки не рисуются, последняя видимая строка заканчивается на «…»", inside and lines and lines[-1].endswith("…") and any("показано строк" in m for m in wc2),
    f"строк видно={len(lines)}, последняя={lines[-1][-25:]!r}, высота bbox={bb[3]-bb[1]}≤125; ink-строки пикселей {ink_rows[0] if ink_rows else None}..{ink_rows[-1] if ink_rows else None}; warning={[m for m in wc2 if 'строк' in m]}")
im4, _ = W(api.render_card, {"fields": {"t": long_, "f": fam}}, [el, {"id": 10, "type": "field", "x": 100, "y": 300, "w": 600, "h": 300, "field_name": "f", "style_json": json.dumps({"font_size": 22, "bold": True}), "side": "front"}], "front")
im4.save(QA/"card_hyphen_ellipsis.png", dpi=(300, 300))

# 4 duplication
rc = subprocess.run(["grep", "-rnE", r"def render_card\b", "--include=*.py", "badge_backend", "ui", "data_tools"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
impl = [l for l in rc.splitlines() if not l.startswith("ui/backend_api.py")]
wrap = open(ROOT/"ui/backend_api.py", encoding="utf-8").read()
chk("Один render_card", len(impl) == 1 and "badge_backend/render" in impl[0] and "_api.render_card_db(" in wrap and "ImageDraw" not in wrap and "drawText" not in wrap,
    rc + " | ui-обёртка только делегирует в _api.render_card_db")
sq = subprocess.run(["grep", "-rnEi", r"import sqlite3|\.execute\(|\b(SELECT|INSERT|UPDATE|DELETE)\b .*(FROM|INTO|SET)", "--include=*.py", "ui"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
chk("Нет SQL в ui/", not sq, sq or "grep пусто")
dt = subprocess.run(["grep", "-rnEi", r"openpyxl|load_workbook|synonym|map_headers|Фамилия|ФИО|header_key|slugify", "--include=*.py", "data_tools", "--exclude-dir=tests", "--exclude-dir=testdata"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
chk("Нет маппинга заголовков/чтения Excel в data_tools", not dt, dt or "grep пусто")
qp = subprocess.run(["grep", "-rn", "QPainter", "--include=*.py", "ui"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
print("  QPainter в ui:", qp)
json.dump([dict(name=a, ok=b, ev=c) for a, b, c in R], open(QA/"e2e_results.json", "w"), ensure_ascii=False, indent=1)
print(f"\nИТОГО: {sum(r[1] for r in R)}/{len(R)} PASS; tmp={TMP}")
