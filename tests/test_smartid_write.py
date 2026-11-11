"""Запись .csd/.csp и круговой прогон через import_smartid.

Не запускать на Linux — только Windows CI. Фикстура демо-макета:
badge_backend/assets/smartid/reference.csd (~10 МБ).
"""
import io
import sqlite3
from pathlib import Path

from PIL import Image

from badge_backend import api
from badge_backend.services import smartid
from badge_backend.services.smartid_write import SmartIdSourceProtectedError

FIXTURE = (Path(__file__).resolve().parents[1] / "badge_backend" /
           "assets" / "smartid" / "reference.csd")


def _png(w=8, h=8, color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _sample_template():
    return {
        "card_w": 856,
        "card_h": 538,
        "dpi": 300,
        "printer": "IDP SMART-51 Card Printer",
        "background_png": _png(16, 10, (240, 240, 230)),
        "fields": [
            {"name": "Name", "value": "Иванов"},
            {"name": "Photo", "value": "face.png"},
        ],
        "elements": [
            {
                "type": "text", "x": 80, "y": 24, "w": 400, "h": 50, "side": "front",
                "text": "HELLO", "font_family": "Arial", "font_size": 20,
                "color": "#C7D9FF", "align": "center",
            },
            {
                "type": "field", "x": 408, "y": 280, "w": 457, "h": 57, "side": "front",
                "field_name": "Name", "text": "Иванов", "font_family": "Arial",
                "font_size": 12, "color": "#112233", "align": "left",
            },
            {
                "type": "photo", "x": 64, "y": 152, "w": 297, "h": 385, "side": "front",
                "field_name": "Photo", "filename": "face.png",
                "png": _png(10, 12, (10, 20, 30)),
            },
            {
                "type": "image", "x": 100, "y": 30, "w": 200, "h": 60, "side": "back",
                "filename": "logo.png", "png": _png(16, 4, (200, 100, 50)),
            },
            {
                "type": "rect", "x": 656, "y": 112, "w": 185, "h": 49, "side": "front",
            },
        ],
    }


def _cmp_style(el, font=None, size=None, color=None, align=None):
    st = el.get("style") or {}
    if font is not None:
        assert st.get("font_family") == font
    if size is not None:
        assert st.get("font_size") == size
    if color is not None:
        assert st.get("color") == color
    if align is not None:
        assert st.get("align") == align


def test_write_then_import_compares_elements(tmp_path):
    tpl = _sample_template()
    dest = tmp_path / "out.csd"
    result = api.write_csd(tpl, dest)
    assert dest.is_file()
    assert dest.read_bytes()[:3] == b"CSD"
    assert isinstance(result["dropped"], list)

    con = api.connect(str(tmp_path / "p.db"))
    out = api.import_smartid(con, dest)
    assert out["template_id"]
    els = api.list_elements(con)
    by_type = {}
    for e in els:
        by_type.setdefault(e["type"], []).append(e)

    text = next(e for e in els if e["type"] == "text" and e.get("static_value") == "HELLO")
    assert (text["x"], text["y"], text["w"], text["h"], text["side"]) == (80, 24, 400, 50, "front")
    _cmp_style(text, "Arial", 20, "#C7D9FF", "center")

    field = next(e for e in els if e["type"] == "field" and e.get("field_name") == "Name")
    assert (field["x"], field["y"], field["w"], field["h"], field["side"]) == (408, 280, 457, 57, "front")
    _cmp_style(field, "Arial", 12, "#112233", "left")

    photo = next(e for e in els if e["type"] == "photo")
    assert photo["field_name"] == "Photo"
    assert (photo["x"], photo["y"], photo["w"], photo["h"], photo["side"]) == (64, 152, 297, 385, "front")

    image = next(e for e in els if e["type"] == "image")
    assert (image["x"], image["y"], image["w"], image["h"], image["side"]) == (100, 30, 200, 60, "back")

    rect = next(e for e in els if e["type"] == "rect")
    assert (rect["x"], rect["y"], rect["w"], rect["h"], rect["side"]) == (656, 112, 185, 49, "front")

    # неподдерживаемый тип попадает в dropped, а не в файл
    bad = _sample_template()
    bad["elements"] = list(bad["elements"]) + [
        {"type": "qr", "x": 1, "y": 2, "w": 30, "h": 30, "side": "front"}
    ]
    dest2 = tmp_path / "out2.csd"
    r2 = api.write_csd(bad, dest2)
    assert any(d == "QR-код 1: не поддерживается в .csd" for d in r2["dropped"])


def test_roundtrip_demo_fixture(tmp_path):
    assert FIXTURE.is_file(), f"нет фикстуры {FIXTURE}"
    parsed = smartid.parse_csd(FIXTURE)
    dest = tmp_path / "rewritten.csd"
    api.write_csd(parsed, dest)
    assert dest.stat().st_size == FIXTURE.stat().st_size
    assert dest.stat().st_size == 10421690

    con = api.connect(str(tmp_path / "p.db"))
    api.import_smartid(con, dest)
    els = api.list_elements(con)

    def key(o):
        return (o.get("type"), o.get("x"), o.get("y"), o.get("w"), o.get("h"),
                o.get("side") or "front", o.get("field_name"))

    src_objs = parsed["objects"]
    assert len(els) == len(src_objs)
    src_by = {key(o): o for o in src_objs}
    for el in els:
        src = src_by.get(key(el))
        assert src is not None, el
        st = el.get("style") or {}
        if src.get("font_family"):
            assert st.get("font_family") == src["font_family"]
        if src.get("font_size") is not None:
            assert st.get("font_size") == src["font_size"]
        if src.get("color"):
            assert st.get("color") == src["color"]
        if src.get("align"):
            assert st.get("align") == src["align"]
        if src.get("field_name"):
            assert el.get("field_name") == src["field_name"]


def test_write_csd_refuses_import_source(tmp_path):
    dest = tmp_path / "opened.csd"
    api.write_csd(_sample_template(), dest)
    try:
        api.write_csd(_sample_template(), dest)
        raise AssertionError("expected FileExistsError")
    except FileExistsError:
        pass
    try:
        api.write_csd(_sample_template(), dest, overwrite=True,
                      import_source_paths=[dest])
        raise AssertionError("expected SmartIdSourceProtectedError")
    except SmartIdSourceProtectedError:
        pass
    marked = dict(_sample_template())
    marked["source"] = str(dest)
    try:
        api.write_csd(marked, dest, overwrite=True)
        raise AssertionError("expected SmartIdSourceProtectedError")
    except SmartIdSourceProtectedError:
        pass
    api.write_csd(_sample_template(), dest, overwrite=True)


def test_write_csp_relative_and_parse(tmp_path):
    csd = tmp_path / "card.csd"
    dbp = tmp_path / "data" / "people.db"
    dbp.parent.mkdir()
    api.write_csd(_sample_template(), csd)
    con = sqlite3.connect(str(dbp))
    con.execute("CREATE TABLE persons (Name TEXT)")
    con.commit()
    con.close()
    csp = tmp_path / "proj.csp"
    info = api.write_csp(csp, csd, dbp, table_name="persons",
                         csd_fields=["Name"], tbl_fields=["Name"])
    assert info["csd_name"] == "card.csd"
    assert info["sqlite_db_path"] == "data"
    assert info["sqlite_db_name"] == "people.db"
    parsed = smartid.parse_csp(csp)
    assert Path(smartid.resolve_csp_csd(parsed)) == csd.resolve()
    assert Path(smartid.resolve_csp_db(parsed)) == dbp.resolve()
    try:
        api.write_csp(csp, csd, dbp)
        raise AssertionError("expected FileExistsError")
    except FileExistsError:
        pass


def test_bold_italic_go_to_dropped_once(tmp_path):
    tpl = {
        "elements": [
            {"type": "text", "x": 10, "y": 10, "w": 100, "h": 20, "side": "front",
             "text": "A", "style": {"bold": True}},
            {"type": "text", "x": 10, "y": 40, "w": 100, "h": 20, "side": "front",
             "text": "B", "style": {"italic": True, "font_style": "italic"}},
            {"type": "text", "x": 10, "y": 70, "w": 100, "h": 20, "side": "front",
             "text": "C", "style": {"bold": True, "font_weight": 700,
                                    "italic": True, "font_style": "oblique"}},
            {"type": "text", "x": 10, "y": 100, "w": 100, "h": 20, "side": "front",
             "text": "D", "style": {"bold": False, "italic": False}},
            {"type": "field", "x": 10, "y": 130, "w": 100, "h": 20, "side": "front",
             "field_name": "Name", "text": "Иванов", "style": {"italic": True}},
        ],
        "fields": [{"name": "Name", "value": "Иванов"}],
    }
    r = api.write_csd(tpl, tmp_path / "styles.csd")
    assert r["dropped"] == [
        "Текст 1: жирный",
        "Текст 2: курсив",
        "Текст 3: жирный",
        "Текст 3: курсив",
        "Поле 1: курсив",
    ]
