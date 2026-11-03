"""QA этап 13 (Backend): независимый round-trip xlsx/xls/csv/db, большие файлы, отмена, mapping, дубли логики.
QT_QPA_PLATFORM=offscreen .venv/bin/python reports/qa/e2e_stage13.py"""
import os, sys, re, ast, json, time, tempfile, pathlib, threading, hashlib, subprocess, inspect
sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]; QA = ROOT / "reports/qa"; sys.path.insert(0, str(ROOT))
from PIL import Image
from badge_backend import api, db as bdb
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa13_")); RES = []
def chk(n, ok, ev=""): RES.append((n, bool(ok), str(ev))); print(("PASS" if ok else "FAIL"), "|", n, "|", ev)

FIELDS = [("last_name", "Фамилия", None), ("first_name", "Имя", None), ("position", "Должность", "Сотрудник"),
          ("dept", "Отдел", None), ("code", "Таб. №", None), ("note", "Примечание", None)]
PEOPLE = [
    {"last_name": "Ёлкина-Щёголева", "first_name": "Юлия", "position": "Гл. «инженер»; ИТ, отдел №5", "dept": "ИТ", "code": "007", "note": "строка1\nстрока2"},
    {"last_name": "Пустов", "first_name": "", "position": "", "dept": "", "code": "0012", "note": ""},
    {"last_name": "Ъ", "first_name": "Эй, \"кавычки\"", "position": "Бухгалтер", "dept": "Финансы", "code": "12345678901234567890", "note": "  пробелы внутри  "},
]
PH = TMP / "ph"; PH.mkdir(); Image.new("RGB", (60, 80), "blue").save(PH / "фото_1.png")
def make_src():
    c = api.connect(str(TMP / f"src_{time.time_ns()}.db"))
    for i, (n, l, d) in enumerate(FIELDS): api.upsert_field(c, n, l, i, default_value=d)
    ids = [api.create_person(c, p, photo_path="фото_1.png" if i == 0 else None) for i, p in enumerate(PEOPLE)]
    api.update_photo_config(c, ids[0], "12;-7;1.25;3;4;90")
    api.set_print_mark(c, [ids[0], ids[2]], True); api.mark_printed(c, [ids[2]])
    return c, ids
def snap(c):
    labs = {f["name"]: f["label"] for f in api.list_fields(c)}
    out = []
    for p in api.list_persons(c):
        out.append(dict(fields={labs.get(k, k): v for k, v in p["fields"].items() if v not in ("", None)},
                        photo=p["photo_path"], cfg=p["photo_config"], mark=p["print_mark"], printed=p["printed_at"] is not None))
    return out

src, ids = make_src(); want = snap(src)
for fmt in ("xlsx", "xls", "csv", "db"):
    out = TMP / f"rt.{fmt}"
    try:
        r = api.export_persons(src, out, fmt, photo_dir=PH)
        sh = api.open_source(out); s0 = sh[0]
        tgt = api.connect(str(TMP / f"tgt_{fmt}.db"))
        if fmt != "db":
            for i, (n, l, d) in enumerate(FIELDS): api.upsert_field(tgt, n, l, i)
        _tv = api.connect(str(TMP / f"tgtv_{fmt}.db"))
        if fmt != "db":
            for i, (n, l, d) in enumerate(FIELDS): api.upsert_field(_tv, n, l, i)
        rep0 = api.import_rows(_tv, s0, **({"import_fields": True} if fmt == "db" else {}), photo_dir=(TMP / "rt_photos") if fmt == "db" else PH)
        chk(f"RT-{fmt} D25: validate=True принимает все записи (пустые значения — только warning)", rep0.added == 3 and not rep0.errors, f"added={rep0.added}, errors={[(e['row'], e['field'], e['code']) for e in rep0.errors]}, warnings={len(rep0.warnings)}")
        rep = api.import_rows(tgt, s0, photo_dir=(TMP / "rt_photos") if fmt == "db" else PH, validate=False, **({"import_fields": True} if fmt == "db" else {}))  # D24: .db — с подтверждением
        got = snap(tgt)
        fn = sorted(f["name"] for f in api.list_fields(tgt))
        chk(f"RT-{fmt} D26: поля цели не размножаются (метки сопоставлены существующим полям)", fn == sorted(n for n, _, _ in FIELDS), f"{fn}; skipped_columns={getattr(rep, 'skipped_columns', '?')}")
        f_ok = [g["fields"] for g in got] == [w_["fields"] for w_ in want]
        diff = [(i, {k: (w_["fields"].get(k), g["fields"].get(k)) for k in set(w_["fields"]) | set(g["fields"]) if w_["fields"].get(k) != g["fields"].get(k)}) for i, (w_, g) in enumerate(zip(want, got))]
        chk(f"RT-{fmt} D27: поля без strip при validate=False (кириллица, пустые, переносы, кавычки, ведущие нули)", rep.added == 3 and f_ok and not rep.errors, f"added={rep.added}, errors={rep.errors[:2]}, diff={[d for d in diff if d[1]] or 'нет'}")
        # D39: photo_path = photos/<уникальное имя> в проекте цели, файл открывается, байты = исходник
        _ph = got[0]["photo"] or ""; _abs = pathlib.Path(TMP / f"tgt_{fmt}.db").parent / _ph
        try:
            with Image.open(_abs) as _im: _im.load(); _opn = True
        except Exception: _opn = False
        _same = _abs.is_file() and _abs.read_bytes() == (PH / "фото_1.png").read_bytes()
        chk(f"RT-{fmt} photo_path + photo_config (D39: photos/…, открывается, байты = исходник)",
            _ph.startswith("photos/") and _opn and _same and got[0]["cfg"] == want[0]["cfg"] and got[1]["photo"] is None,
            f"{[(g['photo'], g['cfg']) for g in got]}; opens={_opn}; bytes_eq={_same}")
        if fmt == "db":
            chk(f"RT-{fmt} print_mark / printed_at", [(g["mark"], g["printed"]) for g in got] == [(w_["mark"], w_["printed"]) for w_ in want],
                f"ожидалось {[(w_['mark'], w_['printed']) for w_ in want]}, получено {[(g['mark'], g['printed']) for g in got]}")
        else:
            cols0, rows0 = api.read_rows(api.open_source(out)[0])
            hdr_ok = "Напечатано" in cols0 and "Дата печати" in cols0
            vals = [dict(zip(cols0, r_)) for r_ in rows0] if hdr_ok else []
            fmt_ok = hdr_ok and [v.get("Напечатано") for v in vals] == ["нет", "нет", "да"] and re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", str(vals[2].get("Дата печати") or ""))
            chk(f"RT-{fmt} D28: колонки «Напечатано» (да/нет) и «Дата печати» (ДД.ММ.ГГГГ) в файле", fmt_ok, f"колонки={cols0}, значения={[(v.get('Напечатано'), v.get('Дата печати')) for v in vals]}")
            chk(f"RT-{fmt} D28: printed_at переживает round-trip", [g["printed"] for g in got] == [w_["printed"] for w_ in want],
                f"ожидалось {[w_['printed'] for w_ in want]}, получено {[g['printed'] for g in got]}")
        dv = {f["name"]: f.get("default_value") for f in api.list_fields(tgt)}.get("position")
        if fmt == "db": chk(f"RT-{fmt} D29: default_value сохраняется в .db", dv == "Сотрудник", f"position.default_value={dv!r}")
        else: chk(f"RT-{fmt} D29: default_value официально теряется в табличном формате (информ.)", True, f"position.default_value={dv!r}")
        s0.close() if hasattr(s0, "close") else None
    except Exception as e:
        chk(f"RT-{fmt} без исключений", False, repr(e))

# исходник .db не меняется при открытии
p = pathlib.Path(src.execute("PRAGMA database_list").fetchone()[2]); src.commit()
h0 = hashlib.sha256(p.read_bytes()).hexdigest(); sh = api.open_source(p); api.read_rows(sh[0]); sh[0].close()
chk("DB-источник не изменён open_source/read_rows", hashlib.sha256(p.read_bytes()).hexdigest() == h0, "sha256 совпал")

# mapping save/load + auto_match
cols, _ = api.read_rows(api.open_source(TMP / "rt.csv")[0])
am = api.auto_match(cols); mp = dict(zip(cols, am))
api.save_mapping(TMP / "map.json", mp, columns=cols); back = api.load_mapping(TMP / "map.json")
chk("auto_match + save/load_mapping (кириллица, round-trip)", back == mp and "Фамилия" in back, f"{mp}")
(TMP / "bad.json").write_text('{"format":"x"}', encoding="utf-8")
try: api.load_mapping(TMP / "bad.json"); bad = False
except ValueError: bad = True
chk("load_mapping: чужой файл → ValueError", bad)

# большие файлы + прогресс + отмена
N = 20000
big = api.connect(str(TMP / "bigsrc.db"))
for i, (n, l, d) in enumerate(FIELDS[:3]): api.upsert_field(big, n, l, i)
with big: big.executemany("INSERT INTO persons(fields_json) VALUES (?)", [(json.dumps({"last_name": f"Фамилия{i}", "first_name": "Имя", "position": "П"}, ensure_ascii=False),) for i in range(N)])
for fmt in ("xlsx", "csv", "xls", "db"):
    out = TMP / f"big.{fmt}"; t = time.time(); r = api.export_persons(big, out, fmt); te = time.time() - t
    s0 = api.open_source(out)[0]; tgt = api.connect(str(TMP / f"bigt_{fmt}.db"))
    prog = []; t = time.time()
    rep = api.import_rows(tgt, s0, validate=False, progress=lambda d, tot: prog.append((d, tot)) or True); ti = time.time() - t
    n = len(api.list_persons(tgt))
    chk(f"BIG-{fmt} {N} строк: экспорт+импорт, прогресс монотонный", rep.added == N and n == N and prog and prog[-1][0] == prog[-1][1] and all(a[0] <= b[0] for a, b in zip(prog, prog[1:])),
        f"export {te:.1f}s, import {ti:.1f}s, прогресс-вызовов={len(prog)}, last={prog[-1] if prog else None}")
    # отмена Event на середине
    ev = threading.Event(); tgt2 = api.connect(str(TMP / f"bigc_{fmt}.db"))
    rep2 = api.import_rows(tgt2, s0, validate=False, progress=lambda d, tot: (ev.set() if d >= tot // 2 else None) or True, cancel=ev)
    n2 = len(api.list_persons(tgt2))
    chk(f"CANCEL-{fmt} Event на середине → откат, 0 записей", rep2.cancelled and rep2.added == 0 and n2 == 0, f"cancelled={rep2.cancelled}, added={rep2.added}, в БД={n2}")
    s0.close()
tgt3 = api.connect(str(TMP / "bigc_pf.db")); s0 = api.open_source(TMP / "big.csv")[0]
rep3 = api.import_rows(tgt3, s0, validate=False, progress=lambda d, tot: d < 1000)
chk("CANCEL progress→False → откат", rep3.cancelled and len(api.list_persons(tgt3)) == 0, f"cancelled={rep3.cancelled}")
with big: big.executemany("INSERT INTO persons(fields_json) VALUES ('{}')", [()] * (api.XLS_MAX_ROWS + 1 - N))
try: api.export_persons(big, TMP / "toobig.xls"); lim = False
except ValueError: lim = not (TMP / "toobig.xls").exists()
chk(".xls > 65535 строк → ValueError, файл не создан", lim)

# дубли логики
def g(cmd): return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout
defs = g(["grep", "-rnE", r"^\s*def (map_headers|auto_match|_norm_header|normalize_header|match_header|parse_file|read_table|import_file|import_rows|import_records|export_persons)\b", "--include=*.py", "badge_backend", "ui", "data_tools"])
# ui/backend_api.py — тонкий фасад-метод (делегирует в badge_backend.api), не вторая реализация
dl = [l for l in defs.splitlines() if "/tests/" not in l and not l.startswith("ui/backend_api.py")]
chk("Одна реализация каждой функции импорта/экспорта/сопоставления", len(dl) == len({re.search(r"def (\w+)", l).group(1) for l in dl}), "\n" + "\n".join(dl))
am_src = inspect.getsource(api.auto_match)
chk("auto_match — обёртка над headers.map_headers (без своей логики синонимов)", "map_headers" in am_src and "SYNONYMS" not in am_src, am_src.strip().splitlines()[0])
uim = g(["grep", "-rnE", r"SYNONYMS|casefold\(\).*(заголов|header)|def .*(map|match).*header", "--include=*.py", "ui"])
uim = [l for l in uim.splitlines() if "smoke_test" not in l and "import" not in l]
chk("Нет своей логики сопоставления заголовков в ui/", not uim, uim or "нет")
sql = []
for f in (ROOT / "ui").glob("*.py"):
    if f.name == "smoke_test.py": continue
    for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Attribute) and n.attr in ("execute", "executemany", "executescript"): sql.append(f"{f.name}:{n.lineno}")
        if isinstance(n, (ast.Import, ast.ImportFrom)) and "sqlite3" in ast.dump(n): sql.append(f"{f.name}:{n.lineno} import sqlite3")
chk("Нет SQL в ui/ (AST)", not sql, sql or "нет")

# --- D24 (Архитектор): поля только из «Менеджера полей» с типом; без авто/демо-полей; импорт поля не создаёт (кроме .db с подтверждением) ---
def _d24():
    TYPES = {"text", "number", "date", "image", "bool"}
    c = api.connect(str(TMP / "d24_new.db"))
    chk("D24-1 новая БД не содержит полей (нет демо/автополей)", api.list_fields(c) == [], [f["name"] for f in api.list_fields(c)])
    chk("D24-2 в новой БД нет записей/элементов-демо", c.execute("SELECT COUNT(*) FROM persons").fetchone()[0] == 0, "persons")
    for t in sorted(TYPES):
        try: api.upsert_field(c, f"f_{t}", f"Поле {t}", data_type=t); ok = True; ev = ""
        except Exception as e: ok, ev = False, repr(e)
        chk(f"D24-3 Менеджер полей: тип «{t}» принимается", ok, ev)
    bad = None
    try: api.upsert_field(c, "f_bad", "Плохой", data_type="blob"); bad = "принят"
    except Exception as e: bad = None if isinstance(e, ValueError) else repr(e)
    chk("D24-4 неизвестный тип поля отклоняется ValueError", bad is None, bad or "ValueError")
    ft = {f["name"]: f.get("data_type") for f in api.list_fields(c)}
    chk("D24-5 у каждого поля задан тип из допустимого набора", ft and all(v in TYPES for v in ft.values()), ft)
    before = sorted(ft)
    csvp = TMP / "d24.csv"; csvp.write_text("Поле text;Неизвестная колонка;Ещё одна\nа;б;в\n", encoding="utf-8-sig")
    try:
        sh = api.open_source(str(csvp))[0]; api.import_rows(c, sh, validate=False)
    except Exception as e: chk("D24-6 импорт csv выполнился", False, repr(e))
    after = sorted(f["name"] for f in api.list_fields(c))
    chk("D24-6 импорт csv/xlsx/xls НЕ создаёт полей (лишние колонки игнорируются)", after == before, f"{before} → {after}")
    # .db: без подтверждения (import_fields=False по умолчанию) поля не создаются, с подтверждением — создаются с типом
    s = api.connect(str(TMP / "d24_src.db")); api.upsert_field(s, "extra", "Доп.", data_type="date")
    api.create_person(s, {"extra": "2026-01-02"}); s.commit(); s.close()
    sh = api.open_source(str(TMP / "d24_src.db"))[0]
    api.import_rows(c, sh, validate=False)
    chk("D24-7 импорт .db без подтверждения не создаёт полей", "extra" not in {f["name"] for f in api.list_fields(c)}, [f["name"] for f in api.list_fields(c)])
    try:
        sh = api.open_source(str(TMP / "d24_src.db"))[0]; api.import_rows(c, sh, validate=False, import_fields=True)
        nf = {f["name"]: f.get("data_type") for f in api.list_fields(c)}
        chk("D24-8 импорт .db с подтверждением (import_fields=True) создаёт поле с исходным типом", nf.get("extra") == "date", nf)
    except Exception as e: chk("D24-8 импорт .db с подтверждением", False, repr(e))
    c.close()
try: _d24()
except Exception as e:
    import traceback; chk("D24 блок выполнился без исключений", False, traceback.format_exc()[-600:])

# --- Приёмка Архитектора: пустое/битое фото → warning; D25 ошибки; D26 skipped_columns ---
def _acc():
    c = api.connect(str(TMP / "acc.db"))
    chk("ACC новая БД создаётся без полей", api.list_fields(c) == [], [f["name"] for f in api.list_fields(c)])
    api.upsert_field(c, "last_name", "Фамилия", 0, data_type="text"); api.upsert_field(c, "age", "Возраст", 1, data_type="number")
    pd = TMP / "accph"; pd.mkdir(exist_ok=True); (pd / "empty.png").write_bytes(b""); (pd / "broken.png").write_bytes(b"not an image")
    Image.new("RGB", (10, 10), "red").save(pd / "ok.png")
    cp = TMP / "acc.csv"
    cp.write_text("Фамилия;возраст ;Фото;Лишняя\nА;1;empty.png;x\nБ;2;broken.png;y\nВ;3;ok.png;z\nГ;abc;;\n;;;\n", encoding="utf-8-sig")
    r = api.import_rows(c, api.open_source(cp)[0], photo_dir=pd)
    w = {(x.get("row"), x.get("code")) for x in r.warnings}; codes = [x.get("code") for x in r.warnings] + [x.get("code") for x in r.photo_issues]
    chk("ACC пустое фото → warning PHOTO_EMPTY, запись импортирована", "PHOTO_EMPTY" in codes, f"warnings={r.warnings}, photo_issues={r.photo_issues}")
    chk("ACC битое фото → warning PHOTO_BROKEN, запись импортирована", "PHOTO_BROKEN" in codes, codes)
    ec = [e.get("code") for e in r.errors]
    chk("D25 ошибки только FIELD_TYPE и полностью пустая строка", r.added == 3 and len(r.errors) == 2 and any("TYPE" in (x or "") for x in ec), f"added={r.added}, errors={[(e.get('row'), e.get('field'), e.get('code')) for e in r.errors]}")
    sk = [x.get("label") if isinstance(x, dict) else x for x in r.skipped_columns]
    chk("D26 «возраст » сопоставлен с «Возраст» (регистр/пробелы); «Лишняя» → skipped_columns; поля не созданы",
        "Лишняя" in sk and "возраст " not in sk and sorted(f["name"] for f in api.list_fields(c)) == ["age", "last_name"], f"skipped_columns={r.skipped_columns}, fields={[f['name'] for f in api.list_fields(c)]}")
    c.close()
try: _acc()
except Exception:
    import traceback; chk("ACC блок выполнился без исключений", False, traceback.format_exc()[-600:])

# --- 91b0208/2a68954: фото как image-поле, единый resolve_photo_path ---
def _photo_rules():
    import sqlite3, warnings as _w
    # (a) grep + AST: путь фото вычисляется только в photos.resolve_photo_path (abs_path — его помощник)
    hits = []
    for base in ("badge_backend", "ui", "data_tools"):
        for f in (ROOT / base).rglob("*.py"):
            rel = str(f.relative_to(ROOT))
            if "/tests/" in rel or rel.endswith(("smoke_test.py", "qa_click_all.py", "self_test.py")): continue
            try: tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError: continue
            fn_of = {}
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for sub in ast.walk(fn): fn_of.setdefault(id(sub), fn.name)
            for n in ast.walk(tree):
                join = (isinstance(n, ast.Call) and ((isinstance(n.func, ast.Attribute) and n.func.attr in ("join", "joinpath")) or
                        (isinstance(n.func, ast.Name) and n.func.id in ("Path", "abs_path")))) or (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div))
                if not join: continue
                txt = ast.unparse(n)
                if "photo_path" not in txt and not re.search(r"\[['\"]photo['\"]\]|photo_field", txt): continue
                fname = fn_of.get(id(n), "<module>")
                if rel.endswith("services/photos.py") and fname in ("resolve_photo_path", "abs_path"): continue
                hits.append(f"{rel}:{n.lineno} {fname}(): {txt[:90]}")
    g_ = g(["grep", "-rnE", r"(base_dir|photo_dir)[^\n]*photo_path|photo_path[^\n]*(base_dir|photo_dir)", "--include=*.py", "badge_backend", "ui", "data_tools"])
    g_ = [l for l in g_.splitlines() if "/tests/" not in l and "resolve_photo_path" not in l and "def " not in l and not re.search(r":\s*#|\"\"\"|photo_dir=|base_dir=", l)]
    chk("PH-a (AST) путь фото вычисляется только в resolve_photo_path", not hits, hits or "нет")
    chk("PH-a (grep, информ.) строки с photo_path и base_dir/photo_dir вне resolve_photo_path", True, g_[:12] or "нет")
    # (b) link_field: несовпадение типов → ValueError
    c = api.connect(":memory:")
    api.upsert_field(c, "foto", "Фото", 0, data_type="image"); api.upsert_field(c, "fam", "Фамилия", 1, data_type="text")
    e_ph = api.create_element(c, "photo", 10, 10, 200, 260); e_tx = api.create_element(c, "field", 300, 10, 400, 60, field_name="fam")
    res = {}
    for nm, (eid, fld) in {"photo→text": (e_ph, "fam"), "field→image": (e_tx, "foto")}.items():
        try: api.link_field(c, eid, fld); res[nm] = "принято"
        except ValueError as e: res[nm] = "ValueError"
    ok_ = api.link_field(c, e_ph, "foto")
    chk("PH-b link_field: несовпадение типов → ValueError, photo↔image принимается", all(v == "ValueError" for v in res.values()) and ok_, f"{res}, photo→image={ok_}")
    # (c) legacy v1: только persons.photo_path → после миграции фото рендерится
    old = TMP / "legacy_v1.db"; c1 = sqlite3.connect(old)
    c1.executescript("BEGIN;\n" + bdb.SCHEMA + "\nPRAGMA user_version=1;\nCOMMIT;")
    ph = TMP / "legacy_photo.png"; Image.new("RGB", (300, 400), (200, 30, 30)).save(ph)
    c1.execute("INSERT INTO persons(id,fields_json,photo_path,print_mark) VALUES (1,?,?,1)", (json.dumps({"last_name": "Старый"}, ensure_ascii=False), str(ph)))
    c1.execute("INSERT INTO persons(id,fields_json,print_mark) VALUES (2,?,1)", (json.dumps({"last_name": "Старый"}, ensure_ascii=False),))
    c1.execute("INSERT INTO template_elements(type,x,y,w,h) VALUES ('photo',20,20,300,400)"); c1.commit(); c1.close()
    c = api.connect(str(old))
    with _w.catch_warnings(): _w.simplefilter("ignore"); a = api.render_card_db(c, 1, "front"); b = api.render_card_db(c, 2, "front")
    a = a[0] if isinstance(a, tuple) else a; b = b[0] if isinstance(b, tuple) else b
    a = a.convert("RGB"); b = b.convert("RGB")
    diff = sum(1 for x, y in zip(a.crop((20, 20, 320, 420)).getdata(), b.crop((20, 20, 320, 420)).getdata()) if x != y)
    red = a.getpixel((170, 220))
    chk("PH-c legacy v1 (только photo_path) → после миграции фото рендерится (пиксели ≠ рендер без фото)",
        c.execute("PRAGMA user_version").fetchone()[0] == bdb.LATEST and diff > 50000 and red[0] > 150 and red[1] < 90,
        f"user_version={c.execute('PRAGMA user_version').fetchone()[0]}, отличающихся пикселей={diff}/120000, пиксель в центре={red}")
    # (d) missing_photos проверяет обе стороны (решение Архитектора)
    c = api.connect(str(TMP / "both_sides.db"))
    api.upsert_field(c, "ph_front", "Фото лиц.", 0, data_type="image"); api.upsert_field(c, "ph_back", "Фото обор.", 1, data_type="image")
    api.create_element(c, "photo", 10, 10, 200, 260, side="front", field_name="ph_front")
    api.create_element(c, "photo", 10, 10, 200, 260, side="back", field_name="ph_back")
    okp = TMP / "ok_side.png"; Image.new("RGB", (40, 40), "blue").save(okp)
    p_ok = api.create_person(c, {"ph_front": str(okp), "ph_back": str(okp)})
    p_back = api.create_person(c, {"ph_front": str(okp), "ph_back": str(TMP / "нет.png")})
    p_front = api.create_person(c, {"ph_front": str(TMP / "нет.png"), "ph_back": str(okp)})
    miss = api.missing_photos(c, [p_ok, p_back, p_front])
    chk("PH-d missing_photos проверяет обе стороны", miss == [p_back, p_front], f"missing={miss}; ok={p_ok}, нет оборота={p_back}, нет лица={p_front}")
try: _photo_rules()
except Exception:
    import traceback; chk("PH блок выполнился без исключений", False, traceback.format_exc()[-700:])
sig = str(inspect.signature(api.export_persons))
chk("Сигнатура export_persons (информ.)", True, sig)
print(f"\nИТОГО: {sum(r[1] for r in RES)}/{len(RES)} PASS; tmp={TMP}")
json.dump([dict(name=a, ok=b, ev=c) for a, b, c in RES], open(QA / "e2e_stage13_results.json", "w"), ensure_ascii=False, indent=1)
