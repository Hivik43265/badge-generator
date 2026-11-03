"""Кейсы golden PNG этапа 10 (используются tests/test_stage10.py и tests/make_golden.py)."""
import json
_b = lambda **k: json.dumps(k)
CASES = {
    "barcode_code128": ({"fields": {"emp": "EMP-000123"}},
                        [dict(id=1, type="barcode", x=100, y=150, w=800, h=250, field_name="emp", style_json=_b(format="code128"))]),
    "barcode_ean13": (None, [dict(id=1, type="barcode", x=200, y=150, w=600, h=300, static_value="5901234123457",
                                  style_json=_b(format="ean13", show_text=True))]),
    "barcode_invalid": (None, [dict(id=1, type="barcode", x=200, y=150, w=600, h=300, static_value="123",
                                    style_json=_b(format="ean13", background="#EEEEEE"))]),
    "qr_m": (None, [dict(id=1, type="qr", x=100, y=50, w=700, h=500, static_value="Иванов И.И.;000123")]),
    "qr_h_border2": ({"fields": {"id": "000777"}}, [dict(id=1, type="qr", x=300, y=100, w=400, h=400, field_name="id",
                                                       style_json=_b(error_correction="H", border=2))]),
    "line_mixed": (None, [dict(id=1, type="line", x=50, y=50, w=900, h=0, style_json=_b(stroke="#1F4E8C", stroke_width=8)),
                          dict(id=2, type="line", x=950, y=600, w=-900, h=-500, style_json=_b(stroke="#CC0000", stroke_width=3)),
                          dict(id=3, type="line", x=500, y=600, w=0, h=-550, style_json=_b(stroke_width=1))]),
    "ellipse_mixed": (None, [dict(id=1, type="ellipse", x=60, y=60, w=500, h=300, style_json=_b(fill="#1F4E8C")),
                             dict(id=2, type="ellipse", x=450, y=200, w=500, h=380,
                                  style_json=_b(fill="#FFCC0080", stroke="#CC0000", stroke_width=6)),
                             dict(id=3, type="ellipse", x=100, y=400, w=200, h=200, style_json=_b(stroke="#000000"))]),
}
