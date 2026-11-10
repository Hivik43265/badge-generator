"""Каталог системных шрифтов и запасной TTF вместо bitmap Pillow."""
from __future__ import annotations

import logging
import os
import sys

from PIL import Image, ImageDraw, ImageFont

from badge_backend.render import _fit_text
from badge_backend.render.fonts import (
    FALLBACK_FAMILIES,
    _font_dirs,
    fallback_family,
    get_font,
    list_font_families,
    list_fonts,
)


def test_list_fonts_nonempty_includes_fallback():
    names = list_fonts()
    assert names, "сканер должен найти хотя бы один TTF/OTF"
    fb = fallback_family()
    assert fb is not None
    assert fb in names
    assert any(fb.casefold().startswith(w.casefold()) or w.casefold().startswith(fb.split()[0].casefold())
               for w in FALLBACK_FAMILIES) or fb in names
    assert list_font_families() == names
    assert names == sorted(names, key=lambda s: s.casefold())


def test_unknown_family_uses_truetype_not_default(caplog):
    with caplog.at_level(logging.WARNING, logger="badge_backend.render.fonts"):
        font = get_font(40, family="NoSuchFontFamily_xyz_123")
    assert isinstance(font, ImageFont.FreeTypeFont)
    assert not isinstance(font, ImageFont.ImageFont) or isinstance(font, ImageFont.FreeTypeFont)
    assert any("не найден" in rec.getMessage() for rec in caplog.records)


def test_larger_pt_gives_larger_bbox_when_text_fits():
    """Автоподгонка не срабатывает в большом кадре — кегль применяется как есть."""
    draw = ImageDraw.Draw(Image.new("RGB", (16, 16)))
    f12, _l, _y, _w, bb12, notes12 = _fit_text(
        draw, "Ag", 2000, 2000, 12 * 300 / 72, 8 * 300 / 72, None, False, None, False, 1.0)
    f36, _l, _y, _w, bb36, notes36 = _fit_text(
        draw, "Ag", 2000, 2000, 36 * 300 / 72, 8 * 300 / 72, None, False, None, False, 1.0)
    assert notes12 == []
    assert notes36 == []
    assert isinstance(f12, ImageFont.FreeTypeFont)
    assert isinstance(f36, ImageFont.FreeTypeFont)
    h12 = bb12[3] - bb12[1]
    h36 = bb36[3] - bb36[1]
    assert h36 > h12


def test_larger_pt_gives_larger_glyphs_when_overflowing():
    """В маленькой рамке больший pt всё равно даёт больший глиф (автоподбор выключен)."""
    draw = ImageDraw.Draw(Image.new("RGB", (16, 16)))
    f18, _l, _y, _w, bb18, n18 = _fit_text(
        draw, "Ag", 40, 20, 18 * 300 / 72, 8 * 300 / 72, None, False, None, False, 1.0)
    f48, _l, _y, _w, bb48, n48 = _fit_text(
        draw, "Ag", 40, 20, 48 * 300 / 72, 8 * 300 / 72, None, False, None, False, 1.0)
    assert f18.size == round(18 * 300 / 72)
    assert f48.size == round(48 * 300 / 72)
    assert (bb48[3] - bb48[1]) > (bb18[3] - bb18[1])
    assert n18 and n48


def test_font_dirs_includes_bundled_assets_when_not_frozen():
    """Из исходников в сканируемые каталоги входит badge_backend/assets/fonts."""
    assert getattr(sys, "_MEIPASS", None) is None
    expected = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "badge_backend", "assets", "fonts"))
    scanned = [os.path.abspath(d) for d in _font_dirs()]
    assert expected in scanned
