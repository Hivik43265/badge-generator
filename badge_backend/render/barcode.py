"""Штрихкоды v1: Code128 (по умолчанию) и EAN-13. Модули берутся из python-barcode
(barcode.get(fmt, value).build() → строка '1010…'), растеризация — своя, на Pillow:
целое число px на модуль (максимально возможное), центрирование в рамке w×h, без искажения ширины модуля.

style_json: {"format": "code128"|"ean13", "show_text": bool (True), "quiet_zone": int модулей (10),
             "color": "#000000", "background": "#FFFFFF" (или null — прозрачно), "font_size": pt (8)}
"""
from __future__ import annotations
import logging, warnings
from PIL import Image, ImageDraw
log = logging.getLogger(__name__)
FORMATS = ("code128", "ean13")
DEFAULT_QUIET = 10

class BarcodeError(ValueError):
    pass

def ean13_checksum(d12: str) -> int:
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return (10 - s % 10) % 10

def normalize_value(fmt: str, value) -> str:
    """Проверить значение → строка для кодирования/подписи. Ошибка → BarcodeError."""
    fmt = (fmt or "code128").lower()
    if fmt not in FORMATS: raise BarcodeError(f"формат {fmt!r} не поддерживается (code128|ean13)")
    v = "" if value is None else str(value).strip()
    if not v: raise BarcodeError("пустое значение")
    if fmt == "ean13":
        if not v.isdigit() or len(v) not in (12, 13): raise BarcodeError(f"EAN-13: нужно 12 или 13 цифр, получено {v!r}")
        cs = ean13_checksum(v[:12])
        if len(v) == 13 and int(v[12]) != cs: raise BarcodeError(f"EAN-13: неверная контрольная цифра в {v!r} (ожидалась {cs})")
        return v[:12] + str(cs)
    if any(ord(c) > 127 for c in v): raise BarcodeError(f"Code128: только ASCII, получено {v!r}")
    return v

def modules(fmt: str, value) -> tuple[str, str]:
    """→ (строка модулей '1'/'0' без тихих зон, текст подписи)."""
    import barcode
    v = normalize_value(fmt, value); fmt = (fmt or "code128").lower()
    try:
        bc = barcode.get(fmt, v[:12] if fmt == "ean13" else v)
        code = "".join(bc.build())
    except Exception as e:
        raise BarcodeError(f"python-barcode: {e}") from e
    code = code.replace("G", "1")      # EAN: удлинённые охранные полосы рисуем как обычные
    return code, (bc.get_fullcode() if fmt == "ean13" else v)

def layout(n_modules: int, w: int, quiet: int) -> tuple[int, int]:
    """→ (px на модуль, x-смещение начала первого модуля внутри рамки). px=0 — не помещается."""
    total = n_modules + 2 * quiet
    m = w // total if total else 0
    if m < 1: return 0, 0
    return m, (w - m * total) // 2 + m * quiet

def render_barcode(w: int, h: int, value, st: dict, color=(0, 0, 0, 255), background=(255, 255, 255, 255),
                   el_id=None) -> Image.Image:
    """RGBA w×h. Невалидное значение или не влезает → пустая рамка (фон) + warning, без исключения."""
    from .fonts import get_font
    from .. import DPI
    tile = Image.new("RGBA", (w, h), background or (0, 0, 0, 0))
    fmt = str(st.get("format") or st.get("symbology") or "code128").lower()   # symbology — синоним (UI)
    try:
        code, text = modules(fmt, value)
        quiet = max(0, int(st.get("quiet_zone", DEFAULT_QUIET)))
        m, x0 = layout(len(code), w, quiet)
        if not m: raise BarcodeError(f"{len(code)}+2×{quiet} модулей не помещаются в ширину {w} px")
    except (BarcodeError, ValueError, TypeError) as e:
        msg = f"элемент {el_id}: штрихкод {fmt} {str(value)[:30]!r} не отрисован — {e}"
        log.warning(msg); warnings.warn(msg, RuntimeWarning, stacklevel=3)
        return tile
    d = ImageDraw.Draw(tile)
    bar_h = h
    if st.get("show_text", True):
        f = get_font(max(1, round(float(st.get("font_size", 8)) * DPI / 72)))
        asc, desc = f.getmetrics(); th = asc + desc
        if th < h * 0.6:
            bar_h = h - th
            d.text((w / 2, h), text, font=f, fill=color, anchor="md")
    i = 0
    while i < len(code):
        if code[i] == "1":
            j = i
            while j < len(code) and code[j] == "1": j += 1
            d.rectangle((x0 + i * m, 0, x0 + j * m - 1, bar_h - 1), fill=color)
            i = j
        else: i += 1
    return tile
