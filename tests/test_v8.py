"""Схема v8: геометрия в 0,1 мм, свойства rotation/lock/border/fill, .bgt v2."""
import json
import sqlite3
import zipfile

import pytest
from PIL import Image

from badge_backend import (
    api, db, CARD_W_PX, CARD_H_PX, CARD_W_UNITS, CARD_H_UNITS,
    units_to_px, px_to_units, units_to_mm, mm_to_units, px_to_mm,
)
from badge_backend.testing import create_legacy_db


def test_unit_invariants():
    assert px_to_units(1011) == 856 == CARD_W_UNITS
    assert px_to_units(638) == 540 == CARD_H_UNITS
    assert units_to_px(856) == 1011 == CARD_W_PX
    assert units_to_px(540) == 638 == CARD_H_PX
    assert units_to_mm(856) == 85.6
    assert units_to_mm(540) == 54.0
    assert mm_to_units(85.6) == 856
    assert round(px_to_mm(1011), 2) == 85.6


def test_migration_v7_to_v8_and_idempotent(tmp_path):
    p = create_legacy_db(tmp_path / "v7.db", 7)
    raw = sqlite3.connect(p)
    raw.execute(
        "INSERT INTO template_elements(type,x,y,w,h,style_json,side,z_order,template_id) "
        "VALUES ('rect',0,0,1011,638,'{\"padding\":30,\"radius\":16,\"stroke_width\":1}','front',0,1)"
    )
    raw.execute(
        "INSERT INTO template_elements(type,x,y,w,h,style_json,side,z_order,template_id) "
        "VALUES ('line',10,20,-300,120,'{}','front',1,1)"
    )
    raw.commit(); raw.close()
    con = api.connect(p)
    assert db.get_schema_version(con) == 8 == db.LATEST
    els = {e["type"]: e for e in api.list_elements(con)}
    r = els["rect"]
    assert (r["x"], r["y"], r["w"], r["h"]) == (0, 0, 856, 540)
    assert r["style"]["padding"] == px_to_units(30)
    assert r["style"]["radius"] == px_to_units(16)
    assert r["style"]["border_width"] == px_to_units(1)
    assert r["style"]["border_style"] == "solid"
    ln = els["line"]
    assert (ln["x"], ln["y"], ln["w"], ln["h"]) == (px_to_units(10), px_to_units(20), px_to_units(-300), px_to_units(120))
    before = [(e["x"], e["y"], e["w"], e["h"], e["style"]) for e in api.list_elements(con)]
    assert db.migrate(con) == 8
    after = [(e["x"], e["y"], e["w"], e["h"], e["style"]) for e in api.list_elements(con)]
    assert after == before


def test_full_card_still_renders_1011x638(tmp_path):
    p = create_legacy_db(tmp_path / "card.db", 7)
    raw = sqlite3.connect(p)
    raw.execute(
        "INSERT INTO template_elements(type,x,y,w,h,style_json,side,z_order,template_id) "
        "VALUES ('rect',0,0,1011,638,'{\"fill\":\"#112233\"}','front',0,1)"
    )
    raw.commit(); raw.close()
    con = api.connect(p)
    im = api.render_card_db(con, None, "front")
    assert im.size == (1011, 638) == (CARD_W_PX, CARD_H_PX)
    assert im.getpixel((5, 5)) == (0x11, 0x22, 0x33)


def test_bgt_v2_export_and_v1_import(tmp_path):
    con = api.connect(tmp_path / "a.db")
    api.create_element(con, "text", 34, 102, 200, 40, static_value="Hi",
                       style={"padding": 8, "font_size": 14})
    dest = tmp_path / "t.bgt"
    api.export_template(con, dest)
    with zipfile.ZipFile(dest) as zf:
        data = json.loads(zf.read("template.json"))
    assert data["format_version"] == 2 and data["schema_min"] == 8 and data["units"] == "0.1mm"
    assert data["elements"][0]["x"] == 34

    payload = {
        "format": "badge-generator-template", "format_version": 1,
        "template": {"name": "Old", "style": {"padding": 30}},
        "elements": [{"type": "text", "x": 40, "y": 120, "w": 236, "h": 80,
                      "static_value": "V1", "style": {"padding": 30, "stroke_width": 1}, "side": "front"}],
        "backgrounds": [],
    }
    old = tmp_path / "old.bgt"
    with zipfile.ZipFile(old, "w") as zf:
        zf.writestr("template.json", json.dumps(payload))
    dst = api.connect(tmp_path / "b.db")
    api.import_template(dst, old)
    el = api.list_elements(dst)[0]
    assert (el["x"], el["y"], el["w"], el["h"]) == (
        px_to_units(40), px_to_units(120), px_to_units(236), px_to_units(80))
    assert el["style"]["padding"] == px_to_units(30)
    assert el["style"]["border_width"] == px_to_units(1)
    assert el["style"]["border_style"] == "solid"

    bad = tmp_path / "v3.bgt"
    payload["format_version"] = 3
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("template.json", json.dumps(payload))
    with pytest.raises(ValueError, match="верси"):
        api.import_template(dst, bad)


def test_locked_blocks_move_and_delete():
    con = api.connect()
    eid = api.create_element(con, "text", 10, 10, 80, 20, static_value="L", style={"locked": True})
    with pytest.raises(ValueError, match="зафиксирован"):
        api.update_element(con, eid, x=50)
    with pytest.raises(ValueError, match="зафиксирован"):
        api.update_element_style(con, eid, rotation=15)
    with pytest.raises(ValueError, match="зафиксирован"):
        api.delete_element(con, eid)
    api.update_element_style(con, eid, locked=False)
    assert api.update_element(con, eid, x=50)
    assert api.list_elements(con)[0]["x"] == 50


def test_rotation_and_fill_and_border_render():
    con = api.connect()
    api.create_element(con, "rect", 100, 100, 200, 80, style={
        "bg_fill": True, "bg_color": "#FF0000",
        "border_style": "solid", "border_width": 10, "border_color": "#0000FF",
        "rotation": 0,
    })
    im = api.render_card_db(con, None)
    assert im.size == (1011, 638)
    # центр прямоугольника залит красным
    cx, cy = units_to_px(200), units_to_px(140)
    assert im.getpixel((cx, cy))[:3] == (255, 0, 0)
    # без заливки цвет не рисуется
    con2 = api.connect()
    api.create_element(con2, "rect", 100, 100, 200, 80, style={
        "bg_fill": False, "bg_color": "#FF0000",
    })
    im2 = api.render_card_db(con2, None)
    assert im2.getpixel((cx, cy)) == (255, 255, 255)
    # поворот 90: рамка меняет ориентацию, x,y,w,h в БД те же
    con3 = api.connect()
    eid = api.create_element(con3, "rect", 200, 150, 200, 40, style={
        "bg_fill": True, "bg_color": "#00AA00", "rotation": 90,
    })
    el = api.list_elements(con3)[0]
    assert (el["x"], el["y"], el["w"], el["h"]) == (200, 150, 200, 40)
    im3 = api.render_card_db(con3, None)
    assert im3.size == (1011, 638)
    assert im3.getpixel((units_to_px(200 + 100), units_to_px(150 + 20)))[:3] != (255, 255, 255)


def test_failed_migration_leaves_file_untouched(tmp_path, monkeypatch):
    p = create_legacy_db(tmp_path / "keep.db", 7)
    raw = sqlite3.connect(p)
    raw.execute(
        "INSERT INTO template_elements(type,x,y,w,h,style_json,side,z_order,template_id) "
        "VALUES ('text',40,50,100,20,'{}','front',0,1)"
    )
    raw.commit(); raw.close()
    before = open(p, "rb").read()

    def boom(con):
        raise RuntimeError("искусственный сбой")

    migrations = list(db.MIGRATIONS)
    migrations[db.MIGRATIONS.index(db._v8_units)] = boom
    monkeypatch.setattr(db, "MIGRATIONS", migrations)
    with pytest.raises(db.MigrationError, match="верси"):
        api.connect(p)
    after = sqlite3.connect(p)
    assert after.execute("PRAGMA user_version").fetchone()[0] == 7
    r = after.execute("SELECT x,y,w,h FROM template_elements").fetchone()
    assert tuple(r) == (40, 50, 100, 20)
    after.close()
    # файл на диске остался схемой v7
    assert sqlite3.connect(p).execute("PRAGMA user_version").fetchone()[0] == 7


def test_photo_frame_spec_from_units():
    con = api.connect()
    api.upsert_field(con, "Фото", "Фото", data_type="image")
    eid = api.create_element(con, "photo", 10, 10, 200, 250, field_name="Фото")
    spec = api.get_photo_frame_spec(con, element_id=eid)
    assert spec["width_mm"] == 20 and spec["height_mm"] == 25
    assert spec["width_px"] == units_to_px(200) and spec["height_px"] == units_to_px(250)
    assert spec["aspect"] == pytest.approx(0.8)


def test_default_link_geometry_photo_20x25_mm():
    con = api.connect()
    api.upsert_field(con, "Фото", "Фото", data_type="image")
    eid = api.link_field(con, None, "Фото")
    el = next(e for e in api.list_elements(con) if e["id"] == eid)
    assert (el["w"], el["h"]) == (200, 250)
    assert units_to_mm(el["w"]) == 20 and units_to_mm(el["h"]) == 25
