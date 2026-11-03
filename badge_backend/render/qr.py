"""QR v1 через qrcode: матрица модулей → своя растеризация (целое число px на модуль, квадрат в min(w,h), по центру).
style_json: {"error_correction": "L"|"M"|"Q"|"H" ("M"), "border": модулей тихой зоны (4),
             "color": "#000000", "background": "#FFFFFF"|null}"""
from __future__ import annotations
import logging, warnings
from PIL import Image, ImageDraw
log = logging.getLogger(__name__)
DEFAULT_BORDER = 4

def matrix(value, ec="M"):
    import qrcode
    from qrcode.exceptions import DataOverflowError
    lv = {"L": qrcode.constants.ERROR_CORRECT_L, "M": qrcode.constants.ERROR_CORRECT_M,
          "Q": qrcode.constants.ERROR_CORRECT_Q, "H": qrcode.constants.ERROR_CORRECT_H}
    ec = str(ec or "M").upper()
    if ec not in lv: raise ValueError(f"error_correction {ec!r}: только L|M|Q|H")
    v = "" if value is None else str(value)
    if not v.strip(): raise ValueError("пустое значение")
    q = qrcode.QRCode(error_correction=lv[ec], border=0)
    try:
        q.add_data(v); q.make(fit=True)
    except (DataOverflowError, ValueError) as e:
        raise ValueError("данные не помещаются в QR (версия 40)") from e
    return q.get_matrix()

def render_qr(w, h, value, st, color=(0, 0, 0, 255), background=(255, 255, 255, 255), el_id=None) -> Image.Image:
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    try:
        mtx = matrix(value, st.get("error_correction", "M"))
        border = max(0, int(st.get("border", DEFAULT_BORDER)))
        n = len(mtx) + 2 * border; side = min(w, h); m = side // n
        if m < 1: raise ValueError(f"{len(mtx)}+2×{border} модулей не помещаются в {side} px")
    except (ValueError, TypeError) as e:
        msg = f"элемент {el_id}: QR {str(value)[:30]!r} не отрисован — {e}"
        log.warning(msg); warnings.warn(msg, RuntimeWarning, stacklevel=3)
        if background: ImageDraw.Draw(tile).rectangle((0, 0, w - 1, h - 1), fill=background)
        return tile
    ox, oy = (w - m * n) // 2, (h - m * n) // 2
    d = ImageDraw.Draw(tile)
    if background: d.rectangle((ox, oy, ox + m * n - 1, oy + m * n - 1), fill=background)
    for r, row in enumerate(mtx):
        for c, on in enumerate(row):
            if on:
                x = ox + (c + border) * m; y = oy + (r + border) * m
                d.rectangle((x, y, x + m - 1, y + m - 1), fill=color)
    return tile
