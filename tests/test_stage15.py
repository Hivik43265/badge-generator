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
    p = PE.autoeffect_params(img); assert p["autoeffect"] is True and "brightness" in p
    assert PE.portrait_params(img, 0.8) is None      # лица нет


def test_p7_frame_spec_uses_active_template():
    con = api.connect()
    api.create_element(con, "photo", 0, 0, 100, 200)
    b = T.create_template(con, "B"); T.set_active_template(con, b)
    api.create_element(con, "photo", 0, 0, 300, 100)
    spec = PE.get_photo_frame_spec(con)
    assert spec and abs(spec["aspect"] - 3.0) < 0.01


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset нет на Windows")
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


# ---------- photo_config → person_photo_views: рендер до/после миграции пиксель в пиксель ----------
import subprocess, sys, tarfile, io
from pathlib import Path
BASE_COMMIT = "db5d65b"   # последняя v6-версия Backend
_OLD_RENDER = r"""
import sqlite3, sys
from badge_backend.render import render_card_db
con = sqlite3.connect(sys.argv[1]); con.row_factory = sqlite3.Row
for pid, in con.execute("SELECT id FROM persons").fetchall():
    for side in ("front", "back"):
        render_card_db(con, pid, side, sys.argv[2]).save(f"{sys.argv[3]}/{pid}_{side}.png")
"""

def _old_backend(tmp):
    repo = Path(__file__).resolve().parents[1]
    try: data = subprocess.run(["git", "-C", str(repo), "archive", BASE_COMMIT, "badge_backend"], check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError): pytest.skip("нет git/коммита v6 для эталонного рендера")
    d = tmp / "old"; d.mkdir(); tarfile.open(fileobj=io.BytesIO(data)).extractall(d, filter="data"); return d

def _compare_before_after(tmp, dbfile, base):
    """Рендер старым кодом (v6, без миграции) vs новым (после миграции копии) — идентичность пикселей."""
    old = _old_backend(tmp); out = tmp / "old_png"; out.mkdir()
    subprocess.run([sys.executable, "-c", _OLD_RENDER, str(dbfile), str(base), str(out)], check=True,
                   cwd=old, env={**os.environ, "PYTHONPATH": str(old)})
    mig = tmp / ("mig_" + dbfile.name); shutil.copy(dbfile, mig)
    con = db.connect(str(mig)); n = 0
    for (pid,) in con.execute("SELECT id FROM persons").fetchall():
        for side in ("front", "back"):
            a = Image.open(out / f"{pid}_{side}.png"); b = render_card_db(con, pid, side, str(base))
            assert a.mode == b.mode and a.size == b.size and a.tobytes() == b.tobytes(), (dbfile, pid, side); n += 1
    return n

def test_photo_config_migrated_render_pixel_identical(tmp_path):
    p = tmp_path / "v6.db"; _v6(p)
    Image.radial_gradient("L").convert("RGB").resize((300, 400)).save(tmp_path / "1.jpg")
    (tmp_path / "p").mkdir(); Image.new("RGB", (320, 240), (200, 30, 90)).save(tmp_path / "p" / "1.jpg")
    raw = sqlite3.connect(p)
    raw.execute("UPDATE persons SET photo_config='12;-7;1.3;5;9;15' WHERE id=1")
    raw.execute("INSERT INTO persons(fields_json,photo_path,photo_config) VALUES ('{\"fio\":\"Сидоров\"}','1.jpg','-20;4;0.8;0;30;-90')")
    raw.commit(); raw.close()
    assert _compare_before_after(tmp_path, p, tmp_path) == 6
    con = db.connect(str(p))
    assert PE.get_photo_view(con, 1)["placement"] == "12;-7;1.3;5;9;15"
    api.update_photo_config(con, 1, "1;2;1.0;0;0;0")                    # колонка → вид (триггер)
    assert PE.get_photo_view(con, 1)["placement"] == "1;2;1.0;0;0;0"
    pid = api.create_person(con, {}, photo_path="1.jpg", photo_config="3;3;1.0;0;0;0")
    assert PE.get_photo_view(con, pid)["placement"] == "3;3;1.0;0;0;0"

def test_render_photo_matches_card_zone_after_migrated_placement(tmp_path):
    """После миграции v6 photo_config превью render_photo совпадает с зоной фото на карточке."""
    p = tmp_path / "v6.db"; _v6(p)
    (tmp_path / "p").mkdir()
    Image.radial_gradient("L").convert("RGB").resize((320, 240)).save(tmp_path / "p" / "1.jpg")
    raw = sqlite3.connect(p)
    raw.execute("UPDATE persons SET photo_config='12;-7;1.3;5;9;15' WHERE id=1")
    raw.commit(); raw.close()
    con = db.connect(str(p))
    assert PE.get_photo_view(con, 1)["placement"] == "12;-7;1.3;5;9;15"
    el = next(e for e in api.list_elements(con) if e["type"] == "photo")
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    card = render_card_db(con, 1, "front", str(tmp_path))
    zone = card.crop((x, y, x + w, y + h)).convert("RGB")
    preview = PE.render_photo(con, 1, size=(w, h), base_dir=tmp_path).convert("RGBA")
    # зона карточки = плитка поверх фона (#EEEEEE из v6); прозрачные углы после placement
    expected = Image.new("RGB", (w, h), (0xEE, 0xEE, 0xEE))
    expected.paste(preview.convert("RGB"), (0, 0), preview.getchannel("A"))
    assert expected.size == zone.size and expected.tobytes() == zone.tobytes()


def test_real_selftest_dbs_render_identical_after_migration(tmp_path):
    srcs = [Path(s) for s in glob.glob("/tmp/bg_selftest_*/*.db") if sqlite3.connect(s).execute("PRAGMA user_version").fetchone()[0] == 6]
    if not srcs: pytest.skip("нет реальных v6-БД на машине")
    for i, s in enumerate(srcs):
        t = tmp_path / str(i); t.mkdir(); c = t / s.name; shutil.copy(s, c)
        _compare_before_after(t, c, s.parent)
        assert sqlite3.connect(s).execute("PRAGMA user_version").fetchone()[0] == 6


# ---------- field без field_name: новый — запрещён, отвязанный — допустим (замена CHECK из test_schema) ----------
def test_create_field_without_field_name_rejected():
    con = api.connect()
    with pytest.raises(sqlite3.IntegrityError): api.create_element(con, "field", 0, 0, 10, 10)
    with pytest.raises(sqlite3.IntegrityError): api.create_element(con, "field", 0, 0, 10, 10, field_name="")
    assert api.list_elements(con) == []

def test_unlinked_field_with_null_field_name_allowed():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО")
    eid = api.create_element(con, "field", 0, 0, 10, 10, field_name="fio")
    assert api.unlink_field(con, eid, static_value="—")
    r = con.execute("SELECT type, field_name, static_value FROM template_elements WHERE id=?", (eid,)).fetchone()
    assert tuple(r) == ("field", None, "—")
    con.execute("UPDATE template_elements SET x=5 WHERE id=?", (eid,)); con.commit()   # строка остаётся валидной


def test_already_v7_without_views_backfills_photo_config(tmp_path):
    """БД, уже на v7 без переноса photo_config (ранний этап 15): повторный connect дописывает вид."""
    p = tmp_path / "v6.db"; _v6(p)
    con = db.connect(str(p))
    con.execute("UPDATE persons SET photo_config='12;-7;1.3;5;9;15' WHERE id=1")
    con.execute("DELETE FROM person_photo_views")
    con.commit(); con.close()
    con = db.connect(str(p))
    assert PE.get_photo_view(con, 1)["placement"] == "12;-7;1.3;5;9;15"
    assert db.get_schema_version(con) == 7


def test_photo_editor_state_roundtrip(tmp_path):
    """set_photo_view → get_photo_editor_state отдаёт те же значения → рендер карты тот же."""
    Image.new("RGB", (200, 240), (80, 90, 100)).save(tmp_path / "a.jpg")
    con = api.connect(); api.upsert_field(con, "Фото", "Фото", data_type="image")
    eid = api.create_element(con, "photo", 10, 10, 100, 120, field_name="Фото")
    pid = api.create_person(con, {"Фото": "a.jpg"}, photo_path="a.jpg")
    params = {"brightness": 18, "contrast": -8, "scale": 110, "rotate": 5.0,
              "crop": (4, 6, 80, 90), "autoeffect": True, "portrait": True}
    saved = PE.set_photo_view(con, pid, params, field_name="Фото")
    st = api.get_photo_editor_state(con, pid, element_id=eid)
    assert st["params"] == saved
    assert st["params"]["crop"] == (4, 6, 80, 90) and st["params"]["portrait"] is True
    assert st["params"]["autoeffect"] is True
    assert st["photo_path"] == "a.jpg" and st["element_id"] == eid and st["field_name"] == "Фото"
    assert st["frame"]["element_id"] == eid and st["frame"]["size"] == (st["frame"]["width_px"], st["frame"]["height_px"])
    before = render_card_db(con, pid, "front", str(tmp_path))
    PE.set_photo_view(con, pid, st["params"], field_name=st["field_name"])
    after = render_card_db(con, pid, "front", str(tmp_path))
    assert before.tobytes() == after.tobytes()
    raw = {"brightness": 5, "contrast": 0, "scale": 100, "rotate": 0.0, "crop": None, "autoeffect": False}
    PE.set_photo_view(con, pid, raw, field_name="Фото")
    assert api.get_photo_editor_state(con, pid, eid)["params"]["portrait"] is False   # ключ добавлен

def test_flags_ignored_by_render():
    img = Image.new("RGB", (80, 80)); img.putdata([(40 + (i % 80) // 4,) * 3 for i in range(6400)])
    p = PE.autoeffect_params(img)
    assert p["autoeffect"] is True and p["portrait"] is False
    a = PE.apply_photo_edit(img, p)
    assert PE.apply_photo_edit(img, {**p, "autoeffect": False, "portrait": True}).tobytes() == a.tobytes()
    assert PE.apply_photo_edit(img, {"portrait": True, "autoeffect": True}).tobytes() == img.tobytes()
