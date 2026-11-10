"""Фон штрихкода/QR из bg_fill/bg_color панели свойств (§9) приоритетнее background/fill."""
from badge_backend.render import _code_bg


def test_code_bg_from_props_panel():
    assert _code_bg({"bg_fill": False, "background": "#FF0000"}) is None          # прозрачно
    assert _code_bg({"bg_fill": True, "bg_color": "#00FF00", "background": "#FF0000"}) == (0, 255, 0, 255)
    assert _code_bg({"bg_fill": True}) == (255, 255, 255, 255)
    assert _code_bg({"background": "#FF0000"}) == (255, 0, 0, 255)                # как раньше
    assert _code_bg({}) == (255, 255, 255, 255)
    assert _code_bg({"background": None}) is None
