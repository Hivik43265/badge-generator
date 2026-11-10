"""Системные и встроенные TTF/OTF/TTC: каталог семейств и загрузка для рендера.

Запасная цепочка: Arial → Segoe UI → Tahoma → DejaVu. load_default — только если нет ни одного TTF.
"""
from __future__ import annotations

import logging
import os
import sys

from PIL import ImageFont

log = logging.getLogger(__name__)
_EXTS = (".ttf", ".otf", ".ttc")
FALLBACK_FAMILIES = ("Arial", "Segoe UI", "Tahoma", "DejaVu Sans", "DejaVu")

# Заполняется один раз за процесс (_scan_catalog).
_CATALOG: dict[str, dict] | None = None
_FALLBACK_NAME: str | None = None


def _font_dirs() -> list[str]:
    local = os.environ.get("LOCALAPPDATA") or ""
    dirs = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.expanduser("~/.fonts"),
        os.path.expanduser("~/.local/share/fonts"),
        "C:/Windows/Fonts",
        os.path.join(local, "Microsoft", "Windows", "Fonts") if local else "",
        "/Library/Fonts",
        "/System/Library/Fonts",
        os.path.expanduser("~/Library/Fonts"),
    ]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        dirs.extend((mei, os.path.join(mei, "fonts"), os.path.join(mei, "badge_backend", "fonts")))
    return [d for d in dirs if d and os.path.isdir(d)]


def _style_slot(style: str) -> str:
    s = (style or "").casefold().replace("-", " ")
    bold = any(w in s for w in ("bold", "black", "heavy", "demibold", "semibold"))
    italic = "italic" in s or "oblique" in s
    if bold and italic:
        return "bold italic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return "regular"


def _iter_faces(path: str):
    ext = os.path.splitext(path)[1].lower()
    n = 32 if ext == ".ttc" else 1
    for index in range(n):
        try:
            face = ImageFont.truetype(path, size=16, index=index)
        except (OSError, ValueError, SyntaxError):
            break
        yield face, index


def _scan_catalog() -> dict[str, dict]:
    """Семейство (casefold) → {name, regular, bold, italic, bold italic}."""
    cat: dict[str, dict] = {}
    for root in _font_dirs():
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if os.path.splitext(name)[1].lower() not in _EXTS:
                    continue
                path = os.path.join(dirpath, name)
                try:
                    for face, index in _iter_faces(path):
                        try:
                            family, style = face.getname()
                        except Exception:  # noqa: BLE001 — битый/защищённый файл
                            continue
                        family = (family or "").strip()
                        if not family:
                            continue
                        key = family.casefold()
                        rec = cat.setdefault(key, {"name": family})
                        slot = _style_slot(style)
                        if slot not in rec:
                            rec[slot] = (path, index)
                except (OSError, ValueError, SyntaxError):
                    continue
    return cat


def _catalog() -> dict[str, dict]:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = _scan_catalog()
    return _CATALOG


def _match_family(cat: dict[str, dict], name: str) -> dict | None:
    if not name:
        return None
    key = name.casefold()
    if key in cat:
        return cat[key]
    for k, rec in cat.items():
        if k.startswith(key) or key.startswith(k):
            return rec
    return None


def fallback_family() -> str | None:
    """Имя запасного семейства, которое реально есть в каталоге (или None, если TTF нет)."""
    global _FALLBACK_NAME
    if _FALLBACK_NAME is not None:
        return _FALLBACK_NAME or None
    cat = _catalog()
    name = None
    for want in FALLBACK_FAMILIES:
        rec = _match_family(cat, want)
        if rec:
            name = rec["name"]
            break
    if name is None and cat:
        name = sorted(cat.values(), key=lambda r: r["name"].casefold())[0]["name"]
    _FALLBACK_NAME = name or ""
    return name


def list_fonts() -> list[str]:
    """Отсортированные отображаемые имена семейств, которые рендерер может загрузить.

    Всегда включает запасное семейство, если в системе (или рядом с exe) есть хотя бы один TTF/OTF/TTC.
    """
    cat = _catalog()
    names = {rec["name"] for rec in cat.values()}
    fb = fallback_family()
    if fb:
        names.add(fb)
    return sorted(names, key=lambda s: s.casefold())


list_font_families = list_fonts


def _pick_face(rec: dict, bold: bool, italic: bool):
    order = []
    if bold and italic:
        order = ["bold italic", "italic", "bold", "regular"]
    elif bold:
        order = ["bold", "regular", "bold italic", "italic"]
    elif italic:
        order = ["italic", "regular", "bold italic", "bold"]
    else:
        order = ["regular", "bold", "italic", "bold italic"]
    for slot in order:
        if slot in rec and slot != "name":
            return rec[slot]
    for k, v in rec.items():
        if k != "name":
            return v
    return None


def find_font_path(family=None, bold=False, italic=False):
    """Путь к файлу шрифта (без индекса TTC) или None, если в каталоге пусто."""
    ref = _resolve_ref(family, bold, italic, warn_missing=False)
    if ref is None:
        return None
    return ref[0]


def _resolve_ref(family, bold, italic, *, warn_missing: bool):
    cat = _catalog()
    rec = _match_family(cat, family) if family else None
    if rec is None and family:
        if warn_missing:
            fb = fallback_family()
            log.warning("шрифт семейства %r не найден, беру запасной %s", family, fb)
        rec = _match_family(cat, fallback_family() or "")
    if rec is None:
        rec = _match_family(cat, fallback_family() or "")
    if rec is None:
        return None
    return _pick_face(rec, bold, italic)


def _load_face(ref, size_px):
    path, index = ref
    return ImageFont.truetype(path, size_px, index=index)


def get_font(size_px, family=None, bold=False, font_path=None, *, italic=False):
    """Загрузить TrueType заданного кегля в пикселях. italic — только keyword.

    Неизвестный family → предупреждение в лог и запасной TTF (Arial → Segoe UI → Tahoma → DejaVu).
    load_default — только если на машине нет ни одного TTF; тогда пишется error.
    """
    size_px = max(1, int(size_px))
    if font_path and os.path.isfile(font_path):
        try:
            return ImageFont.truetype(font_path, size_px)
        except (OSError, ValueError):
            log.warning("не удалось открыть font_path %s, ищу семейство", font_path)
    ref = _resolve_ref(family, bold, italic, warn_missing=True)
    if ref is not None:
        try:
            return _load_face(ref, size_px)
        except (OSError, ValueError):
            log.warning("не удалось загрузить %s, пробую другой TTF", ref[0])
            cat = _catalog()
            for rec in cat.values():
                alt = _pick_face(rec, bold, italic)
                if not alt or alt == ref:
                    continue
                try:
                    return _load_face(alt, size_px)
                except (OSError, ValueError):
                    continue
    log.error("нет доступного TTF/OTF, беру встроенный шрифт Pillow — кегль может не меняться")
    try:
        return ImageFont.load_default(size_px)
    except TypeError:
        return ImageFont.load_default()
