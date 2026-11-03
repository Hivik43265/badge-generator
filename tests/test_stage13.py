"""Этап 13: open_source/read_rows/auto_match/import_rows, mapping JSON, export_persons (xlsx/xls/csv/db)."""
from badge_backend.testing import import_with_fields as _imp
import json, os, sqlite3, threading, hashlib, pytest
from PIL import Image
from badge_backend import api, db
from badge_backend.testing import create_legacy_db

PEOPLE = [{"last_name": "Ёжиков", "first_name": "Пётр", "position": "Инженер «A»; отдел", "tab": "007"},
          {"last_name": "Щукина", "first_name": "Юлия", "position": "Бухгалтер старший", "tab": "0012"},
          {"last_name": "Иванов", "first_name": "Иван", "position": "", "tab": "3"}]

@pytest.fixture
def src(tmp_path):
    con = api.connect()
    api.upsert_field(con, "last_name", "Фамилия", 0); api.upsert_field(con, "first_name", "Имя", 1)
    api.upsert_field(con, "position", "Должность", 2, default_value="Сотрудник")
    api.upsert_field(con, "tab", "Таб. ключ", 3)
    (tmp_path / "ph").mkdir()
    Image.new("RGB", (30, 40), "red").save(tmp_path / "ph" / "a.png")
    ids = [api.create_person(con, p, photo_path="a.png" if i == 0 else None) for i, p in enumerate(PEOPLE)]
    api.set_print_mark(con, [ids[0]], 1); api.mark_printed(con, [ids[1]])
    return con, ids, tmp_path

def _by_label(con):
    labs = {f["name"]: f["label"] for f in api.list_fields(con)}
    return [{labs.get(k, k): v for k, v in p["fields"].items()} for p in api.list_persons(con)]

def _expected():
    m = {"last_name": "Фамилия", "first_name": "Имя", "position": "Должность", "tab": "Таб. ключ"}
    return [{m[k]: v for k, v in p.items() if v != ""} for p in PEOPLE]

@pytest.mark.parametrize("fmt", ["xlsx", "xls", "csv", "db"])
def test_roundtrip_all_formats(src, fmt):
    con, ids, d = src
    out = d / f"out.{fmt}"
    r = api.export_persons(con, out, fmt, photo_dir=d / "ph")
    assert r["path"] == out and r["rows"] == 3 and out.exists()
    sheets = api.open_source(out); assert len(sheets) == 1
    cols, rows = api.read_rows(sheets[0])
    assert len(rows) == 3
    tgt = api.connect()
    base = (d / "out_photos") if fmt == "db" else d / "ph"
    rep = _imp(api.import_rows, tgt, sheets[0], photo_dir=base)
    assert rep.added == 3 and not rep.errors and not rep.cancelled
    assert _by_label(tgt) == _expected()
    ps = api.list_persons(tgt)
    assert ps[0]["photo_path"] == "a.png" and ps[1]["photo_path"] is None
    if fmt == "db":
        assert (d / "out_photos" / "a.png").exists() and r["files_copied"] == 1
        assert [(p["print_mark"], p["printed_at"] is not None) for p in ps] == [(1, False), (0, True), (0, False)]
        f = {x["name"]: x for x in api.list_fields(tgt)}
        assert f["tab"]["label"] == "Таб. ключ" and f["position"]["default_value"] == "Сотрудник"
    else:
        assert "Фото" in cols and "Таб. ключ" in cols

def test_export_ids_order_and_csv_cp1251(src):
    con, ids, d = src
    r = api.export_persons(con, d / "x.csv", ids=[ids[2], ids[0], 999], csv_encoding="cp1251")
    assert r["rows"] == 2
    raw = (d / "x.csv").read_bytes(); raw.decode("cp1251")
    with pytest.raises(UnicodeDecodeError): raw.decode("utf-8")
    cols, rows = api.read_rows(api.open_source(d / "x.csv")[0])
    assert [r[0] for r in rows] == ["Иванов", "Ёжиков"]
    with pytest.raises(ValueError): api.export_persons(con, d / "x.csv", csv_encoding="koi8-r")
    with pytest.raises(ValueError): api.export_persons(con, d / "x.pdf")

def test_xls_row_limit(tmp_path):
    con = api.connect(); api.upsert_field(con, "n", "N")
    with con: con.executemany("INSERT INTO persons(fields_json) VALUES (?)",
                              [(json.dumps({"n": str(i)}),) for i in range(api.XLS_MAX_ROWS + 1)])
    with pytest.raises(ValueError) as ei: api.export_persons(con, tmp_path / "big.xls")
    msg = str(ei.value)
    assert "65535" in msg and "Выберите формат .xlsx" in msg and "65536" in msg
    assert not (tmp_path / "big.xls").exists()
    ok = api.export_persons(con, tmp_path / "ok.xls", ids=range(1, api.XLS_MAX_ROWS + 1))
    assert ok["rows"] == api.XLS_MAX_ROWS

def test_db_export_template_and_exists(src):
    con, ids, d = src
    Image.new("RGB", (10, 10), "blue").save(d / "ph" / "logo.png")
    api.create_element(con, "image", 0, 0, 50, 50, static_value="logo.png")
    api.create_element(con, "ellipse", 1, 2, 30, 40, side="back", style={"fill": "#FF0000"})
    api.set_background(con, "front", "#EEEEEE", "logo.png")
    r = api.export_persons(con, d / "p.db", ids=[ids[1]], photo_dir=d / "ph")
    n = api.connect(d / "p.db")
    assert api.get_schema_version(n) == db.LATEST and len(api.list_persons(n)) == 1
    assert [e["type"] for e in api.list_elements(n)] == ["ellipse", "image"]
    assert api.get_background(n, "front")["image_path"] == "logo.png" and (d / "p_photos" / "logo.png").exists()
    assert r["files_copied"] == 2
    with pytest.raises(FileExistsError): api.export_persons(con, d / "p.db")

def test_db_export_missing_photo_warns(src):
    con, ids, d = src
    api.update_person(con, ids[1], photo_path="nope.jpg")
    r = api.export_persons(con, d / "m.db", photo_dir=d / "ph")
    assert any("nope.jpg" in w for w in r["warnings"])

# ---------- источники ----------
def test_xlsx_multiple_sheets_header_limit(tmp_path):
    from openpyxl import Workbook
    wb = Workbook(); a = wb.active; a.title = "Сотрудники"
    a.append([]); a.append(["Фамилия", "Имя"]); a.append(["Ёжиков", "Пётр"]); a.append(["Щукина", "Юлия"])
    b = wb.create_sheet("Гости"); b.append(["Фамилия", "Имя"]); b.append(["Гость", "Один"])
    wb.save(tmp_path / "m.xlsx")
    sh = api.open_source(tmp_path / "m.xlsx")
    assert [(s.name, s.kind, s.index) for s in sh] == [("Сотрудники", "xlsx", 0), ("Гости", "xlsx", 1)]
    assert api.read_rows(sh[0], limit=1) == (["Фамилия", "Имя"], [["Ёжиков", "Пётр"]])
    cols, rows = api.read_rows(sh[0], header=False)
    assert cols == ["Колонка 1", "Колонка 2"] and rows[0] == ["Фамилия", "Имя"] and len(rows) == 3
    con = api.connect(); rep = _imp(api.import_rows, con, sh[1])
    assert rep.added == 1 and api.list_persons(con)[0]["fields"]["last_name"] == "Гость"
    con2 = api.connect()
    rep = _imp(api.import_rows, con2, sh[0], header=False, mapping={"Колонка 1": "last_name", "Колонка 2": "first_name"},
                          validate=False)
    assert rep.added == 3

def test_csv_encodings(tmp_path):
    for enc in ("utf-8-sig", "cp1251", "utf-8"):
        p = tmp_path / f"{enc}.csv"; p.write_text("Фамилия;Имя\nЁжиков;Пётр\n", encoding=enc)
        assert api.read_rows(api.open_source(p)[0]) == (["Фамилия", "Имя"], [["Ёжиков", "Пётр"]])

def test_auto_match_uses_headers():
    from badge_backend.services.headers import map_headers
    cols = ["ФИО", "Должность", "Фото", "Таб. номер", "Что-то"]
    assert api.auto_match(cols) == map_headers(cols) == ["__fio__", "position", "photo_path", "employee_id", "chto_to"]
    assert api.auto_match(cols, {"Что-то": None})[-1] is None

def test_unsupported_and_not_sqlite(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    with pytest.raises(ValueError): api.open_source(tmp_path / "a.pdf")
    (tmp_path / "b.db").write_bytes(b"not a database" * 200)
    with pytest.raises(ValueError): api.open_source(tmp_path / "b.db")
    with pytest.raises(FileNotFoundError): api.open_source(tmp_path / "none.csv")

# ---------- прогресс / отмена ----------
def _csv(tmp_path, n=10):
    p = tmp_path / "n.csv"
    p.write_text("Фамилия;Имя\n" + "".join(f"Фам{i};Имя{i}\n" for i in range(n)), encoding="utf-8")
    return api.open_source(p)[0]

def test_progress(tmp_path):
    calls = []; con = api.connect()
    rep = _imp(api.import_rows, con, _csv(tmp_path), progress=lambda d, t: calls.append((d, t)))
    assert rep.added == 10 and calls[0] == (0, 10) and calls[-1] == (10, 10) and len(calls) == 11

@pytest.mark.parametrize("how", ["callable", "event", "progress_false"])
def test_cancel_rolls_back(tmp_path, how):
    con = api.connect(); ev = threading.Event(); seen = []
    def prog(d, t):
        seen.append(d)
        if d == 5:
            if how == "event": ev.set()
            if how == "progress_false": return False
    kw = {"progress": prog}
    if how == "callable": kw["cancel"] = lambda: len(seen) >= 4
    if how == "event": kw["cancel"] = ev
    from badge_backend.testing import prepare_fields
    sh = _csv(tmp_path); prepare_fields(con, sh); nf = api.list_fields(con)
    rep = api.import_rows(con, sh, **kw)
    assert rep.cancelled and rep.added == 0 and api.list_persons(con) == [] and api.list_fields(con) == nf

# ---------- mapping ----------
def test_mapping_save_load(tmp_path):
    m = {"Ф.И.О. сотрудника": "__fio__", "Лишнее": None, "position": ["Пост", "Роль"]}
    p = api.save_mapping(tmp_path / "m" / "map.json", m, columns=["Ф.И.О. сотрудника", "Лишнее"])
    assert api.load_mapping(p) == m
    assert json.loads(p.read_text(encoding="utf-8"))["columns"] == ["Ф.И.О. сотрудника", "Лишнее"]
    assert "Ф.И.О." in p.read_text(encoding="utf-8")          # UTF-8 без \\u-экранирования
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError): api.load_mapping(tmp_path / "bad.json")
    (tmp_path / "other.json").write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError): api.load_mapping(tmp_path / "other.json")
    with pytest.raises(ValueError): api.save_mapping(tmp_path / "x.json", {"a": 1})
    # загруженный mapping применяется к импорту
    c = tmp_path / "c.csv"; c.write_text("Ф.И.О. сотрудника;Лишнее\nЁжиков Пётр Ильич;zzz\n", encoding="utf-8")
    con = api.connect(); _imp(api.import_rows, con, api.open_source(c)[0], api.load_mapping(p))
    assert api.list_persons(con)[0]["fields"] == {"last_name": "Ёжиков", "first_name": "Пётр", "middle_name": "Ильич"}

# ---------- .db: проектная любой версии и произвольная SQLite ----------
def _sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

@pytest.mark.parametrize("ver", [1, 2, 3, 4])
def test_legacy_project_db_import(tmp_path, ver):
    p = create_legacy_db(tmp_path / f"v{ver}.db", version=ver)
    raw = sqlite3.connect(p)
    raw.execute("INSERT INTO person_fields(name,label,sort_order) VALUES ('last_name','Фамилия',0),('first_name','Имя',1)")
    raw.execute("INSERT INTO persons(fields_json,photo_path,print_mark) VALUES (?, 'f.jpg', 1)",
                (json.dumps({"last_name": "Ёжиков", "first_name": "Пётр"}, ensure_ascii=False),))
    raw.commit(); raw.close()
    Image.new("RGB", (5, 5)).save(tmp_path / "f.jpg")
    h, m = _sha(p), os.path.getmtime(p)
    sh = api.open_source(p)
    assert [(s.kind, s.name, s.schema_version) for s in sh] == [("project", "persons", ver)]
    assert sh[0].work_path != p and api.get_schema_version(sqlite3.connect(sh[0].work_path)) == db.LATEST
    con = api.connect(); rep = _imp(api.import_rows, con, sh[0], photo_dir=tmp_path)
    assert rep.added == 1, rep
    pr = api.list_persons(con)[0]
    assert pr["fields"] == {"last_name": "Ёжиков", "first_name": "Пётр"} and pr["photo_path"] == "f.jpg" and pr["print_mark"] == 1
    w = sh[0].work_path; sh[0].close(); sh[0].close()
    assert not w.exists()
    with pytest.raises(ValueError): api.read_rows(sh[0])
    assert _sha(p) == h and os.path.getmtime(p) == m and sqlite3.connect(p).execute("PRAGMA user_version").fetchone()[0] == ver

def test_arbitrary_sqlite_readonly(tmp_path):
    p = tmp_path / "hr.sqlite"; raw = sqlite3.connect(p)
    raw.execute('CREATE TABLE "staff list"(id INTEGER, "Фамилия" TEXT, "Имя" TEXT, salary REAL)')
    raw.execute("CREATE TABLE other(x)")
    raw.executemany('INSERT INTO "staff list" VALUES (?,?,?,?)', [(1, "Ёжиков", "Пётр", 10.0), (2, "Щукина", "Юлия", 2.5)])
    raw.commit(); raw.close(); h = _sha(p)
    sh = api.open_source(p)
    assert [(s.name, s.kind) for s in sh] == [("other", "sqlite"), ("staff list", "sqlite")]
    cols, rows = api.read_rows(sh[1])
    assert cols == ["id", "Фамилия", "Имя", "salary"] and rows == [["1", "Ёжиков", "Пётр", "10"], ["2", "Щукина", "Юлия", "2.5"]]
    assert api.read_rows(sh[1], limit=1)[1] == [rows[0]]
    con = api.connect(); rep = _imp(api.import_rows, con, sh[1], {"id": None})
    assert rep.added == 2 and api.list_persons(con)[1]["fields"]["salary"] == "2.5"
    ro = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError): ro.execute("DELETE FROM other")
    assert _sha(p) == h and not (tmp_path / "hr.sqlite-journal").exists()

# ---------- фото ----------
def test_photo_path_column(tmp_path):
    p = tmp_path / "f.csv"; p.write_text("Фамилия;Имя;Путь к фото\nЁжиков;Пётр;sub/ez.jpg\n", encoding="utf-8")
    (tmp_path / "sub").mkdir(); Image.new("RGB", (5, 5)).save(tmp_path / "sub" / "ez.jpg")
    con = api.connect(); rep = _imp(api.import_rows, con, api.open_source(p)[0], photo_dir=tmp_path)
    assert rep.added == 1 and api.list_persons(con)[0]["photo_path"] == "sub/ez.jpg"

def test_xlsx_embedded_images(tmp_path):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    Image.new("RGB", (20, 30), (0, 128, 0)).save(tmp_path / "g.png")
    wb = Workbook(); ws = wb.active
    ws.append(["Фамилия", "Имя", "Фото"]); ws.append(["Ёжиков", "Пётр", None]); ws.append(["Щукина", "Юлия", "own.jpg"])
    ws.append(["Иванов", "Иван", None])
    ws.add_image(XLImage(str(tmp_path / "g.png")), "C2"); ws.add_image(XLImage(str(tmp_path / "g.png")), "C3")
    wb.save(tmp_path / "img.xlsx"); (tmp_path / "out").mkdir(); Image.new("RGB", (5, 5)).save(tmp_path / "out" / "own.jpg")
    sh = api.open_source(tmp_path / "img.xlsx")[0]
    con = api.connect(); rep = _imp(api.import_rows, con, sh, photo_dir=tmp_path / "out")
    ps = api.list_persons(con)
    assert ps[0]["photo_path"] and (tmp_path / "out" / ps[0]["photo_path"]).exists()
    assert Image.open(tmp_path / "out" / ps[0]["photo_path"]).size == (20, 30)
    assert ps[1]["photo_path"] == "own.jpg"            # путь из колонки важнее картинки
    assert ps[2]["photo_path"] is None
    with pytest.warns(RuntimeWarning, match="встроенных картинок"):
        _imp(api.import_rows, api.connect(), sh)

def test_import_file_still_works_and_xls(src):
    con, ids, d = src
    api.export_persons(con, d / "t.xls")
    tgt = api.connect(); rep = _imp(api.import_file, tgt, d / "t.xls", photo_dir=d / "ph")
    assert rep.added == 3 and _by_label(tgt) == _expected()

# ---------- решение Архитектора: ненайденное фото — предупреждение ----------
def _photo_csv(tmp_path):
    (tmp_path / "ph").mkdir(exist_ok=True); Image.new("RGB", (5, 5)).save(tmp_path / "ph" / "ok.jpg")
    (tmp_path / "ph" / "broken.jpg").write_bytes(b"not an image"); (tmp_path / "ph" / "empty.jpg").write_bytes(b"")
    p = tmp_path / "ph.csv"
    p.write_text("Фамилия;Имя;Фото\nЁжиков;Пётр;ok.jpg\nЩукина;Юлия;nope.jpg\nИванов;Иван;\nСидоров;Олег;broken.jpg\nПустов;Пётр;empty.jpg\n",
                 encoding="utf-8")
    return p

def test_missing_photo_file_imported_with_warning(tmp_path):
    p = _photo_csv(tmp_path)
    for run in ("import_rows", "import_file"):
        con = api.connect()
        rep = (_imp(api.import_rows, con, api.open_source(p)[0], photo_dir=tmp_path / "ph") if run == "import_rows"
               else _imp(api.import_file, con, p, photo_dir=tmp_path / "ph"))
        assert (rep.added, rep.skipped) == (5, 0), run
        assert {(w["row"], w["code"]) for w in rep.warnings} == \
            {(3, "PHOTO_MISSING"), (4, "PHOTO_MISSING"), (5, "PHOTO_BROKEN"), (6, "PHOTO_EMPTY")}
        assert any("nope.jpg" in w["details"] for w in rep.warnings) and rep.errors == []
        ps = api.list_persons(con)
        assert [x["photo_path"] for x in ps] == ["ok.jpg", "nope.jpg", None, None, None]   # битый/пустой — очищен
        assert ps[3]["fields"]["last_name"] == "Сидоров" and ps[4]["fields"]["last_name"] == "Пустов"
        assert api.missing_photos(con, [x["id"] for x in ps], base_dir=tmp_path / "ph") == [x["id"] for x in ps[1:]]

def test_missing_photo_file_require_photo_skips(tmp_path):
    p = _photo_csv(tmp_path); con = api.connect()
    rep = _imp(api.import_rows, con, api.open_source(p)[0], photo_dir=tmp_path / "ph", require_photo=True)
    assert rep.added == 1 and rep.skipped == 4 and rep.warnings == []
    assert {e["code"] for e in rep.errors} >= {"PHOTO_NOT_FOUND", "PHOTO_MISSING", "PHOTO_BROKEN", "PHOTO_EMPTY"}
