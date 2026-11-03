"""Этап 10: пустой шаблон, barcode (Code128/EAN-13), qr, line (миграция v3), рамки rect."""
import sqlite3, warnings
from pathlib import Path
import pytest
from PIL import Image, ImageChops
from badge_backend import api, db, testing
from badge_backend.render import render_card
from badge_backend.render.barcode import modules, layout, render_barcode, ean13_checksum
from badge_backend.render.qr import matrix, render_qr
from badge_backend.services import exporter
try:
    import zxingcpp
except ImportError:
    zxingcpp = None
needs_decoder = pytest.mark.skipif(zxingcpp is None, reason="zxing-cpp не установлен (requirements-dev.txt)")
GOLD = Path(__file__).parent / "golden"
WHITE = (255, 255, 255)

def runs(row):
    out, cur, n = [], row[0], 0
    for v in row:
        if v == cur: n += 1
        else: out.append((cur, n)); cur, n = v, 1
    out.append((cur, n)); return out

# ---------- пустой шаблон ----------
def test_new_db_no_elements_no_seed(tmp_path):
    c = api.connect(tmp_path / "n.db")
    assert api.list_elements(c) == [] and c.execute("SELECT count(*) FROM template_elements").fetchone()[0] == 0
    src = "".join(p.read_text(encoding="utf-8") for p in Path(api.__file__).parent.rglob("*.py")) + db.SCHEMA
    assert "create_element(con, \"rect\"" not in src and "INSERT INTO template_elements(" not in db.SCHEMA

def _empty_db():
    c = api.connect(); api.create_person(c, {"last_name": "А"}, print_mark=1); return c

def test_export_png_empty_template_warns(tmp_path):
    c = _empty_db()
    with pytest.warns(RuntimeWarning, match="шаблон пуст"):
        r = api.export_png(c, out_dir=tmp_path, allow_missing_photo=True)
    assert r.empty_template is True and r.warnings == [exporter.EMPTY_TEMPLATE_WARNING] and len(r) == 2
    assert Image.open(r[0]).size == (1011, 638)

def test_export_pdf_empty_template_warns(tmp_path):
    c = _empty_db()
    with pytest.warns(RuntimeWarning, match="шаблон пуст"):
        r = api.export_pdf(c, out_path=tmp_path / "a.pdf", allow_missing_photo=True)
    assert r.empty_template and r.exists()

def test_export_one_empty_side_partial_warning(tmp_path):
    c = _empty_db(); api.create_element(c, "rect", 0, 0, 10, 10, style={"fill": "#000"})
    with pytest.warns(RuntimeWarning, match="сторона 'back'"):
        r = api.export_png(c, out_dir=tmp_path, allow_missing_photo=True)
    assert r.empty_template is False and r.warnings == ["сторона 'back' шаблона пуста"]

def test_export_nonempty_no_warnings(tmp_path):
    c = _empty_db(); api.create_element(c, "rect", 0, 0, 10, 10, style={"fill": "#000"})
    r = api.export_png(c, out_dir=tmp_path, sides="front", allow_missing_photo=True)
    assert r.empty_template is False and r.warnings == []

def test_print_empty_template_warns(tmp_path):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtPrintSupport import QPrinter
    app = QApplication.instance() or QApplication([])
    c = _empty_db(); pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(str(tmp_path / "p.pdf"))
    with pytest.warns(RuntimeWarning, match="шаблон пуст"):
        r = api.print_cards(c, pr, allow_missing_photo=True)
    assert r == 2 and r.empty_template is True and r.warnings

# ---------- barcode ----------
def test_ean13_validation():
    assert modules("ean13", "590123412345")[1] == "5901234123457"
    assert modules("ean13", "5901234123457")[1] == "5901234123457"
    assert len(modules("ean13", "5901234123457")[0]) == 95
    assert ean13_checksum("400638133393") == 1

@pytest.mark.parametrize("val", ["", None, "12345", "59012341234578", "5901234123458", "abcdefghijkl"])
def test_ean13_invalid_empty_frame(val):
    with pytest.warns(RuntimeWarning, match="не отрисован"):
        t = render_barcode(400, 150, val, {"format": "ean13"})
    assert t.getcolors(1) is not None   # однотонная (пустая) рамка

def test_code128_invalid_and_too_narrow():
    with pytest.warns(RuntimeWarning): assert render_barcode(300, 100, "", {}).getcolors(1)
    with pytest.warns(RuntimeWarning): assert render_barcode(300, 100, "Привет", {}).getcolors(1)
    with pytest.warns(RuntimeWarning, match="не помещаются"):
        assert render_barcode(50, 100, "ABCDEFGHIJ", {}).getcolors(1)

@pytest.mark.parametrize("fmt,val,w", [("code128", "EMP-000123", 700), ("code128", "A1", 333),
                                       ("ean13", "5901234123457", 500), ("ean13", "400638133393", 211)])
def test_integer_module_width_and_centering(fmt, val, w):
    code, _ = modules(fmt, val); q = 10
    m, x0 = layout(len(code), w, q)
    assert m == w // (len(code) + 2 * q) and m >= 1
    t = render_barcode(w, 120, val, {"format": fmt, "show_text": False, "quiet_zone": q}).convert("L")
    row = [t.getpixel((x, 60)) for x in range(w)]
    assert set(row) <= {0, 255}
    r = runs(row)
    lead, trail = r[0][1], r[-1][1]
    assert r[0][0] == 255 and r[-1][0] == 255 and abs(lead - trail) <= 1 + 0   # центрирование
    assert lead >= q * m
    inner = r[1:-1]
    assert all(n % m == 0 for _, n in inner)
    expect = runs([int(c) for c in code])
    assert [n // m for _, n in inner] == [n for _, n in expect]
    # максимум: m+1 уже не влезает
    assert (m + 1) * (len(code) + 2 * q) > w

def test_show_text_reserves_area():
    a = render_barcode(600, 200, "ABC", {"show_text": True}).convert("L")
    b = render_barcode(600, 200, "ABC", {"show_text": False}).convert("L")
    col = [x for x in range(600) if a.getpixel((x, 0)) == 0][0]
    assert b.getpixel((col, 199)) == 0 and a.getpixel((col, 199)) == 255   # внизу у a подпись, а не полоса
    assert ImageChops.difference(a, b).getbbox() is not None

def test_barcode_value_from_field_and_static():
    p = {"fields": {"emp": "590123412345"}}
    e1 = [dict(id=1, type="barcode", x=100, y=100, w=500, h=200, field_name="emp", style_json='{"format":"ean13"}')]
    e2 = [dict(id=1, type="barcode", x=100, y=100, w=500, h=200, static_value="5901234123457",
               style_json='{"format":"ean13"}')]
    a, b = render_card(p, e1), render_card(None, e2)
    assert a.tobytes() == b.tobytes() and a.tobytes() != render_card(None, []).tobytes()

@needs_decoder
@pytest.mark.parametrize("fmt,val", [("code128", "EMP-000123"), ("ean13", "5901234123457")])
def test_barcode_decodes(fmt, val):
    t = render_barcode(700, 200, val, {"format": fmt}).convert("RGB")
    res = zxingcpp.read_barcodes(t)
    assert [r.text for r in res] == [val]

# ---------- qr ----------
def test_qr_square_integer_modules_center():
    for w, h in ((300, 200), (200, 333), (257, 257)):
        mtx = matrix("ID:000123"); n = len(mtx) + 8; m = min(w, h) // n
        t = render_qr(w, h, "ID:000123", {}).convert("RGBA")
        bb = t.getchannel("A").getbbox()
        assert bb[2] - bb[0] == bb[3] - bb[1] == m * n
        assert bb[0] == (w - m * n) // 2 and bb[1] == (h - m * n) // 2
        # модуль (0,0) — угол finder-паттерна: тёмный квадрат m×m
        x0, y0 = bb[0] + 4 * m, bb[1] + 4 * m
        assert t.getpixel((x0, y0))[:3] == (0, 0, 0) and t.getpixel((x0 + m * 7, y0))[:3] == WHITE

def test_qr_ec_levels_and_invalid():
    assert len(matrix("x" * 50, "H")) > len(matrix("x" * 50, "L"))
    with pytest.warns(RuntimeWarning, match="пустое"): assert render_qr(200, 200, "", {}).getcolors(1)
    with pytest.warns(RuntimeWarning, match="не помещаются"): render_qr(200, 200, "x" * 5000, {})
    with pytest.warns(RuntimeWarning, match="не помещаются"): render_qr(20, 20, "hello", {})
    with pytest.warns(RuntimeWarning, match="error_correction"): render_qr(200, 200, "a", {"error_correction": "Z"})

def test_qr_value_from_field_and_static():
    e1 = [dict(id=1, type="qr", x=10, y=10, w=300, h=300, field_name="emp")]
    e2 = [dict(id=1, type="qr", x=10, y=10, w=300, h=300, static_value="000777")]
    assert render_card({"fields": {"emp": "000777"}}, e1).tobytes() == render_card(None, e2).tobytes()

@needs_decoder
@pytest.mark.parametrize("ec", "LMQH")
def test_qr_decodes(ec):
    t = render_qr(400, 400, "Иванов И.И.;000123", {"error_correction": ec}).convert("RGB")
    assert [r.text for r in zxingcpp.read_barcodes(t)] == ["Иванов И.И.;000123"]

# ---------- line + миграция v3 ----------
def test_line_negative_and_zero_extent():
    c = api.connect()
    a = api.create_element(c, "line", 500, 300, -200, 0, style={"stroke": "#FF0000", "stroke_width": 4})
    b = api.create_element(c, "line", 100, 600, 0, -500, style={"stroke": "#0000FF"})
    with pytest.raises(sqlite3.IntegrityError): api.create_element(c, "line", 1, 1, 0, 0)
    with pytest.raises(sqlite3.IntegrityError): api.create_element(c, "rect", 1, 1, -5, 5)
    im = api.render_card_db(c, None)
    assert im.getpixel((400, 300)) == (255, 0, 0) and im.getpixel((100, 300)) == (0, 0, 255)
    assert im.getpixel((600, 300)) == WHITE

def test_line_diagonal():
    im = render_card(None, [dict(type="line", x=0, y=0, w=100, h=100, style_json='{"stroke_width":1}')])
    assert im.getpixel((50, 50)) == (0, 0, 0) and im.getpixel((50, 10)) == WHITE

def test_migration_v2_to_v3_with_data(tmp_path):
    p = testing.create_legacy_db(tmp_path / "v2.db", version=2)
    raw = sqlite3.connect(p)
    raw.execute("INSERT INTO template_elements(id,type,x,y,w,h,field_name,style_json,side,z_order) "
                "VALUES (7,'field',1,2,3,4,'fio','{\"a\":1}','back',5)")
    raw.execute("INSERT INTO template_elements(id,type,x,y,w,h,static_value) VALUES (42,'barcode',0,0,10,10,'X')")
    raw.commit()
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("INSERT INTO template_elements(type,x,y,w,h) VALUES ('line',0,0,5,5)")
    before = raw.execute("SELECT * FROM template_elements ORDER BY id").fetchall(); raw.close()
    c = api.connect(p)
    assert api.get_schema_version(c) == 4  # v3→…→LATEST
    assert [tuple(r) for r in c.execute("SELECT * FROM template_elements ORDER BY id")] == before
    idx = {r[1] for r in c.execute("PRAGMA index_list(template_elements)")}
    assert "idx_te_side_z" in idx
    assert c.execute("SELECT count(*) FROM sqlite_master WHERE name='_te_old'").fetchone()[0] == 0
    assert api.create_element(c, "line", 0, 0, 5, -5) > 42      # новые id после старых
    # повтор: version откатили — шаг идемпотентен, данные на месте
    c.execute("PRAGMA user_version=2"); assert db.migrate(c) == db.LATEST and db.migrate(c) == db.LATEST
    assert c.execute("SELECT count(*) FROM template_elements").fetchone()[0] == 3

def test_legacy_v2_helper(tmp_path):
    p = testing.create_legacy_db(tmp_path / "x.db", version=2)
    r = sqlite3.connect(p); assert r.execute("PRAGMA user_version").fetchone()[0] == 2
    assert "printed_at" in db._cols(r, "persons")

# ---------- рамки rect ----------
def test_rect_all_four_keys():
    st = '{"stroke":"#FF0000","stroke_width":6,"fill":"#00FF00","radius":40}'
    im = render_card(None, [dict(type="rect", x=100, y=100, w=400, h=300, style_json=st)])
    assert im.getpixel((300, 102)) == (255, 0, 0)          # stroke сверху
    assert im.getpixel((300, 250)) == (0, 255, 0)          # fill внутри
    assert im.getpixel((101, 101)) == WHITE                # скруглённый угол
    sq = render_card(None, [dict(type="rect", x=100, y=100, w=400, h=300, style_json=st.replace('"radius":40', '"radius":0'))])
    assert sq.getpixel((101, 101)) == (255, 0, 0)

def test_rect_stroke_only_and_legacy_keys():
    a = render_card(None, [dict(type="rect", x=10, y=10, w=100, h=100, style_json='{"stroke":"#000","stroke_width":3}')])
    b = render_card(None, [dict(type="rect", x=10, y=10, w=100, h=100, style_json='{"border_color":"#000","border_width":3}')])
    assert a.tobytes() == b.tobytes() and a.getpixel((60, 60)) == WHITE and a.getpixel((60, 11)) == (0, 0, 0)
    one = render_card(None, [dict(type="rect", x=10, y=10, w=100, h=100, style_json='{"stroke":"#000"}')])
    assert one.getpixel((60, 10)) == (0, 0, 0) and one.getpixel((60, 11)) == WHITE

# ---------- golden ----------
from tests_golden_cases import CASES  # noqa: E402

@pytest.mark.parametrize("name", sorted(CASES))
def test_stage10_golden(name):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        im = render_card(*CASES[name])
    ref = Image.open(GOLD / f"{name}.png").convert("RGB")
    assert ImageChops.difference(im, ref).getbbox() is None

def test_symbology_alias():
    a = render_barcode(500, 150, "5901234123457", {"format": "ean13"})
    assert a.tobytes() == render_barcode(500, 150, "5901234123457", {"symbology": "ean13"}).tobytes()
