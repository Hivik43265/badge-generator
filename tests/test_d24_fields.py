"""D24: person_fields — единственный источник полей; data_type; импорт не создаёт поля; фото-проблемы в отчёте."""
import sqlite3, warnings
import pytest
from badge_backend import api, db
from badge_backend.fields import normalize_value, format_value, FieldValueWarning
from badge_backend.render import render_card
from badge_backend.testing import create_legacy_db


def _csv(p, text): p.write_text(text, encoding="utf-8"); return p

def test_new_db_has_no_fields():
    con = api.connect()
    assert api.list_fields(con) == [] and api.get_schema_version(con) == 6 == db.LATEST

def test_v4_to_v5_existing_fields_become_text(tmp_path):
    p = create_legacy_db(tmp_path / "v4.db", version=4); raw = sqlite3.connect(p)
    raw.execute("INSERT INTO person_fields(name,label,sort_order) VALUES ('a','А',0)"); raw.commit(); raw.close()
    con = api.connect(p)
    assert api.list_fields(con) == [{"name": "a", "label": "А", "sort_order": 0, "default_value": None, "data_type": "text"}]
    with pytest.raises(sqlite3.IntegrityError):
        with con: con.execute("UPDATE person_fields SET data_type='blob'")
    con.execute("PRAGMA user_version=4"); assert db.migrate(con) == 6   # идемпотентно

def test_upsert_field_data_type():
    con = api.connect()
    api.upsert_field(con, "bd", "Дата рождения", 0, data_type="date")
    api.upsert_field(con, "bd", "ДР", 1)                       # None — тип не меняется
    assert api.list_fields(con)[0]["data_type"] == "date" and api.list_fields(con)[0]["label"] == "ДР"
    api.set_field_type(con, "bd", "number"); assert api.list_fields(con)[0]["data_type"] == "number"
    with pytest.raises(ValueError): api.upsert_field(con, "x", "X", data_type="blob")
    with pytest.raises(ValueError): api.set_field_type(con, "nope", "text")

@pytest.mark.parametrize("t,v,exp,bad", [
    ("date", "05.03.1990", "1990-03-05", False), ("date", "1990-03-05", "1990-03-05", False),
    ("date", "31.02.2020", "31.02.2020", True), ("date", "вчера", "вчера", True),
    ("number", "1 234,50", "1234.50", False), ("number", "42.0", "42", False), ("number", "abc", "abc", True),
    ("bool", "Да", "1", False), ("bool", "false", "0", False), ("bool", "может", "может", True),
    ("text", " a ", " a ", False), ("date", "", "", False)])
def test_normalize_value(t, v, exp, bad):
    sv, err = normalize_value(t, v); assert sv == exp and bool(err) == bad

def test_format_value():
    assert format_value({"data_type": "date"}, "1990-03-05") == "05.03.1990"
    assert format_value("bool", "1") == "Да" and format_value("bool", "0") == "Нет"
    assert format_value("text", "x") == "x" and format_value("date", None) == ""

def test_save_validation_warning_safe():
    con = api.connect()
    api.upsert_field(con, "bd", "ДР", data_type="date"); api.upsert_field(con, "n", "N", data_type="number")
    api.upsert_field(con, "photo", "Фото", data_type="image")
    pid = api.create_person(con, {"bd": "05.03.1990", "n": "7,5", "photo": "a.jpg", "free": 1})
    p = api.get_person(con, pid)
    assert p["fields"] == {"bd": "1990-03-05", "n": "7.5", "photo": "a.jpg", "free": 1} and p["photo_path"] is None
    with pytest.warns(FieldValueWarning):
        api.update_person(con, pid, {"bd": "31.02.2020"})
    assert api.get_person(con, pid)["fields"]["bd"] == "31.02.2020"          # сохранено как есть
    assert api.validate_fields(con, {"bd": "xx", "n": "1"}) == [{"field": "bd", "code": "FIELD_TYPE", "details": pytest.approx(
        api.validate_fields(con, {"bd": "xx"})[0]["details"])}]
    api.update_person(con, pid, {"photo": "b.jpg"}); assert api.get_person(con, pid)["fields"]["photo"] == "b.jpg"

def test_render_uses_format_value():
    con = api.connect(); api.upsert_field(con, "bd", "ДР", data_type="date")
    api.create_element(con, "field", 10, 10, 400, 80, field_name="bd")
    els = api.list_elements(con)
    from badge_backend.render import load_elements
    el = load_elements(con, "front")[0]; assert el["data_type"] == "date"
    pid = api.create_person(con, {"bd": "1990-03-05"})
    a = render_card(api.get_person(con, pid), [el])
    b = render_card({"fields": {"bd": "05.03.1990"}}, [{**el, "data_type": "text"}])
    assert a.tobytes() == b.tobytes() and els

def test_import_does_not_create_fields_and_reports_skipped(tmp_path):
    p = _csv(tmp_path / "a.csv", "Фамилия;Имя;Цех;ДР\nИванов;Иван;7;05.03.1990\nПетров;Пётр;8;bad\n")
    con = api.connect()
    rep = api.import_file(con, p)
    assert api.list_fields(con) == [] and rep.added == 2
    assert [c["label"] for c in rep.skipped_columns] == ["Фамилия", "Имя", "Цех", "ДР"]
    assert all(x["fields"] == {} for x in api.list_persons(con))
    con = api.connect()
    api.upsert_field(con, "last_name", "Фамилия", 0); api.upsert_field(con, "dr", "ДР", 1, data_type="date")
    sh = api.open_source(p)[0]
    keys = api.auto_match(api.read_rows(sh)[0], fields=con)
    assert keys == ["last_name", None, None, "dr"]                     # ДР — по label существующего поля
    rep = api.import_rows(con, sh)                                     # ДР сопоставлен по label и при импорте
    assert rep.added == 1 and [c["label"] for c in rep.skipped_columns] == ["Имя", "Цех"]
    ps = api.list_persons(con)
    assert ps[0]["fields"] == {"last_name": "Иванов", "dr": "1990-03-05"}
    assert [(e["row"], e["code"], e["field"]) for e in rep.errors] == [(3, "FIELD_TYPE", "dr")]   # D25: ошибка, строка пропущена
    assert [f["name"] for f in api.list_fields(con)] == ["last_name", "dr"]

def test_project_import_fields_flag(tmp_path):
    src = api.connect(tmp_path / "src.db")
    api.upsert_field(src, "last_name", "Фамилия"); api.upsert_field(src, "bd", "ДР", 1, default_value="—", data_type="date")
    api.create_person(src, {"last_name": "Иванов", "first_name": "Иван", "bd": "05.03.1990"}); src.close()
    con = api.connect(); sh = api.open_source(tmp_path / "src.db")[0]
    rep = api.import_rows(con, sh)                       # по умолчанию поля не переносятся
    assert api.list_fields(con) == [] and rep.added == 1 and {c["key"] for c in rep.skipped_columns} >= {"last_name", "bd"}
    con = api.connect(); api.upsert_field(con, "last_name", "Ф")
    rep = api.import_rows(con, sh, import_fields=True); sh.close()
    f = {x["name"]: x for x in api.list_fields(con)}
    assert set(f) == {"last_name", "bd"} and f["last_name"]["label"] == "Ф"
    assert (f["bd"]["data_type"], f["bd"]["default_value"], f["bd"]["label"]) == ("date", "—", "ДР")
    assert api.list_persons(con)[0]["fields"] == {"last_name": "Иванов", "bd": "1990-03-05"}
    assert [c["key"] for c in rep.skipped_columns] == ["first_name"]

def test_image_field_value_kept_in_fields(tmp_path):
    from badge_backend import demo
    ph = tmp_path / "ph"; ph.mkdir(); demo.make_photo(ph / "a.jpg")
    p = _csv(tmp_path / "a.csv", "Фамилия;Снимок\nИванов;a.jpg\n")
    con = api.connect(); api.upsert_field(con, "last_name", "Фамилия"); api.upsert_field(con, "snap", "Снимок", data_type="image")
    rep = api.import_rows(con, api.open_source(p)[0], photo_dir=ph)
    p0 = api.list_persons(con)[0]
    assert rep.added == 1 and p0["photo_path"] is None and p0["fields"]["snap"] == "a.jpg" and rep.warnings == []

# ---------- фото: пустые/битые ----------
def _photos(tmp_path):
    from badge_backend import demo
    ph = tmp_path / "ph"; ph.mkdir(); demo.make_photo(ph / "ok.jpg")
    (ph / "broken.jpg").write_bytes(b"not an image"); (ph / "empty.jpg").write_bytes(b"")
    return ph

@pytest.mark.parametrize("name,code", [("broken.jpg", "PHOTO_BROKEN"), ("empty.jpg", "PHOTO_EMPTY")])
def test_bad_photo_imported_without_photo(tmp_path, name, code):
    ph = _photos(tmp_path)
    p = _csv(tmp_path / "a.csv", f"Фамилия;Имя;Фото\nЁжиков;Пётр;ok.jpg\nСидоров;Олег;{name}\n")
    con = api.connect(); api.upsert_field(con, "last_name", "Фамилия"); api.upsert_field(con, "first_name", "Имя")
    rep = api.import_rows(con, api.open_source(p)[0], photo_dir=ph)
    assert rep.added == 2 and rep.errors == []
    assert rep.photo_issues == [{"row": 3, "code": code, "file": name}]
    assert [(w["row"], w["code"]) for w in rep.warnings] == [(3, code)]
    assert [x["photo_path"] for x in api.list_persons(con)] == ["ok.jpg", None]
    assert "photo_issues" in rep.as_dict()
    con2 = api.connect(); api.upsert_field(con2, "last_name", "Фамилия"); api.upsert_field(con2, "first_name", "Имя")
    rep = api.import_rows(con2, api.open_source(p)[0], photo_dir=ph, require_photo=True)
    assert rep.added == 1 and rep.skipped == 1 and rep.errors[0]["code"] == code

@pytest.mark.parametrize("payload,code", [(b"\x89PNG\r\n\x1a\nbroken", "PHOTO_BROKEN"), (b"", "PHOTO_EMPTY")])
def test_bad_embedded_xlsx_image_not_copied(tmp_path, payload, code, monkeypatch):
    """Встроенная картинка xlsx, оказавшаяся битой/пустой, не остаётся в photo_dir."""
    from openpyxl import Workbook
    from badge_backend.services import sources
    wb = Workbook(); ws = wb.active; ws.append(["Фамилия", "Имя"]); ws.append(["Иванов", "Иван"]); wb.save(tmp_path / "a.xlsx")
    out = tmp_path / "out"
    def fake(sheet, photo_dir, off):
        out.mkdir(exist_ok=True); (out / "img_r2.png").write_bytes(payload); return {2: "img_r2.png"}, 0
    monkeypatch.setattr(sources, "_xlsx_images", fake)
    monkeypatch.setattr("openpyxl.load_workbook", __import__("openpyxl").load_workbook)
    con = api.connect(); api.upsert_field(con, "last_name", "Фамилия"); api.upsert_field(con, "first_name", "Имя")
    rep = api.import_rows(con, api.open_source(tmp_path / "a.xlsx")[0], photo_dir=out)
    assert rep.added == 1 and rep.photo_issues == [{"row": 2, "code": code, "file": "img_r2.png"}]
    assert not (out / "img_r2.png").exists() and api.list_persons(con)[0]["photo_path"] is None


def test_d27_validate_false_keeps_whitespace(tmp_path):
    p = _csv(tmp_path / "a.csv", "Фамилия;Имя\n  Иванов  ;Иван\n")
    for v, exp in ((False, "  Иванов  "), (True, "Иванов")):
        con = api.connect(); api.upsert_field(con, "last_name", "Фамилия")
        api.import_rows(con, api.open_source(p)[0], validate=v)
        assert api.list_persons(con)[0]["fields"]["last_name"] == exp

def test_d26_name_then_label():
    con = api.connect(); api.upsert_field(con, "code", "Таб. №"); api.upsert_field(con, "note", "Примечание")
    api.upsert_field(con, "dept", "Отдел")
    assert api.auto_match(["code", " таб.  № ", "ПРИМЕЧАНИЕ", "Отдел", "Лишнее"], fields=con) == ["code", None, "note", "dept", None]
    assert api.auto_match(["таб. №"], fields=con) == ["code"]

def test_d28_print_columns_roundtrip(tmp_path):
    src = api.connect(); api.upsert_field(src, "last_name", "Фамилия")
    a, b, c = (api.create_person(src, {"last_name": n}) for n in "АБВ")
    api.set_print_mark(src, [a, c], True); api.mark_printed(src, [c])
    for fmt in ("xlsx", "xls", "csv"):
        out = tmp_path / f"p.{fmt}"; api.export_persons(src, out, fmt)
        cols, rows = api.read_rows(api.open_source(out)[0])
        assert cols[-3:] == ["Отметка печати", "Напечатано", "Дата печати"]
        assert [r[-2] for r in rows] == ["нет", "нет", "да"] and rows[2][-1].count(".") == 2
        tgt = api.connect(); api.upsert_field(tgt, "last_name", "Фамилия")
        rep = api.import_rows(tgt, api.open_source(out)[0])
        assert rep.errors == [] and rep.skipped_columns == []
        got = [(p["print_mark"], p["printed_at"] is not None) for p in api.list_persons(tgt)]
        assert got == [(1, False), (0, False), (0, True)], fmt
        assert api.list_persons(tgt)[2]["printed_at"][:10] == api.list_persons(src)[2]["printed_at"][:10]
