"""Импорт Smart IDesigner (.csd / .csp). Синтетические фикстуры: образец IDP ~10 МБ в tests/ не кладём."""
import io
import sqlite3
import struct
from pathlib import Path

from PIL import Image

from badge_backend import api
from badge_backend.services import smartid


def _i32(n):
    return struct.pack("<i", n)


def _u16(n):
    return struct.pack("<H", n)


def _tiny_png(w=8, h=8, color=(20, 40, 80, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _header(w=856, h=538, dpi=300, printer="IDP SMART-51 Card Printer"):
    buf = bytearray()
    buf += b"CSD\x00\x0d\x00\x00\x00\x00"
    buf += b"VER\x00\x10\x00\x00\x00\x01\x00\x1b\x00"
    buf += b"PRN\x00\x00\x00\x00" + printer.encode("utf-16le") + b"\x00\x00"
    buf += b"\x00" * max(0, 100 - len(buf))
    buf += bytes.fromhex("ff 80 05 02 00 96 00")
    buf += _u16(w) + _u16(h)
    buf += _u16(100) + _u16(1) + _u16(15) + _u16(dpi)
    buf += b"\x00" * 32
    return bytes(buf)


def _et(x, y, w, h, text, font="Arial", size=10, align=1, color=(0xC7, 0xD9, 0xFF),
        flags=0x01000000, rotation=0):
    rec = bytearray(0xDD)
    rec[0:8] = bytes.fromhex("01 80 05 00 00 00") + b"ET"
    rec[8:28] = _i32(flags) + _i32(x) + _i32(y) + _i32(w) + _i32(h)
    rec[28:32] = _i32(rotation)
    rec[0x2C:0x30] = bytes(color) + b"\x00"
    rec[0x8A:0x8C] = _u16(0x10 | (align & 3))
    rec[0x90:0x94] = _i32(size)
    face = font.encode("utf-16le")
    rec[0x98:0x98 + len(face)] = face
    rec += _i32(len(text)) + text.encode("utf-16le")
    return bytes(rec)


def _mi(x, y, w, h, png=None, filename="pic.png", flags=0x01000000):
    rec = bytearray(220)
    rec[0:8] = bytes.fromhex("01 80 04 00 00 00") + b"MI"
    rec[8:28] = _i32(flags) + _i32(x) + _i32(y) + _i32(w) + _i32(h)
    if filename:
        rec += _i32(len(filename)) + filename.encode("utf-16le")
    if png:
        rec += png
    return bytes(rec)


def _er(x, y, w, h):
    rec = bytearray(80)
    rec[0:8] = bytes.fromhex("01 80 00 00 00 00") + b"ER"
    rec[8:28] = _i32(0x01000000) + _i32(x) + _i32(y) + _i32(w) + _i32(h)
    return bytes(rec)


def _zz(x, y, w, h):
    rec = bytearray(40)
    rec[0:8] = bytes.fromhex("01 80 07 00 00 00") + b"ZZ"
    rec[8:28] = _i32(0) + _i32(x) + _i32(y) + _i32(w) + _i32(h)
    return bytes(rec)


def _fields_table(pairs):
    out = bytearray()
    out += _u16(len(pairs)) + b"\xff\xff\x00\x00\x05\x00"
    for i, (name, value) in enumerate(pairs):
        rec = bytearray(smartid.FIELD_REC_SIZE)
        if i == 0:
            rec[0:5] = b"CGFld"
        else:
            rec[3] = 0x0E
            rec[4] = 0x80
            rec[5] = i
        nb = name.encode("utf-16le")[:62]
        rec[9:9 + len(nb)] = nb
        vb = value.encode("utf-16le")
        rec[73:77] = _i32(len(value))
        rec[77:77 + len(vb)] = vb
        out += rec
    return bytes(out)


def _build_csd(*, title="LICENSE TO FIREARMS", veteran="VETERAN", name="Adward,Jenner",
               photo_name="face.png", include_er=True, include_unknown=True,
               photo_png=None, extra_image_png=None):
    photo_png = photo_png or _tiny_png(10, 12, (10, 20, 30, 255))
    extra_image_png = extra_image_png or _tiny_png(16, 4, (200, 100, 50, 255))
    parts = [_header(), _tiny_png(32, 20, (240, 240, 230, 255))]  # фон до объектов
    parts.append(_mi(64, 152, 297, 385, png=photo_png, filename=photo_name))
    parts.append(_et(80, 24, 817, 105, title, size=20))
    if include_er:
        parts.append(_er(656, 112, 185, 49))
    parts.append(_et(664, 120, 169, 41, veteran, size=10))
    parts.append(_et(408, 280, 457, 57, name, size=10))
    parts.append(_mi(456, 568, 513, 68, png=extra_image_png, filename="logo.png"))
    if include_unknown:
        parts.append(_zz(10, 10, 20, 20))
    parts.append(_fields_table([
        ("Cardtype", title),
        ("Photo", rf"C:\Users\demo\{photo_name}"),
        ("Name", name),
    ]))
    return b"".join(parts)


def test_to_storage_units_isolated():
    assert smartid._to_storage_units(856) == 856
    assert smartid._to_storage_units(538) == 538
    assert smartid._to_storage_units(540) == 540
    assert smartid._to_storage_units(664) == 664
    assert smartid._to_storage_units(120) == 120
    assert smartid._to_storage_units(169) == 169
    assert smartid._to_storage_units(41) == 41


def test_parse_csd_card_size_and_known_et():
    parsed = smartid.parse_csd(_build_csd())
    assert parsed["card_w"] == 856
    assert parsed["card_h"] == 538
    assert parsed["printer"] == "IDP SMART-51 Card Printer"
    ets = [o for o in parsed["objects"] if o["tag"] == "ET"]
    mis = [o for o in parsed["objects"] if o["tag"] == "MI"]
    assert len(ets) == 3
    assert len(mis) == 2
    vet = next(o for o in ets if o["text"] == "VETERAN")
    assert (vet["x"], vet["y"], vet["w"], vet["h"]) == (664, 120, 169, 41)
    assert smartid._to_storage_units(vet["x"]) == 664


def test_type_mapping_field_text_photo_image():
    parsed = smartid.parse_csd(_build_csd())
    by_text = {o.get("text"): o for o in parsed["objects"] if o["tag"] == "ET"}
    assert by_text["VETERAN"]["type"] == "text"
    assert by_text["VETERAN"]["field_name"] is None
    assert by_text["Adward,Jenner"]["type"] == "field"
    assert by_text["Adward,Jenner"]["field_name"] == "Name"
    assert by_text["LICENSE TO FIREARMS"]["type"] == "field"
    assert by_text["LICENSE TO FIREARMS"]["field_name"] == "Cardtype"
    photos = [o for o in parsed["objects"] if o["type"] == "photo"]
    images = [o for o in parsed["objects"] if o["type"] == "image"]
    assert len(photos) == 1
    assert photos[0]["field_name"] == "Photo"
    assert photos[0]["x"] == 64 and photos[0]["y"] == 152
    assert len(images) == 1
    assert images[0]["filename"] == "logo.png"
    # y=568 >= 538 → оборот, y' = 30 (догадка, фиксируем текущее правило)
    assert images[0]["side"] == "back"
    assert images[0]["y"] == 30
    rects = [o for o in parsed["objects"] if o["type"] == "rect"]
    assert len(rects) == 1
    assert rects[0]["tag"] == "ER"
    assert (rects[0]["x"], rects[0]["y"], rects[0]["w"], rects[0]["h"]) == (656, 112, 185, 49)


def test_unknown_record_skipped_not_crash():
    parsed = smartid.parse_csd(_build_csd())
    tags = {s.get("tag") for s in parsed["skipped"]}
    assert "ZZ" in tags
    assert "ER" not in tags
    assert {o["tag"] for o in parsed["objects"]} <= {"ET", "MI", "ER"}


def test_import_csd_replaces_active_template(tmp_path):
    src = tmp_path / "license.csd"
    src.write_bytes(_build_csd())
    con = api.connect(str(tmp_path / "p.db"))
    before = api.active_template_id(con)
    out = api.import_smartid(con, src)
    assert out["template_id"] == before
    assert out["persons_imported"] == 0
    els = api.list_elements(con)
    types = {e["type"] for e in els}
    assert "field" in types and "text" in types and "photo" in types and "image" in types
    assert "rect" in types
    rect = next(e for e in els if e["type"] == "rect")
    assert rect["style"].get("border_style") == "solid"
    assert rect["style"].get("bg_fill") is False
    assert "Cardtype" in (out["report"].get("created_fields") or [])
    assert "Photo" in out["report"]["created_fields"]
    vet = next(e for e in els if e.get("static_value") == "VETERAN")
    assert (vet["x"], vet["y"], vet["w"], vet["h"]) == (664, 120, 169, 41)
    name_el = next(e for e in els if e.get("field_name") == "Name")
    assert name_el["type"] == "field"
    photo = next(e for e in els if e["type"] == "photo")
    assert photo["field_name"] == "Photo"
    skipped_tags = {s.get("tag") for s in out["report"]["skipped"]}
    assert "ZZ" in skipped_tags and "ER" not in skipped_tags
    bg = api.get_background(con, "front")
    assert bg and bg.get("image_path")


def test_import_csp_maps_fields_and_persons(tmp_path):
    photo = tmp_path / "face.jpg"
    Image.new("RGB", (12, 12), (8, 9, 10)).save(photo, format="JPEG")
    csd = tmp_path / "card.csd"
    csd.write_bytes(_build_csd(photo_name="face.png"))
    dbp = tmp_path / "people.db"
    src = sqlite3.connect(str(dbp))
    src.execute("CREATE TABLE Employees (fio TEXT, pic TEXT, extra TEXT)")
    src.execute("INSERT INTO Employees VALUES (?,?,?)", ("Иванов", str(photo), "skip-me"))
    src.commit()
    src.close()
    csp = tmp_path / "proj.csp"
    csp.write_text(
        "\n".join([
            "[DB]",
            f"CSD_Name=card.csd",
            f"SQLiteDBPath={tmp_path}",
            "SQLiteDBName=people.db",
            "TableName=Employees",
            "[BIND]",
            "CSD_Fields=Name|Photo",
            "TBL_Fields=fio|pic",
        ]),
        encoding="utf-8",
    )
    con = api.connect(str(tmp_path / "project.db"))
    api.upsert_field(con, "Name", "Name", 0)
    api.create_person(con, {"Name": "Существующий"})
    out = api.import_smartid(con, csp)
    assert out["persons_imported"] == 1
    persons = api.list_persons(con)
    assert len(persons) == 2  # записи из .csp добавляются, не заменяют
    names = {p["fields"].get("Name") for p in persons}
    assert names == {"Существующий", "Иванов"}
    ivan = next(p for p in persons if p["fields"].get("Name") == "Иванов")
    # колонка extra без маппинга не создаёт поле
    assert "extra" not in persons[0]["fields"]
    photo_val = ivan["fields"].get("Photo") or ivan.get("photo_path")
    assert photo_val  # путь сохранён существующим импортом

def test_cyrillic_fields_and_photo_alias():
    assert smartid._is_photo_field("ФОТО")
    assert smartid._is_photo_field("фото")
    assert smartid._is_photo_field("Фото")
    raw = (
        _header()
        + _et(40, 50, 200, 40, "Иванов", rotation=15)
        + _mi(10, 10, 80, 100, png=_tiny_png(), filename="лицо.png")
        + _fields_table([
            ("Фамилия", "Иванов"),
            ("ФОТО", "C:\\фото\\лицо.png"),
        ])
    )
    parsed = smartid.parse_csd(raw)
    names = [f["name"] for f in parsed["fields"]]
    assert names == ["Фамилия", "ФОТО"]
    assert parsed["fields"][0]["value"] == "Иванов"
    fam = next(o for o in parsed["objects"] if o.get("text") == "Иванов")
    assert fam["field_name"] == "Фамилия" and fam["type"] == "field"
    assert fam["rotation"] == 15
    photo = next(o for o in parsed["objects"] if o["tag"] == "MI")
    assert photo["type"] == "photo" and photo["field_name"] == "ФОТО"


def test_cyrillic_import_creates_fields(tmp_path):
    src = tmp_path / "ru.csd"
    src.write_bytes(
        _header()
        + _et(40, 50, 200, 40, "Петров")
        + _fields_table([("Фамилия", "Петров"), ("ФОТО", "x.png")])
    )
    con = api.connect(str(tmp_path / "p.db"))
    out = api.import_smartid(con, src)
    created = out["report"]["created_fields"]
    assert "Фамилия" in created and "ФОТО" in created
    types = {r["name"]: r["data_type"] for r in api.list_fields(con)}
    assert types["Фамилия"] == "text" and types["ФОТО"] == "image"
    el = next(e for e in api.list_elements(con) if e.get("field_name") == "Фамилия")
    assert el["type"] == "field"
