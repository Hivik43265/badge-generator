"""Рендер карточки CR80 (1011×638 px, 300 DPI) на Pillow.

Главная функция: render_card(person, elements, side='front') -> PIL.Image RGB 1011×638.
Координаты элементов — единицы 0,1 мм (холст 856×540); перевод в px @ 300 DPI внутри функции.
Элементы рисуются по возрастанию z_order (затем id).
"""
from __future__ import annotations
import json, logging, math, os, warnings
from ..fields import format_value
from PIL import Image, ImageDraw, ImageColor, ImageOps
from .. import CARD_W_PX, CARD_H_PX, DPI, CARD_W_UNITS, CARD_H_UNITS, units_to_px
from ..photo_config import PhotoConfig
from .fonts import get_font, find_font_path
log = logging.getLogger(__name__)
__all__ = ["render_card", "render_card_db", "render_preview", "transform_photo", "load_elements",
           "load_background", "load_photo_views", "get_font", "find_font_path"]

def _d(row):
    if row is None: return {}
    return dict(row) if not isinstance(row, dict) else row

def _json(v):
    if isinstance(v, dict): return v
    try: return json.loads(v) if v else {}
    except (ValueError, TypeError): return {}

def _color(v, default=None):
    if v in (None, "", "none", "transparent"): return default
    try: return ImageColor.getcolor(v, "RGBA") if isinstance(v, str) else tuple(v)
    except ValueError: return default

from ..services.photos import resolve_photo_path, open_photo_file, open_photo_bytes, photo_image_bytes, photo_field_value  # noqa: E402

def _resolve(path, base_dir):
    if not path: return None
    return path if os.path.isabs(path) or not base_dir else os.path.join(base_dir, path)

def _open(path):
    if not path: return None
    try:
        return open_photo_file(path).convert("RGBA")
    except Exception as e:  # noqa
        log.warning("не удалось открыть %s: %s", path, e); return None

def _open_photo(person, el, base_dir):
    """Исходник фото записи: путь (в т.ч. кириллица / photos/) или байты, лежащие в поле."""
    pp = resolve_photo_path(person, el, base_dir)
    src = _open(pp) if pp else None
    if src is not None: return src
    blob = photo_image_bytes(photo_field_value(person, el))
    if not blob: return None
    try:
        return open_photo_bytes(blob).convert("RGBA")
    except Exception as e:  # noqa
        log.warning("не удалось открыть фото из значения поля: %s", e); return None

def _cover(im, w, h):
    s = max(w / im.width, h / im.height)
    return im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)

def _cover_crop(im, w, h):
    im = _cover(im, w, h); l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))

# ---------- фото ----------
def transform_photo(src: Image.Image, w: int, h: int, cfg: PhotoConfig | str | None) -> Image.Image:
    """Применить photo_config к исходнику, вернуть RGBA w×h (прозрачно там, где фото нет).

    1) crop: берётся область [crop_x..W)×[crop_y..H) исходника (crop клампится);
    2) cover-fit этой области в рамку w×h, умножить на scale;
    3) поворот на angle градусов ПО ЧАСОВОЙ вокруг центра (expand);
    4) центр фото ставится в центр рамки + (x, y) px; всё вне рамки обрезается.
    """
    if not isinstance(cfg, PhotoConfig): cfg = PhotoConfig.parse(cfg)
    src = src.convert("RGBA")
    cx, cy = min(cfg.crop_x, src.width - 1), min(cfg.crop_y, src.height - 1)
    im = src.crop((cx, cy, src.width, src.height))
    s = max(w / im.width, h / im.height) * cfg.scale
    im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    if cfg.angle % 360:
        im = im.rotate(-cfg.angle, resample=Image.BICUBIC, expand=True)  # PIL: + = против часовой
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = round(w / 2 + cfg.x - im.width / 2); py = round(h / 2 + cfg.y - im.height / 2)
    out.paste(im, (px, py), im)
    return out

def _placeholder(w, h, label="нет фото"):
    im = Image.new("RGBA", (w, h), (225, 228, 232, 255)); d = ImageDraw.Draw(im)
    c = (150, 155, 162, 255)
    d.ellipse((w * .3, h * .15, w * .7, h * .5), fill=c)
    d.pieslice((w * .12, h * .55, w * .88, h * 1.25), 180, 360, fill=c)
    f = get_font(max(10, h // 14)); d.text((w / 2, h - 6), label, font=f, fill=(90, 95, 100, 255), anchor="md")
    return im

def _photo_view(person, el):
    """Этап 15: вид фото записи для элемента: person['photo_views'][field_name], иначе [''] (перенесённый
    photo_config — 'placement'). Персона без 'photo_views' (словарь в обход БД) → её photo_config как вид ''."""
    person = person or {}
    pv = person.get("photo_views")
    if pv is None: pv = {"": {"placement": person.get("photo_config")}}
    v = pv.get(el.get("field_name") or "")
    return v if v is not None else pv.get("")

def _view_tile(src, w, h, params):
    """Вид фото (person_photo_views) — ЕДИНСТВЕННЫЙ путь рендера фото: см. photo_edit.apply_photo_view."""
    from ..services.photo_edit import apply_photo_view
    return apply_photo_view(src, w, h, params)

# ---------- текст ----------
_BREAK_AFTER = "-\u2010\u2011\u2012\u2013\u2014\u2015/"   # дефисы, тире, слэш: знак остаётся в конце строки
ELLIPSIS = "\u2026"

def _split_breaks(word):
    """'Римский-Корсаков' → ['Римский-', 'Корсаков'] (разрыв после дефиса/тире/слэша)."""
    parts, cur = [], ""
    for ch in word:
        cur += ch
        if ch in _BREAK_AFTER: parts.append(cur); cur = ""
    if cur: parts.append(cur)
    return parts

def _tw(d, t, font):
    if not t: return 0
    b = d.textbbox((0, 0), t, font=font, anchor="la")
    return max(b[2], d.textlength(t, font=font)) - min(0, b[0])

def _wrap(d, text, font, width, force=False):
    """Перенос: 1) по пробелам; 2) слово, не влезающее в строку целиком, — по дефисам/тире/слэшу;
    3) force=True — кусок шире рамки режется по символам. → (lines, был_ли_разрез_по_символам)."""
    lines, cut = [], False
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            t = (cur + " " + word) if cur else word
            if _tw(d, t, font) <= width: cur = t; continue
            if _tw(d, word, font) <= width:
                if cur: lines.append(cur)
                cur = word; continue
            # слово шире рамки: дефисы; первый кусок пробуем дописать к текущей строке
            for i, piece in enumerate(_split_breaks(word)):
                t = (cur + (" " if i == 0 else "") + piece) if cur else piece
                if cur and _tw(d, t, font) <= width: cur = t; continue
                if cur: lines.append(cur)
                cur = piece
                if force and _tw(d, cur, font) > width:
                    chunk = ""
                    for ch in cur:
                        if chunk and _tw(d, chunk + ch, font) > width: lines.append(chunk); chunk = ""; cut = True
                        chunk += ch
                    cur = chunk
        lines.append(cur)
    return lines, cut

def _layout(d, lines, font, spacing):
    """Расположить строки (anchor 'la' = левый край, асцендер): → (позиции y, ширины, bbox-объединение)."""
    asc, desc = font.getmetrics() if hasattr(font, "getmetrics") else (font.size, 0)
    lh = (asc + desc) * spacing
    ys = [i * lh for i in range(len(lines))]
    boxes = [d.textbbox((0, y), l, font=font, anchor="la") for l, y in zip(lines, ys) if l]
    if not boxes: return ys, [0] * len(lines), (0, 0, 0, 0), asc + desc
    bb = (min(b[0] for b in boxes), min(0, min(b[1] for b in boxes)),
          max(b[2] for b in boxes), max(ys[-1] + asc + desc, max(b[3] for b in boxes)))
    return ys, [d.textlength(l, font=font) for l in lines], bb, asc + desc

def _ellipsize(d, line, font, width):
    t = line.rstrip()
    while t and _tw(d, t + ELLIPSIS, font) > width: t = t[:-1].rstrip()
    return t + ELLIPSIS if _tw(d, t + ELLIPSIS, font) <= width else ""

def _flag(v) -> bool:
    """Флаг стиля: True/1/"1"/"true"/"yes" — да; False/0/"0"/"false"/""/None — нет."""
    if isinstance(v, str):
        return v.strip().casefold() not in ("", "0", "false", "no", "off", "none", "normal")
    return bool(v)

def _text_style_flags(st) -> tuple[bool, bool]:
    """Замечание №3 (11.11), контракт стиля текста: style['bold']: bool, style['italic']: bool.
    Старые данные: font_style 'italic'/'oblique' → italic; font_weight ≥ 600 или 'bold'/'black'/'heavy' → bold.
    → (bold, italic)."""
    st = st or {}
    bold = _flag(st.get("bold"))
    if not bold:
        fw = st.get("font_weight")
        if isinstance(fw, str):
            w = fw.strip().casefold()
            bold = (int(w) >= 600) if w.isdigit() else any(k in w for k in ("bold", "black", "heavy"))
        elif isinstance(fw, (int, float)) and not isinstance(fw, bool):
            bold = fw >= 600
    italic = _flag(st.get("italic"))
    if not italic:
        fs = st.get("font_style")
        italic = isinstance(fs, str) and any(k in fs.casefold() for k in ("italic", "oblique"))
    return bold, italic

SYNTH_SHEAR = 0.2          # синтетический курсив: наклон ≈ 11° (tan = 0,2)

def _synthetic(font, bold, italic) -> tuple[int, bool]:
    """Чего нет в загруженном начертании: → (толщина обводки для синтетического жирного px, нужен ли наклон).
    Начертание определяется по имени стиля файла (getname()[1]: 'Bold', 'Oblique', 'Bold Italic', …)."""
    from PIL import ImageFont
    from .fonts import _style_slot
    if not isinstance(font, ImageFont.FreeTypeFont):   # растровый шрифт Pillow: ни обводки, ни имени стиля
        return 0, False
    try: slot = _style_slot(font.getname()[1])
    except Exception:  # noqa: BLE001 — встроенный шрифт Pillow без имени
        slot = "regular"
    stroke = 0
    if bold and "bold" not in slot:
        stroke = max(1, round(getattr(font, "size", 10) / 30))
    return stroke, bool(italic and "italic" not in slot)

def _fit_text(d, text, w, h, size_px, min_px, fam, bold, fpath, wrap, spacing, italic=False):
    """Перенос на строго заданном кегле, без уменьшения.

    1) перенос по пробелам, затем по дефисам/тире/слэшу;
    2) слово шире рамки режется по символам (force wrap);
    3) строки, не влезающие по высоте, не отбрасываются и не получают «…» —
       обрезка делается при рисовании по внутренней рамке.

    min_px сохранён в сигнатуре (ключ min_size в стиле принимается), но не используется.
    italic (замечание №3) — выбор курсивного начертания (fonts._pick_face); нет файла — синтетика в _draw_text.
    → (font, lines, ys, widths, bbox, notes)
    """
    size = max(1, int(round(size_px)))
    f = get_font(size, fam, bold, fpath, italic=bool(italic))
    w = max(1, w - 2 * _synthetic(f, bold, italic)[0])   # синтетический жирный: обводка шире глифа на stroke с каждой стороны
    notes = []
    if wrap:
        # сначала обычный перенос (пробелы, дефисы); force — только если строка всё ещё шире рамки
        lines, cut = _wrap(d, text, f, w, force=False)
        if any(_tw(d, l, f) > w for l in lines):
            lines, cut = _wrap(d, text, f, w, force=True)
            if cut:
                notes.append("слово разрезано по символам")
    else:
        lines = str(text).split("\n")
    ys, ws, bb, _ = _layout(d, lines, f, spacing)
    if (bb[2] - min(0, bb[0])) > w or any(_tw(d, l, f) > w for l in lines):
        notes.append("обрезано по ширине")
    if (bb[3] - bb[1]) > h:
        notes.append("обрезано по высоте")
    return f, lines, ys, ws, bb, notes

def _draw_text(img, el, text, st):
    """Текст рисуется строго заданным font_size (pt → px = pt×DPI/72).
    Всё, что выходит за внутреннюю рамку (w×h минус padding; в padding уже входит
    толщина рамки), обрезается по ней. min_size в стиле принимается и игнорируется.
    Замечание №3: bold/italic (_text_style_flags) выбирают начертание; если файла жирного нет —
    синтетический жирный (обводка цветом текста), курсива нет — синтетический наклон (сдвиг строки
    относительно её базовой линии на SYNTH_SHEAR)."""
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    if text is None or str(text) == "": return
    pad = int(st.get("padding", 0)); iw, ih = max(1, w - 2 * pad), max(1, h - 2 * pad)
    # слой ровно внутреннего размера — ничего не попадает в padding/бордюр
    layer = Image.new("RGBA", (iw, ih), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    size = float(st.get("font_size", 10)) * DPI / 72
    bold, italic = _text_style_flags(st)
    f, lines, ys, ws, bb, notes = _fit_text(d, str(text), iw, ih, size, 0, st.get("font_family"),
                                           bold, st.get("font_path"), st.get("wrap", True),
                                           float(st.get("line_spacing", 1.0)), italic=italic)
    stroke, shear = _synthetic(f, bold, italic)
    if notes:
        msg = (f"элемент {el.get('id')}: текст {str(text)[:30]!r} не помещается в {w}×{h} "
               f"при заданном размере — обрезан ({'; '.join(notes)})")
        log.warning(msg); warnings.warn(msg, RuntimeWarning, stacklevel=3)
    color = _color(st.get("color"), (0, 0, 0, 255)); align = st.get("align", "left"); va = st.get("valign", "top")
    if not lines:
        img.paste(layer, (x + pad, y + pad), layer); return
    th = bb[3] - bb[1]
    oy = -bb[1] + {"middle": (ih - th) / 2, "center": (ih - th) / 2, "bottom": ih - th}.get(va, 0)
    oy = min(max(oy, -bb[1]), ih - bb[3]) if th <= ih else -bb[1]      # если выше рамки — сверху, низ обрежется
    for line, ly, lw in zip(lines, ys, ws):
        if not line: continue
        lb = d.textbbox((0, 0), line, font=f, anchor="la")
        gw = lb[2] - min(0, lb[0])
        ox = -min(0, lb[0]) + {"center": (iw - gw) / 2, "right": iw - gw}.get(align, 0)
        if gw <= iw:
            ox = min(max(ox, -min(0, lb[0])), iw - lb[2])
        sk = {"stroke_width": stroke, "stroke_fill": color} if stroke else {}
        if not shear:
            d.text((ox, oy + ly), line, font=f, fill=color, anchor="la", **sk)
            continue
        # синтетический курсив: строка на отдельном слое, сдвиг x += SHEAR·(базовая линия − y)
        asc = f.getmetrics()[0] if hasattr(f, "getmetrics") else f.size
        ox -= {"center": SYNTH_SHEAR * asc / 2, "right": SYNTH_SHEAR * asc}.get(align, 0)
        ll = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(ll).text((ox, oy + ly), line, font=f, fill=color, anchor="la", **sk)
        yb = oy + ly + asc
        affine = getattr(getattr(Image, "Transform", Image), "AFFINE")
        ll = ll.transform(ll.size, affine, (1, SYNTH_SHEAR, -SYNTH_SHEAR * yb, 0, 1, 0), resample=Image.BICUBIC)
        layer.alpha_composite(ll)
    img.paste(layer, (x + pad, y + pad), layer)

# ---------- прочие элементы ----------
def _px(st, key):
    """Размер в px: key (px) или key_mm (мм)."""
    if st.get(key) is not None: return float(st[key])
    if st.get(key + "_mm") is not None: return float(st[key + "_mm"]) / 25.4 * DPI
    return 0.0


def _radius_px(st):
    if st.get("radius") is not None:
        return float(units_to_px(st["radius"], DPI))
    if st.get("radius_mm") is not None:
        return float(st["radius_mm"]) / 25.4 * DPI
    return 0.0

def _border_spec(st):
    style = st.get("border_style")
    if style is None:
        # legacy: stroke / stroke_width или border_color / border_width без border_style → solid
        if st.get("stroke_width") not in (None, "", 0, "0") or (
            st.get("stroke") not in (None, "", "none") and st.get("stroke_width") is None
            and st.get("border_width") is None
        ) or st.get("border_width") not in (None, "", 0, "0") or (
            st.get("border_color") not in (None, "") and st.get("border_width") is None
        ):
            style = "solid"
        else:
            style = "none"
    if style == "none":
        return "none", 0, None
    if st.get("border_width") not in (None, ""):
        bw = units_to_px(st["border_width"], DPI)
    elif st.get("stroke_width") not in (None, ""):
        bw = units_to_px(st["stroke_width"], DPI)
    else:
        bw = 1 if (st.get("stroke") is not None or st.get("border_color") is not None) else 0
    if not bw or bw <= 0:
        return "none", 0, None
    bw = max(1, int(round(bw)))
    color = _color(st.get("border_color", st.get("stroke")), (0, 0, 0, 255))
    return style, bw, color

def _bg_spec(st):
    if "bg_fill" in st:
        return bool(st.get("bg_fill")), _color(st.get("bg_color", st.get("fill")), (255, 255, 255, 255))
    if st.get("fill") not in (None, "", "none", "transparent"):
        return True, _color(st.get("fill"))
    return False, None

def _code_bg(st):
    """Фон штрихкода/QR: bg_fill (панель свойств, §9) приоритетнее; bg_fill=false — прозрачно (None).
    Без bg_fill — как раньше: background/fill, по умолчанию белый."""
    legacy = st.get("background", st.get("fill", "#FFFFFF"))
    if "bg_fill" in st:
        if not st.get("bg_fill"): return None
        return _color(st.get("bg_color", legacy), (255, 255, 255, 255))
    return _color(legacy)

def _dashed_rect(d, x, y, w, h, bw, color, dash=8, gap=6):
    segs = [
        (x, y, x + w, y),
        (x + w - 1, y, x + w - 1, y + h),
        (x + w, y + h - 1, x, y + h - 1),
        (x, y + h, x, y),
    ]
    for x0, y0, x1, y1 in segs:
        dx, dy = x1 - x0, y1 - y0
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / length, dy / length
        pos = 0.0
        on = True
        while pos < length:
            step = dash if on else gap
            npos = min(length, pos + step)
            if on:
                d.line((x0 + ux * pos, y0 + uy * pos, x0 + ux * npos, y0 + uy * npos), fill=color, width=bw)
            pos = npos
            on = not on

def _stroke_inside(d, x, y, w, h, bw, color, style, radius=0):
    bw = max(1, int(bw))
    if style in ("dash", "dot"):
        _dashed_rect(d, x, y, w, h, bw, color, dash=(8 if style == "dash" else 2), gap=(6 if style == "dash" else 4))
        return
    if radius:
        inset = (bw - 1) / 2.0
        box = (x + inset, y + inset, x + w - 1 - inset, y + h - 1 - inset)
        d.rounded_rectangle(box, radius=max(0, radius - inset), outline=color, width=bw)
        return
    d.rectangle((x, y, x + w - 1, y + bw - 1), fill=color)
    d.rectangle((x, y + h - bw, x + w - 1, y + h - 1), fill=color)
    d.rectangle((x, y, x + bw - 1, y + h - 1), fill=color)
    d.rectangle((x + w - bw, y, x + w - 1, y + h - 1), fill=color)

def _box(img, el, st, fill_default=None):
    """Рамка/прямоугольник. Заливка: bg_fill/bg_color или fill. Обводка целиком внутри прямоугольника."""
    fill_on, fill = _bg_spec(st)
    if fill_default is not None and not fill_on:
        fill = _color(st.get("fill"), fill_default); fill_on = fill is not None
    bstyle, bw, bc = _border_spec(st)
    r = round(_radius_px(st))
    if not fill_on and not (bstyle != "none" and bw): return
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    if fill_on and fill:
        if r: d.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=r, fill=fill)
        else: d.rectangle((x, y, x + w - 1, y + h - 1), fill=fill)
    if bstyle != "none" and bw and bc:
        _stroke_inside(d, x, y, w, h, bw, bc, bstyle, r)
    img.alpha_composite(layer)

def _ellipse(img, el, st):
    """Эллипс, вписанный в рамку. style как у rect: fill, stroke (= border_color), stroke_width (= border_width); radius игнорируется."""
    fill_on, fill = _bg_spec(st)
    if not fill_on:
        fill = _color(st.get("fill"))
    bstyle, bw, bc = _border_spec(st)
    if not fill and not (bstyle != "none" and bw): return
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((x, y, x + w - 1, y + h - 1), fill=fill,
                                  outline=bc if (bstyle != "none" and bw) else None, width=bw or 1)
    img.alpha_composite(layer)

def _paste_clipped(img, el, tile, st):
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    r = round(_radius_px(st))
    mask = tile.getchannel("A")
    if r:
        m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
        from PIL import ImageChops; mask = ImageChops.multiply(mask, m)
    img.paste(tile.convert("RGB"), (x, y), mask)

def _field_value(person, name, default=None):
    """Значение поля записи; если пусто/None — default (person_fields.default_value, приходит в el['default_value'])."""
    v = _raw_field_value(person, name)
    return default if v in (None, "") and default not in (None, "") else v

def _raw_field_value(person, name):
    if not person: return None
    f = person.get("fields") if isinstance(person.get("fields"), dict) and person.get("fields_json") is None \
        else _json(person.get("fields_json"))
    if name in f: return f[name]
    if name in ("id",) and person: return person.get("id")
    return None

# ---------- главная ----------
def _prep_style(st):
    """Копия стиля: padding/radius уже в единицах → px для внутренних рисовальщиков."""
    st = dict(st or {})
    if st.get("padding") is not None:
        try: st["padding"] = units_to_px(st["padding"], DPI)
        except (TypeError, ValueError): pass
    return st

def _line_points(el, st):
    """Концы линии (px); при rotation — поворот по часовой стрелке вокруг центра рамки."""
    x0, y0, x1, y1 = el["x"], el["y"], el["x"] + el["w"], el["y"] + el["h"]
    rot = float(st.get("rotation") or 0)
    if rot % 360 == 0:
        return (x0, y0, x1, y1)
    a = math.radians(rot); ca, sa = math.cos(a), math.sin(a)
    cx, cy = el["x"] + el["w"] / 2, el["y"] + el["h"] / 2
    def r(px, py):
        dx, dy = px - cx, py - cy
        return (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)   # ось y вниз → по часовой
    return (*r(x0, y0), *r(x1, y1))

def _composite_layer(img, layer, el, st):
    """Наклеить слой w×h; при rotation — вокруг центра рамки по часовой стрелке."""
    rot = float(st.get("rotation") or 0)
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    if rot % 360 != 0:
        layer = layer.rotate(-rot, expand=True, resample=Image.BICUBIC)
        x = round(x + w / 2 - layer.width / 2)
        y = round(y + h / 2 - layer.height / 2)
        img.alpha_composite(layer, (x, y))
    else:
        img.alpha_composite(layer, (x, y))

def render_card(person, elements, side: str = "front", background=None, base_dir=None) -> Image.Image:
    """Отрисовать сторону карточки.

    person      dict или sqlite3.Row: fields_json (str JSON или dict), photo_path, photo_config;
                этап 15: 'photo_views' {field_name|'': params} — вид фото записи (важнее photo_config);
                краткая форма {'fields': {...}, 'photo_path': ..., 'photo_config': ...};
                None — пустой шаблон. Если есть и fields_json, и fields — используется fields_json.
    elements    итерируемое template_elements (dict/Row); x,y,w,h — единицы 0,1 мм; берутся только с данным side.
    side        'front' | 'back'.
    background  dict/Row template_backgrounds {'color', 'image_path'} или None (белый).
    base_dir    база для относительных путей (photo_path, image_path, static_value у image).
    Возвращает PIL.Image RGB ровно 1011×638 @ 300 DPI.
    """
    if side not in ("front", "back"): raise ValueError("side должен быть 'front' или 'back'")
    person = _d(person); bg = _d(background)
    W, H = units_to_px(CARD_W_UNITS, DPI), units_to_px(CARD_H_UNITS, DPI)
    img = Image.new("RGBA", (W, H), _color(bg.get("color"), (255, 255, 255, 255)))
    if bg.get("image_path"):
        b = _open(_resolve(bg["image_path"], base_dir))
        if b: img.alpha_composite(_cover_crop(b, W, H))
    els = sorted((_d(e) for e in elements if _d(e).get("side", "front") == side),
                 key=lambda e: (int(e.get("z_order") or 0), e.get("id") or 0))   # №7: z_order=None не роняет сортировку
    for el in els:
        el = {**el, **{k: units_to_px(el[k], DPI) for k in ("x", "y", "w", "h")}}
        if el["type"] == "line":
            if el["w"] == 0 and el["h"] == 0: continue
        elif el["w"] <= 0 or el["h"] <= 0: continue
        st = _prep_style(_json(el.get("style_json"))); t = el["type"]
        try:
            if t == "line":
                bstyle, bw, bc = _border_spec(st)
                c = bc or _color(st.get("stroke", st.get("color")), (0, 0, 0, 255))
                sw = bw or max(1, round(_px(st, "stroke_width") or 1))
                layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                pts = _line_points(el, st)
                ImageDraw.Draw(layer).line(pts, fill=c, width=sw)
                img.alpha_composite(layer)
                continue
            tile = Image.new("RGBA", (max(1, el["w"]), max(1, el["h"])), (0, 0, 0, 0))
            loc = {**el, "x": 0, "y": 0}
            fill_on, fill_c = _bg_spec(st)
            if fill_on and fill_c and t not in ("rect", "ellipse"):
                ImageDraw.Draw(tile).rectangle((0, 0, loc["w"] - 1, loc["h"] - 1), fill=fill_c)
            bstyle, bw, bc = _border_spec(st)
            st_content = dict(st)
            if bstyle != "none" and bw:
                st_content["padding"] = int(st_content.get("padding") or 0) + bw
            if t == "rect":
                _box(tile, loc, st, fill_default=None)
            elif t == "ellipse":
                _ellipse(tile, loc, st)
            elif t in ("text", "field"):
                if t == "text" or not el.get("field_name"): val = el.get("static_value")
                else: val = _field_value(person, el.get("field_name"), el.get("default_value"))
                if t == "field" and el.get("data_type"): val = format_value(el["data_type"], val) if val is not None else val
                _draw_text(tile, loc, val, st_content)
            elif t == "photo":
                src = _open_photo(person, el, base_dir)
                view = _photo_view(person, el)
                if src: ph = _view_tile(src, el["w"], el["h"], view)
                else: ph = _placeholder(el["w"], el["h"], el.get("_placeholder_label") or "нет фото")
                _paste_clipped(tile, loc, ph, st)
            elif t == "image":
                src = _open(_resolve(el.get("static_value"), base_dir))
                if src:
                    fit = st.get("fit", "contain")
                    if fit == "cover": ph = _cover_crop(src, el["w"], el["h"])
                    else:
                        ph = Image.new("RGBA", (el["w"], el["h"]), (0, 0, 0, 0))
                        c = ImageOps.contain(src, (el["w"], el["h"]), Image.LANCZOS)
                        ph.paste(c, ((el["w"] - c.width) // 2, (el["h"] - c.height) // 2))
                    _paste_clipped(tile, loc, ph, st)
            elif t == "barcode":
                from .barcode import render_barcode
                val = el.get("static_value") if not el.get("field_name") else _field_value(person, el["field_name"], el.get("default_value"))
                if val in (None, "") and el.get("field_name") and el.get("static_value"): val = el["static_value"]
                ph = render_barcode(el["w"], el["h"], val, st, _color(st.get("color"), (0, 0, 0, 255)),
                                    _code_bg(st), el.get("id"))
                tile.paste(ph, (0, 0), ph)
            elif t == "qr":
                from .qr import render_qr
                val = _field_value(person, el["field_name"], el.get("default_value")) if el.get("field_name") else el.get("static_value")
                if val in (None, "") and el.get("field_name") and el.get("static_value"): val = el["static_value"]
                ph = render_qr(el["w"], el["h"], val, st, _color(st.get("color"), (0, 0, 0, 255)),
                               _code_bg(st), el.get("id"))
                tile.paste(ph, (0, 0), ph)
            else:
                log.warning("неизвестный тип элемента %r пропущен", t); continue
            if t not in ("rect", "ellipse"):
                if bstyle != "none" and bw and bc:
                    d = ImageDraw.Draw(tile)
                    _stroke_inside(d, 0, 0, loc["w"], loc["h"], bw, bc, bstyle, round(_radius_px(st)))
            _composite_layer(img, tile, el, st)
        except Exception as e:  # элемент не должен ронять карточку
            log.warning("элемент %s (%s) не отрисован: %s", el.get("id"), t, e)
    return img.convert("RGB")

def load_elements(con, side=None, template_id=None):
    """Элементы стороны шаблона (None — активного) + default_value привязанного поля (person_fields.default_value).
    Этап 15: стиль шаблона (font_family, padding) подмешивается в style_json text/field-объектов, где своего нет."""
    from ..db import active_template_id
    tid = template_id or active_template_id(con)
    tst = json.loads((con.execute("SELECT style_json FROM templates WHERE id=?", (tid,)).fetchone() or ["{}"])[0] or "{}")
    q = ("SELECT e.*, f.default_value AS default_value, f.data_type AS data_type, f.label AS field_label FROM template_elements e "
         "LEFT JOIN person_fields f ON f.name = e.field_name WHERE e.template_id=?" + (" AND e.side=?" if side else "")
         + " ORDER BY e.z_order, e.id")
    out = []
    for r in con.execute(q, (tid, side) if side else (tid,)):
        d = dict(r)
        if tst and d["type"] in ("text", "field"):
            d["style_json"] = json.dumps({**tst, **_json(d.get("style_json"))}, ensure_ascii=False)
        out.append(d)
    return out

def load_background(con, side, template_id=None):
    """Фон стороны шаблона (None — активного) → {'side','image_path','color'} | None."""
    from ..db import active_template_id
    r = con.execute("SELECT side, image_path, color FROM template_backgrounds2 WHERE template_id=? AND side=?",
                    (template_id or active_template_id(con), side)).fetchone()
    return dict(r) if r else None

def load_photo_views(con, person_id) -> dict:
    """{field_name ('' — photo_path): params} вида фото записи (person_photo_views)."""
    return {r[0]: json.loads(r[1]) for r in con.execute(
        "SELECT field_name, params_json FROM person_photo_views WHERE person_id=?", (person_id,))}

def _field_name_view(elements) -> list[dict]:
    """Замечание №5а: элементы для вида «шаблон с названиями полей» (без записи).
    Привязанный text/field → постоянный текст = название поля (label, иначе имя) своим шрифтом и стилем;
    привязанный photo → заглушка с названием поля; остальное (постоянный текст, картинки, фигуры, коды) — как есть.
    Красные #поле здесь не рисуются никогда — это разметка редактора (Frontend, Qt)."""
    out = []
    for e in elements:
        e = dict(_d(e)); fn = e.get("field_name"); t = e.get("type")
        if fn and t in ("text", "field"):
            e.update(type="text", static_value=e.get("field_label") or fn, data_type=None)
        elif fn and t == "photo":
            e["_placeholder_label"] = e.get("field_label") or fn
        out.append(e)
    return out

def render_card_db(con, person=None, side="front", base_dir=None, *, field_names: bool = False) -> Image.Image:
    """render_card по данным из БД. person — id или row; None — пустой шаблон.
    field_names (замечание №5а, только при person=None), по умолчанию False — прежний пустой шаблон
    (значения по умолчанию полей, заглушка «нет фото»). True — ТОЛЬКО по явному запросу редактора: привязанные
    текстовые объекты рисуются названием поля (label) своим шрифтом/стилем, фото-объект — заглушкой с названием поля;
    постоянный текст и картинки — как есть. С записью field_names не влияет. Печать/PNG/PDF рендерят записи
    через render_card и названий полей не получают независимо от флага."""
    if isinstance(person, int):
        r = con.execute("SELECT * FROM persons WHERE id=?", (person,)).fetchone()
        if r is None: raise KeyError(f"person {person} не найден")
        person = r
    if person is not None:
        person = dict(person)
        if "photo_views" not in person and person.get("id") is not None: person["photo_views"] = load_photo_views(con, person["id"])
    els = load_elements(con, side)
    if person is None and field_names: els = _field_name_view(els)
    return render_card(person, els, side, load_background(con, side), base_dir)

def render_preview(con, person, side="front", scale: float = 0.5, base_dir=None) -> Image.Image:
    """Уменьшенное превью для Frontend (scale 0<s<=1, размер round(1011*s)×round(638*s))."""
    if not 0 < scale <= 4: raise ValueError("scale в диапазоне (0, 4]")
    im = render_card_db(con, person, side, base_dir)
    if scale == 1: return im
    return im.resize((max(1, round(CARD_W_PX * scale)), max(1, round(CARD_H_PX * scale))), Image.LANCZOS)
