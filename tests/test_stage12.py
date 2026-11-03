"""Этап 12 (reports/stage-12-actions.md §3): v4, ellipse, default_value, поля/связи, query_persons, статусы, бэкап."""
import sqlite3, pytest
from PIL import ImageChops
from badge_backend import api, db
from badge_backend.render import render_card, render_card_db
from badge_backend.testing import create_legacy_db

# ---------- миграция v4 ----------
def test_v3_to_v4_keeps_data_and_ids(tmp_path):
    p = create_legacy_db(tmp_path / "v3.db", version=3)
    raw = sqlite3.connect(p)
    raw.execute("INSERT INTO person_fields(name,label,sort_order) VALUES ('fio','ФИО',0)")
    raw.execute("INSERT INTO template_elements(id,type,x,y,w,h,style_json) VALUES (7,'line',1,2,30,0,'{}')")
    raw.execute("INSERT INTO template_elements(id,type,x,y,w,h,field_name) VALUES (9,'field',5,5,100,40,'fio')")
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("INSERT INTO template_elements(type,x,y,w,h) VALUES ('ellipse',0,0,10,10)")
    raw.commit(); raw.close()
    con = api.connect(p)
    assert api.get_schema_version(con) == 4 == db.LATEST
    assert [(e["id"], e["type"]) for e in api.list_elements(con)] == [(7, "line"), (9, "field")]
    assert "default_value" in db._cols(con, "person_fields")
    assert api.list_fields(con)[0]["default_value"] is None
    eid = api.create_element(con, "ellipse", 0, 0, 10, 10)
    assert api.list_elements(con)[-1]["id"] == eid
    with pytest.raises(sqlite3.IntegrityError): api.create_element(con, "ellipse", 0, 0, 0, 10)
    assert db.migrate(con) == 4

def test_v4_idempotent_rerun():
    con = api.connect()
    con.execute("PRAGMA user_version=3"); assert db.migrate(con) == 4
    assert list(db._cols(con, "person_fields")).count("default_value") == 1

def test_legacy_helper_v4(tmp_path):
    raw = sqlite3.connect(create_legacy_db(tmp_path / "v4.db", version=4))
    assert api.get_schema_version(raw) == 4
    with pytest.raises(ValueError): create_legacy_db(tmp_path / "v5.db", version=5)

# ---------- ellipse ----------
def _el(**k): return {"id": 1, "type": "ellipse", "x": 100, "y": 100, "w": 400, "h": 200, **k}

def test_ellipse_fill_stroke():
    im = render_card(None, [_el(style_json='{"fill":"#00FF00","stroke":"#FF0000","stroke_width":4}')])
    assert im.getpixel((300, 200)) == (0, 255, 0)     # центр — заливка
    assert im.getpixel((101, 101)) == (255, 255, 255)  # угол рамки — вне эллипса
    assert im.getpixel((300, 101)) == (255, 0, 0)      # верх — обводка

def test_ellipse_empty_style_draws_nothing_and_ignores_radius():
    blank = render_card(None, [])
    assert ImageChops.difference(render_card(None, [_el()]), blank).getbbox() is None
    a = render_card(None, [_el(style_json='{"fill":"#123456"}')])
    b = render_card(None, [_el(style_json='{"fill":"#123456","radius":40}')])
    assert a.tobytes() == b.tobytes()

def test_ellipse_stroke_only_default_width_and_legacy_keys():
    a = render_card(None, [_el(style_json='{"stroke":"#000000"}')])
    b = render_card(None, [_el(style_json='{"border_color":"#000000","border_width":1}')])
    assert a.tobytes() == b.tobytes() and a.getpixel((300, 200)) == (255, 255, 255)

def test_ellipse_via_db():
    con = api.connect(); api.create_element(con, "ellipse", 10, 10, 100, 100, style={"fill": "#0000FF"})
    assert render_card_db(con, None).getpixel((60, 60)) == (0, 0, 255)

# ---------- default_value ----------
def _db_with_field():
    con = api.connect(); api.upsert_field(con, "dept", "Отдел")
    api.create_element(con, "field", 50, 50, 600, 120, field_name="dept", style={"font_size": 40})
    return con

def test_default_value_substituted_when_empty():
    con = _db_with_field()
    pe = api.create_person(con, {"dept": ""}); pn = api.create_person(con, {}); pv = api.create_person(con, {"dept": "ИТ"})
    blank = render_card_db(con, pe)
    api.set_field_default(con, "dept", "Гость")
    assert api.list_fields(con)[0]["default_value"] == "Гость"
    d_empty, d_none = render_card_db(con, pe), render_card_db(con, pn)
    assert ImageChops.difference(d_empty, blank).getbbox() is not None
    assert d_empty.tobytes() == d_none.tobytes()
    ref = render_card(None, [dict(type="text", x=50, y=50, w=600, h=120, static_value="Гость", style_json='{"font_size":40}')])
    assert d_empty.tobytes() == ref.tobytes()
    v = render_card_db(con, pv)  # непустое значение — default не применяется
    assert v.tobytes() != d_empty.tobytes()
    api.set_field_default(con, "dept", None)
    assert render_card_db(con, pe).tobytes() == blank.tobytes()

def test_default_value_in_export_snapshot(tmp_path):
    con = _db_with_field(); api.set_field_default(con, "dept", "Гость")
    pid = api.create_person(con, {}, print_mark=1)
    snap = api.snapshot(con, [pid], ("front",))
    assert any(e.get("default_value") == "Гость" for j in snap for e in j["elements"])

def test_default_value_qr_barcode():
    con = api.connect(); api.upsert_field(con, "code", "Код")
    api.create_element(con, "qr", 10, 10, 300, 300, field_name="code")
    pid = api.create_person(con, {})
    empty = render_card_db(con, pid); api.set_field_default(con, "code", "000123")
    assert ImageChops.difference(render_card_db(con, pid), empty).getbbox() is not None

def test_set_field_default_unknown():
    with pytest.raises(ValueError): api.set_field_default(api.connect(), "nope", "x")

# ---------- поля ----------
def test_upsert_field_default_value_and_list():
    con = api.connect()
    api.upsert_field(con, "a", "А", 1, default_value="x")
    assert api.list_fields(con)[0]["default_value"] == "x"
    api.upsert_field(con, "a", "А2", 1)                       # ... — не трогать default
    assert api.list_fields(con)[0] == {"name": "a", "label": "А2", "sort_order": 1, "default_value": "x"}
    api.upsert_field(con, "a", "А2", 1, default_value=None)
    assert api.list_fields(con)[0]["default_value"] is None
    api.set_field_default(con, "a", "y"); assert api.list_fields(con)[0]["default_value"] == "y"
    api.set_field_default(con, "a", ""); assert api.list_fields(con)[0]["default_value"] is None

def test_link_unlink_and_links():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО"); api.upsert_field(con, "code", "Код")
    f = api.create_element(con, "field", 0, 0, 100, 50, field_name="code", static_value="Иванов")
    q = api.create_element(con, "qr", 0, 0, 100, 100, side="back")
    b = api.create_element(con, "barcode", 0, 0, 300, 100)
    t = api.create_element(con, "text", 0, 0, 100, 50)
    assert api.link_field(con, f, "fio") and api.link_field(con, q, "fio") and api.link_field(con, b, "code")
    L = api.list_field_links(con)
    assert {k: [(e["element_id"], e["type"], e["side"]) for e in v] for k, v in L.items()} == \
        {"fio": [(f, "field", "front"), (q, "qr", "back")], "code": [(b, "barcode", "front")]}
    assert L["fio"][0]["label"] == "Иванов" and L["fio"][0]["id"] == f
    r = api.create_element(con, "rect", 0, 0, 10, 10)
    with pytest.raises(ValueError): api.link_field(con, r, "fio")          # rect — не привязывается
    with pytest.raises(ValueError): api.link_field(con, f, "nope")
    assert api.link_field(con, 999, "fio") is False
    assert api.unlink_field(con, f)
    e = [x for x in api.list_elements(con) if x["id"] == f][0]
    assert (e["type"], e["field_name"], e["static_value"]) == ("text", None, "Иванов")
    assert api.unlink_field(con, q, static_value="000123")
    e = [x for x in api.list_elements(con) if x["id"] == q][0]
    assert (e["type"], e["field_name"], e["static_value"]) == ("qr", None, "000123")
    assert api.unlink_field(con, 999) is False
    assert api.list_field_links(con) == {"code": [{"element_id": b, "id": b, "type": "barcode", "side": "front", "label": ""}]}

def test_delete_field():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО"); api.upsert_field(con, "free", "x")
    f = api.create_element(con, "field", 0, 0, 100, 50, field_name="fio")
    with pytest.raises(ValueError): api.delete_field(con, "fio", unlink=False)
    assert [x["name"] for x in api.list_fields(con)] == ["free", "fio"] or len(api.list_fields(con)) == 2
    assert api.delete_field(con, "free", unlink=False)
    assert api.delete_field(con, "fio") and api.list_fields(con) == []
    assert api.list_elements(con)[0]["type"] == "text" and api.list_elements(con)[0]["field_name"] is None
    assert api.delete_field(con, "fio") is False

# ---------- карты / статусы ----------
def test_delete_persons_and_clear_printed():
    con = api.connect(); ids = [api.create_person(con, {"n": str(k)}) for k in range(4)]
    api.set_print_mark(con, ids[:3], 1); api.mark_printed(con, ids[:2]); api.set_print_mark(con, [ids[0]], 1)
    assert api.clear_printed(con, [ids[0], ids[2], 999]) == 1
    p0 = api.get_person(con, ids[0]); assert p0["printed_at"] is None and p0["print_mark"] == 1  # mark не тронут
    assert api.get_person(con, ids[1])["printed_at"] is not None
    assert api.delete_persons(con, [ids[0], ids[3], 999]) == 2
    assert [p["id"] for p in api.list_persons(con)] == [ids[1], ids[2]]
    assert api.delete_persons(con, []) == 0

# ---------- query_persons ----------
@pytest.fixture
def qcon():
    con = api.connect()
    for n in ("fio", "dept"): api.upsert_field(con, n, n)
    ids = [api.create_person(con, f) for f in (
        {"fio": "Иванов Иван", "dept": "ИТ"}, {"fio": "Петров Пётр", "dept": "Бухгалтерия"},
        {"fio": "иванова Анна", "dept": "  "}, {"fio": "Сидоров"})]
    api.set_print_mark(con, [ids[0], ids[1]], 1); api.mark_printed(con, [ids[1]])
    return con, ids

def _ids(rows): return [r["id"] for r in rows]
def C(f, op, v=None): return {"field": f, "op": op, "value": v}

def test_query_ops(qcon):
    con, i = qcon
    Q = lambda *t, **k: _ids(api.query_persons(con, {"join": "and", "terms": list(t)} if t else None, **k))
    assert Q() == i
    assert Q(C("fio", "contains", "ИВАН")) == [i[0], i[2]]
    assert Q(C("fio", "startswith", "иванов")) == [i[0], i[2]]
    assert Q(C("dept", "eq", "ит")) == [i[0]]
    assert Q(C("dept", "ne", "ИТ")) == [i[1], i[2], i[3]]
    assert Q(C("dept", "empty")) == [i[2], i[3]]
    assert Q(C("dept", "not_empty")) == [i[0], i[1]]
    assert Q(C("id", "eq", str(i[2]))) == [i[2]]
    assert Q(C("print_mark", "eq", "1")) == [i[0]]
    assert Q(C("printed_at", "not_empty")) == [i[1]]
    assert _ids(api.query_persons(con, C("fio", "contains", "сидор"))) == [i[3]]   # одиночное условие

def test_query_join_nested_flags_order(qcon):
    con, i = qcon
    t = [C("dept", "eq", "ИТ"), C("dept", "eq", "бухгалтерия")]
    assert _ids(api.query_persons(con, {"join": "and", "terms": t})) == []
    assert _ids(api.query_persons(con, {"join": "or", "terms": t})) == [i[0], i[1]]
    w = {"join": "and", "terms": [{"join": "or", "terms": t}, C("fio", "contains", "сидор")]}
    assert _ids(api.query_persons(con, w)) == []
    w["terms"][1] = C("fio", "contains", "пётр"); assert _ids(api.query_persons(con, w)) == [i[1]]
    assert _ids(api.query_persons(con, printed=True)) == [i[1]]
    assert _ids(api.query_persons(con, printed=False)) == [i[0], i[2], i[3]]
    assert _ids(api.query_persons(con, only_marked=True)) == [i[0]]
    assert _ids(api.query_persons(con, {"join": "or", "terms": t}, printed=False)) == [i[0]]
    assert _ids(api.query_persons(con, order_by="-id")) == i[::-1]
    assert _ids(api.query_persons(con, order_by="fio")) == [i[0], i[2], i[1], i[3]]
    r = api.query_persons(con, C("dept", "eq", "ИТ"))[0]
    assert r["fields"]["fio"] == "Иванов Иван" and "printed_at" in r

@pytest.mark.parametrize("bad,kw", [
    (C("fio') OR 1=1 --", "eq", "x"), {}),
    (C("fio", "gt", "1"), {}),
    (C("fio", "eq"), {}),
    ({"join": "xor", "terms": []}, {}),
    ({"join": "and", "terms": ["1=1"]}, {}),
    (None, {"order_by": "id; DROP TABLE persons"}),
])
def test_query_rejects(qcon, bad, kw):
    with pytest.raises(ValueError): api.query_persons(qcon[0], bad, **kw)

def test_query_value_is_literal(qcon):
    con, _ = qcon
    assert api.query_persons(con, C("fio", "contains", "' OR 1=1 --")) == []
    assert api.query_persons(con, C("fio", "contains", "%")) == []
    assert len(api.list_persons(con)) == 4

# ---------- бэкап / сжатие / восстановление ----------
def _filled(tmp_path):
    p = tmp_path / "project.db"; con = api.connect(p)
    for k in range(200): api.create_person(con, {"fio": "x" * 500, "n": str(k)})
    with con: con.execute("DELETE FROM persons WHERE id > 5")
    return p, con

def test_backup_and_vacuum(tmp_path):
    p, con = _filled(tmp_path)
    out = api.backup_db(con, tmp_path / "bk" / "b1.db")
    assert out == tmp_path / "bk" / "b1.db" and not (tmp_path / "bk" / "b1.db.tmp").exists()
    b = api.connect(out); assert len(api.list_persons(b)) == 5 and api.get_schema_version(b) == 4; b.close()
    with pytest.raises(ValueError): api.backup_db(con, p)
    r = api.vacuum_db(con)
    assert set(r) == {"size_before", "size_after"} and r["size_after"] < r["size_before"]
    assert p.stat().st_size == r["size_after"]

def test_compact_and_backup(tmp_path):
    p, con = _filled(tmp_path)
    r = api.compact_and_backup(con, tmp_path / "bk")
    assert r["integrity"] == "ok" and r["size_after"] < r["size_before"] and r["backup"].parent == tmp_path / "bk"
    assert r["backup"].name.startswith("project-")
    r2 = api.compact_and_backup(con, tmp_path / "bk")
    assert r2["backup"] != r["backup"] and len(api.list_persons(api.connect(r["backup"]))) == 5

def test_restore_db(tmp_path):
    p, con = _filled(tmp_path)
    bk = api.backup_db(con, tmp_path / "b.db")
    api.delete_persons(con, [1, 2, 3]); con.close()
    api.restore_db(p, bk)
    c = api.connect(p); assert len(api.list_persons(c)) == 5; c.close()
    # бэкап старой версии мигрирует
    old = create_legacy_db(tmp_path / "v2.db", version=2)
    api.restore_db(tmp_path / "t.db", old)
    assert api.get_schema_version(sqlite3.connect(tmp_path / "t.db")) == 4
    bad = tmp_path / "bad.db"; bad.write_bytes(b"not a database" * 100)
    with pytest.raises(ValueError): api.restore_db(tmp_path / "t2.db", bad)
    zero = tmp_path / "zero.db"; sqlite3.connect(zero).execute("CREATE TABLE x(a)").connection.commit()
    with pytest.raises(ValueError): api.restore_db(tmp_path / "t3.db", zero)        # schema_version 0
    with pytest.raises(FileNotFoundError): api.restore_db(tmp_path / "t4.db", tmp_path / "missing.db")
    with pytest.raises(ValueError): api.restore_db(bk, bk)

# ---------- цикл link → unlink → link (решение Архитектора) ----------
def _el_by_id(con, i): return [x for x in api.list_elements(con) if x["id"] == i][0]
_GEOM = ("x", "y", "w", "h", "side", "z_order", "style")

def test_cycle_text():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО")
    t = api.create_element(con, "text", 11, 22, 333, 44, side="back", z_order=3, static_value="Иванов",
                           style={"font_size": 30, "bold": True})
    g0 = {k: _el_by_id(con, t)[k] for k in _GEOM}
    assert api.link_field(con, t, "fio")
    e = _el_by_id(con, t); assert (e["type"], e["field_name"], e["static_value"]) == ("field", "fio", None)
    assert {k: e[k] for k in _GEOM} == g0
    assert api.unlink_field(con, t)
    e = _el_by_id(con, t); assert (e["type"], e["field_name"], e["static_value"]) == ("text", None, None)
    assert api.link_field(con, t, "fio") and _el_by_id(con, t)["type"] == "field"
    assert api.unlink_field(con, t, static_value="Петров")
    e = _el_by_id(con, t); assert (e["type"], e["field_name"], e["static_value"]) == ("text", None, "Петров")
    assert api.link_field(con, t, "fio")
    e = _el_by_id(con, t); assert (e["type"], e["field_name"], e["static_value"]) == ("field", "fio", None)
    assert {k: e[k] for k in _GEOM} == g0
    assert api.list_field_links(con)["fio"][0]["element_id"] == t

@pytest.mark.parametrize("typ", ["barcode", "qr"])
def test_cycle_barcode_qr(typ):
    con = api.connect(); api.upsert_field(con, "code", "Код")
    i = api.create_element(con, typ, 5, 6, 300, 300, static_value="111", style={"format": "code128"})
    g0 = {k: _el_by_id(con, i)[k] for k in _GEOM}
    for _ in range(2):
        assert api.link_field(con, i, "code")
        e = _el_by_id(con, i); assert (e["type"], e["field_name"]) == (typ, "code")
        assert api.unlink_field(con, i)
        e = _el_by_id(con, i); assert (e["type"], e["field_name"], e["static_value"]) == (typ, None, "111")
    assert api.link_field(con, i, "code") and api.unlink_field(con, i, static_value="222")
    e = _el_by_id(con, i); assert (e["type"], e["field_name"], e["static_value"]) == (typ, None, "222")
    assert api.link_field(con, i, "code") and _el_by_id(con, i)["field_name"] == "code"
    assert {k: _el_by_id(con, i)[k] for k in _GEOM} == g0
