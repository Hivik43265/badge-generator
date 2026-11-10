"""Тестовые картинки (make_photo/make_logo) и загрузчик макетов из JSON. Макетов в коде нет —
демо-макет лежит в tests/fixtures/demo_layout.json."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
from . import api

def make_photo(path, w=600, h=800):
    """Синтетическое «фото»: градиент + лицо, чтобы видеть трансформации."""
    im = Image.new("RGB", (w, h)); d = ImageDraw.Draw(im)
    for yy in range(h): d.line((0, yy, w, yy), fill=(60 + yy * 120 // h, 110, 190 - yy * 90 // h))
    d.ellipse((w*.25, h*.15, w*.75, h*.55), fill=(240, 205, 170)); d.rectangle((w*.2, h*.62, w*.8, h), fill=(40, 60, 90))
    d.ellipse((w*.36, h*.28, w*.44, h*.34), fill="black"); d.ellipse((w*.56, h*.28, w*.64, h*.34), fill="black")
    d.arc((w*.38, h*.36, w*.62, h*.48), 20, 160, fill=(150, 40, 40), width=8)
    im.save(path); return path

def make_logo(path, s=200):
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse((0, 0, s - 1, s - 1), fill="#1F4E8C"); d.rectangle((s*.3, s*.3, s*.7, s*.7), fill="#FFFFFF")
    im.save(path); return path

DEMO_LAYOUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "demo_layout.json"

def apply_layout(con, layout) -> list[int]:
    """Применить макет {"backgrounds": {side: {color, image_path}}, "elements": [{type,x,y,w,h,side,...,style}]}
    (dict или путь к JSON) через публичное API. → id созданных элементов. Существующие элементы не удаляются."""
    if not isinstance(layout, dict): layout = json.loads(Path(layout).read_text(encoding="utf-8"))
    from . import px_to_units
    convert = layout.get("units") in (None, "px")
    for side, bg in (layout.get("backgrounds") or {}).items():
        api.set_background(con, side, bg.get("color") or "#FFFFFF", bg.get("image_path"))
    ids = []
    for e in layout.get("elements") or []:
        e = dict(e); typ = e.pop("type")
        x, y, w, h = e.pop("x"), e.pop("y"), e.pop("w"), e.pop("h")
        if convert:
            x, y, w, h = px_to_units(x), px_to_units(y), px_to_units(w), px_to_units(h)
            st = e.get("style")
            if isinstance(st, dict):
                st = dict(st)
                for k in ("padding", "radius"):
                    if st.get(k) is not None:
                        st[k] = px_to_units(st[k])
                if st.get("border_width") is not None and "border_style" not in st:
                    st["border_width"] = px_to_units(st["border_width"])
                    if st["border_width"] > 0:
                        st["border_style"] = "solid"
                e["style"] = st
        ids.append(api.create_element(con, typ, x, y, w, h, **e))
    return ids

def build_demo(con, layout=None):
    """ТОЛЬКО для тестов/смоука: загрузить демо-макет из tests/fixtures/demo_layout.json.
    Seed-макетов в коде нет: шаблон нового проекта пуст. Без tests/fixtures → FileNotFoundError."""
    return apply_layout(con, layout or DEMO_LAYOUT)
