"""Этап 15: шаблоны, привязка/отвязка, «Фото», виды фото, поиск, время, стиль, режим правки шаблона, миграция v6→v7."""
import json, os, shutil, sqlite3, time, glob
import pytest
from PIL import Image
from badge_backend import api, db
from badge_backend.services import templates as T, search as S, photo_edit as PE
from badge_backend.render import render_card_db


def _v6(path):
    """Реалистичная v6-БД: поля, люди с фото/без, элементы обеих сторон, фоны, UTC-время, printed_at."""
    raw = sqlite3.connect(path)
    v0 = db.LATEST; db.LATEST = 6
    try: db.migrate(raw)
    finally: db.LATEST = v0
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 6
    raw.executescript("""
      INSERT INTO person_fields(name,label,sort_order,data_type) VALUES ('fio','ФИО',0,'text'),('dept','Отдел',1,'text');
      INSERT INTO persons(fields_json,photo_path,photo_config,print_mark,created_at,updated_at,printed_at) VALUES
        ('{"fio":"Иванов","dept":"ИТ"}','p/1.jpg','0;0;1.0;0;0;0',1,'2026-01-02 10:00:00','2026-01-02 11:00:00','2026-01-03T12:00:00+03:00'),
        ('{"fio":"Петров","dept":"Склад"}',NULL,'0;0;1.0;0;0;0',0,'2026-01-04 09:00:00','2026-01-04 09:00:00',NULL);
      INSERT INTO template_elements(type,x,y,w,h,field_name,static_value,side,z_order) VALUES
        ('photo',10,10,200,250,NULL,NULL,'front',0),('field',300,10,400,60,'fio',NULL,'front',1),
        ('text',300,90,400,60,NULL,'Гость','front',2),('qr',10,10,150,150,'fio',NULL,'back',0);
      INSERT INTO template_backgrounds(side,image_path,color) VALUES ('front',NULL,'#EEEEEE');
    """); raw.commit(); raw.close()


def test_migration_v6_realistic_no_loss(tmp_path):
    p = tmp_path / "v6.db"; _v6(p)
    con = db.connect(str(p)); assert db.get_schema_version(con) == 7
    ps = {r["id"]: api.get_person(con, r["id"]) for r in con.execute("SELECT id FROM persons")}
    assert ps[1]["fields"]["fio"] == "Иванов" and ps[1]["fields"]["Фото"] == "p/1.jpg" and ps[1]["photo_path"] == "p/1.jpg"
    assert "Фото" not in ps[2]["fields"] or not ps[2]["fields"]["Фото"]
    assert ps[1]["printed_at"] == "2026-01-03T12:00:00+03:00"
    assert ps[1]["created_at"][:4] == "2026" and ps[1]["created_at"][-6] in "+-"
    els = api.list_elements(con)
    assert len([e for e in els]) == 4 and {e["type"] for e in els} == {"photo", "field", "text", "qr"}
    assert [e["field_name"] for e in els if e["type"] == "photo"] == ["Фото"]
    assert api.get_background(con, "front")["color"] == "#EEEEEE"
    assert [t["name"] for t in T.list_templates(con)] == ["Основной"]


def test_migration_on_copy_of_real_dbs(tmp_path):
    srcs = [s for s in glob.glob("/tmp/bg_selftest_*/*.db") if sqlite3.connect(s).execute("PRAGMA user_version").fetchone()[0] == 6]
    if not srcs: pytest.skip("нет реальных v6-БД на машине")
    for s in srcs:
        dst = tmp_path / os.path.basename(s); shutil.copy(s, dst)
        o = sqlite3.connect(s); np, ne = o.execute("SELECT count(*) FROM persons").fetchone()[0], o.execute("SELECT count(*) FROM template_elements").fetchone()[0]; o.close()
        con = db.connect(str(dst))
        assert db.get_schema_version(con) == 7
        assert con.execute("SELECT count(*) FROM persons").fetchone()[0] == np
        assert con.execute("SELECT count(*) FROM template_elements").fetchone()[0] == ne
        assert sqlite3.connect(s).execute("PRAGMA user_version").fetchone()[0] == 6   # оригинал не тронут


def test_templates_active_and_isolated():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО")
    a = T.get_active_template(con)["id"]; api.create_element(con, "field", 0, 0, 10, 10, field_name="fio")
    b = T.create_template(con, "Гостевой", copy_from=a)
    assert len(api.list_elements(con)) == 1
    T.set_active_template(con, b); api.create_element(con, "text", 0, 0, 10, 10, static_value="x")
    assert len(api.list_elements(con)) == 2
    T.set_active_template(con, a); assert len(api.list_elements(con)) == 1
    with pytest.raises(ValueError): T.delete_template(con, a)
    assert T.delete_template(con, b) and len(T.list_templates(con)) == 1


def test_link_none_creates_and_unlink_keeps_type():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО")
    eid = api.link_field(con, None, "fio")
    e = [x for x in api.list_elements(con) if x["id"] == eid][0]
    assert e["type"] == "field" and e["field_name"] == "fio"
    assert api.unlink_field(con, eid)
    e = [x for x in api.list_elements(con) if x["id"] == eid][0]
    assert e["type"] == "field" and e["field_name"] is None


def test_photo_insert_creates_photo_field():
    con = api.connect()
    api.create_element(con, "photo", 0, 0, 100, 120)
    f = {x["name"]: x for x in api.list_fields(con)}
    assert "Фото" in f and f["Фото"]["data_type"] == "image"
    assert api.list_elements(con)[0]["field_name"] == "Фото"


def test_photo_view_nondestructive(tmp_path):
    con = api.connect(); api.create_element(con, "photo", 0, 0, 100, 120)
    Image.new("RGB", (200, 240), (100, 120, 140)).save(tmp_path / "a.jpg")
    pid = api.create_person(con, {"Фото": "a.jpg"}, photo_path="a.jpg")
    before = (tmp_path / "a.jpg").read_bytes()
    PE.set_photo_view(con, pid, {"brightness": 40})
    assert PE.get_photo_view(con, pid)["brightness"] == 40
    render_card_db(con, pid, "front", str(tmp_path))
    assert (tmp_path / "a.jpg").read_bytes() == before
    PE.set_photo_view(con, pid, None); assert PE.get_photo_view(con, pid).get("brightness", 0) == 0


def test_autoeffect_and_portrait_params():
    img = Image.new("RGB", (200, 200), (60, 60, 60))
    p = PE.autoeffect_params(img); assert p["autoeffect"] is False and "brightness" in p
    assert PE.portrait_params(img, 0.8) is None      # лица нет


def test_p7_frame_spec_uses_active_template():
    con = api.connect()
    api.create_element(con, "photo", 0, 0, 100, 200)
    b = T.create_template(con, "B"); T.set_active_template(con, b)
    api.create_element(con, "photo", 0, 0, 300, 100)
    spec = PE.get_photo_frame_spec(con)
    assert spec and abs(spec["aspect"] - 3.0) < 0.01


@pytest.mark.parametrize("tz", ["Europe/Berlin", "Asia/Tokyo"])
def test_timestamps_local_with_offset(tz, monkeypatch):
    monkeypatch.setenv("TZ", tz); time.tzset()
    try:
        con = api.connect(); pid = api.create_person(con, {})
        p = api.get_person(con, pid)
        off = time.strftime("%z"); off = off[:3] + ":" + off[3:]
        assert p["created_at"].endswith(off) and p["updated_at"].endswith(off)
        con.execute("UPDATE persons SET print_mark=1 WHERE id=?", (pid,)); con.commit()
        assert api.get_person(con, pid)["updated_at"].endswith(off)
    finally:
        monkeypatch.delenv("TZ"); time.tzset()


def test_search_parser():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО"); api.upsert_field(con, "dept", "Отдел")
    a = api.create_person(con, {"fio": "Иванов Иван", "dept": "ИТ"})
    b = api.create_person(con, {"fio": "Петров", "dept": ""})
    ids = lambda q: sorted(p["id"] for p in S.search_persons(con, q))
    assert ids("Иванов") == [a]
    assert ids("Отдел = ИТ") == [a]
    assert ids("Отдел пусто") == [b]
    assert ids("ФИО ^ Пет или Отдел = ИТ") == [a, b]
    assert ids("(ФИО ~ ван) и Отдел непусто") == [a]
    assert S.parse_search("ФИО < 3", con)["terms"][0]["op"] == "contains"   # «<» не оператор → обычный текст
    with pytest.raises(ValueError): S.parse_search("(ФИО = a", con)


def test_template_style_font_padding():
    con = api.connect()
    st = T.set_template_style(con, {"font_family": "DejaVu Sans", "padding": 12})
    assert T.get_template_style(con) == st and st["padding"] == 12
    with pytest.raises(ValueError): T.set_template_style(con, {"padding": 500})
