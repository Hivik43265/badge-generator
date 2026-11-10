"""Поворот линии: концы вокруг центра рамки по часовой стрелке (новое поведение)."""
import json
import pytest
from badge_backend.render import render_card, _line_points


def _dark(img, x, y, r=3):
    px = img.convert("L").load()
    return any(px[i, j] < 128 for i in range(x - r, x + r + 1) for j in range(y - r, y + r + 1))


def test_line_points_rotation_90():
    el = {"x": 100, "y": 200, "w": 200, "h": 0}
    x0, y0, x1, y1 = _line_points(el, {"rotation": 90})
    assert (round(x0), round(y0), round(x1), round(y1)) == (200, 100, 200, 300)


def test_line_points_no_rotation():
    el = {"x": 10, "y": 20, "w": 30, "h": 40}
    assert _line_points(el, {}) == (10, 20, 40, 60)


def test_rotated_line_rendered_vertical():
    el = {"id": 1, "type": "line", "x": 228, "y": 270, "w": 400, "h": 0, "side": "front", "z_order": 0,
          "style_json": json.dumps({"rotation": 90, "border_style": "solid", "border_width": 10,
                                    "border_color": "#000000"})}
    img = render_card(None, [el], "front")
    cx, cy = 505, 319   # центр рамки в px (428, 270 ед.)
    assert _dark(img, cx, cy - 150)        # линия ушла вверх/вниз от центра
    assert _dark(img, cx, cy + 150)
    assert not _dark(img, cx - 200, cy)    # и не осталась горизонтальной
    assert not _dark(img, cx + 200, cy)
