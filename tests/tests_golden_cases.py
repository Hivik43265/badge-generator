"""Кейсы golden PNG этапа 10 (используются tests/test_stage10.py и tests/make_golden.py).

Координаты x/y/w/h и stroke_width/border_width заданы в пикселях @ 300 DPI
и переводятся в единицы 0,1 мм через px_to_units — тот же пересчёт, что в
миграции v8. QR border — в модулях тихой зоны, не в единицах.
"""
import json
from badge_backend import px_to_units

_b = lambda **k: json.dumps(k)

def _el(typ, x, y, w, h, **kw):
    """Элемент с геометрией и толщиной обводки, переведёнными из px @ 300 DPI."""
    if "style_json" in kw:
        st = json.loads(kw["style_json"])
        for key in ("stroke_width", "border_width"):
            if st.get(key) is not None:
                st[key] = px_to_units(st[key])
        kw["style_json"] = json.dumps(st)
    return dict(type=typ, x=px_to_units(x), y=px_to_units(y),
                w=px_to_units(w), h=px_to_units(h), **kw)

CASES = {
    "barcode_code128": ({"fields": {"emp": "EMP-000123"}},
                        [_el("barcode", 100, 150, 800, 250, id=1, field_name="emp",
                             style_json=_b(format="code128"))]),
    "barcode_ean13": (None, [_el("barcode", 200, 150, 600, 300, id=1, static_value="5901234123457",
                                 style_json=_b(format="ean13", show_text=True))]),
    "barcode_invalid": (None, [_el("barcode", 200, 150, 600, 300, id=1, static_value="123",
                                   style_json=_b(format="ean13", background="#EEEEEE"))]),
    "qr_m": (None, [_el("qr", 100, 50, 700, 500, id=1, static_value="Иванов И.И.;000123")]),
    "qr_h_border2": ({"fields": {"id": "000777"}},
                     [_el("qr", 300, 100, 400, 400, id=1, field_name="id",
                          style_json=_b(error_correction="H", border=2))]),
    "line_mixed": (None, [_el("line", 50, 50, 900, 0, id=1,
                              style_json=_b(stroke="#1F4E8C", stroke_width=8)),
                          _el("line", 950, 600, -900, -500, id=2,
                              style_json=_b(stroke="#CC0000", stroke_width=3)),
                          _el("line", 500, 600, 0, -550, id=3,
                              style_json=_b(stroke_width=1))]),
    "ellipse_mixed": (None, [_el("ellipse", 60, 60, 500, 300, id=1,
                                 style_json=_b(fill="#1F4E8C")),
                             _el("ellipse", 450, 200, 500, 380, id=2,
                                 style_json=_b(fill="#FFCC0080", stroke="#CC0000", stroke_width=6)),
                             _el("ellipse", 100, 400, 200, 200, id=3,
                                 style_json=_b(stroke="#000000"))]),
}
