#!/usr/bin/env python3
"""Генератор тестовых наборов: python make_testsets.py [out_dir]
Канонические наборы — CSV; messy_headers — сырой xlsx для Backend."""
import csv, json, random, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook

H = ["last_name", "first_name", "middle_name", "position", "department", "photo_path", "email", "phone", "photo_config"]
LN = ["Иванов", "Петров", "Сидоров", "Козлов", "Ёлкин", "Смирнов"]
FN = ["Иван", "Пётр", "Алексей", "Мария", "Ольга", "Сергей"]


SIZES = [(300, 400), (300, 400), (600, 800), (400, 300), (300, 400)]


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def pattern(w, h, idx, meta=None):
    """Полностью асимметричный тестовый шаблон (нет зеркальной/поворотной симметрии):
    - фон: R растёт слева направо, G сверху вниз, B — по диагонали от TL к BR;
    - сетка (каждая 4-я линия чёрная, отсчёт от TL);
    - 4 уникальных угловых маркера разной формы и цвета:
      TL красный квадрат, TR зелёный круг, BL синий треугольник, BR жёлтый ромб;
    - перекрестие в центре, стрелка вверх смещена влево от центра,
      номер фото смещён вправо-вниз, «якорная» точка-кольцо в (0.3w, 0.7h).
    Если передан meta (dict), в него пишутся координаты элементов в пикселях."""
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (int(230 * x / (w - 1)), int(230 * y / (h - 1)), int(255 * (1 - (x / w + y / h) / 2)))
    d = ImageDraw.Draw(im)
    step = max(25, min(w, h) // 12)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=(255, 255, 255) if x % (step * 4) else (0, 0, 0), width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=(255, 255, 255) if y % (step * 4) else (0, 0, 0), width=1)
    m = max(40, min(w, h) // 7)
    f = _font(m // 3)
    k = (0, 0, 0)
    # TL: красный квадрат
    d.rectangle([0, 0, m - 1, m - 1], fill=(255, 0, 0), outline=k, width=2)
    # TR: зелёный круг
    d.ellipse([w - m, 0, w - 1, m - 1], fill=(0, 200, 0), outline=k, width=2)
    # BL: синий треугольник (прямой угол в углу кадра)
    d.polygon([(0, h - m), (0, h - 1), (m - 1, h - 1)], fill=(0, 0, 255), outline=k)
    # BR: жёлтый ромб
    d.polygon([(w - m // 2, h - m), (w - 1, h - m // 2), (w - m // 2, h - 1), (w - m, h - m // 2)],
              fill=(255, 210, 0), outline=k)
    d.text((m // 2, m // 2), "TL", fill=(255, 255, 255), font=f, anchor="mm")
    d.text((w - m // 2, m // 2), "TR", fill=(255, 255, 255), font=f, anchor="mm")
    d.text((m // 4 + 2, h - m // 4 - 2), "BL", fill=(255, 255, 255), font=_font(m // 4), anchor="mm")
    d.text((w - m // 2, h - m // 2), "BR", fill=k, font=f, anchor="mm")
    cx, cy, r = w // 2, h // 2, min(w, h) // 10
    d.line([(cx - r, cy), (cx + r, cy)], fill=k, width=3)
    d.line([(cx, cy - r), (cx, cy + r)], fill=k, width=3)
    d.ellipse([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2], outline=k, width=2)
    ax, top, aw = int(w * 0.3), int(h * 0.15), r // 2  # стрелка вверх, смещена влево
    d.line([(ax, int(h * 0.4)), (ax, top + aw)], fill=k, width=5)
    d.polygon([(ax, top), (ax - aw, top + aw + 5), (ax + aw, top + aw + 5)], fill=k)
    d.text((ax + aw + 4, top), "UP", fill=k, font=f, anchor="lt")
    nx, ny = int(w * 0.68), int(h * 0.62)  # номер смещён вправо-вниз
    d.text((nx, ny), f"#{idx}", fill=(255, 255, 255), font=_font(m), anchor="mm", stroke_width=3, stroke_fill=k)
    d.text((nx, ny + m * 3 // 4), f"{w}x{h}", fill=k, font=f, anchor="mm")
    dx, dy, dr = int(w * 0.3), int(h * 0.7), max(6, m // 5)  # якорная точка
    d.ellipse([dx - dr, dy - dr, dx + dr, dy + dr], fill=(255, 0, 255), outline=k, width=2)
    if meta is not None:
        meta.update({
            "size": (w, h), "marker": m,
            "TL red square": (0, 0, m - 1, m - 1),
            "TR green circle": (w - m, 0, w - 1, m - 1),
            "BL blue triangle": (0, h - m, m - 1, h - 1),
            "BR yellow diamond": (w - m, h - m, w - 1, h - 1),
            "center crosshair": (cx, cy), "crosshair arm": r,
            "arrow UP tip": (ax, top), "arrow shaft x": ax,
            "index label center": (nx, ny),
            "magenta anchor dot center": (dx, dy), "anchor dot radius": dr,
        })
    return im


FIXTURES = [("portrait_300x400.png", 300, 400, 1), ("portrait_600x800.png", 600, 800, 2),
            ("landscape_400x300.png", 400, 300, 3)]


def _probe_points(meta):
    """Точки для markers.json: внутри фигур, вне подписей и контуров."""
    w, h = meta["size"]; m = meta["marker"]
    cx, cy = meta["center crosshair"]; dx, dy = meta["magenta anchor dot center"]
    return [("TL_red_square", 4, m - 6), ("TR_green_circle", w - m // 2, m - 8),
            ("BL_blue_triangle", 4, h - 6), ("BR_yellow_diamond", w - m // 2, h - m + 10),
            ("center_crosshair", cx, cy), ("magenta_anchor_dot", dx, dy),
            ("arrow_tip_black", meta["arrow UP tip"][0], meta["arrow UP tip"][1] + 4)]


def save_png_deterministic(im, path):
    """RGB, без альфы, без метаданных, compress_level=0 — побайтно детерминированно."""
    im = im.convert("RGB")
    im.info.clear()
    im.save(path, format="PNG", compress_level=0, optimize=False)


def make_fixtures(out: Path):
    """Фиксированный детерминированный набор для проверки photo_config (рендер-тесты — у Backend)."""
    out.mkdir(parents=True, exist_ok=True)
    markers = {}
    lines = ["# Фикстуры photo_config", "",
             "Генерация: `python testdata/make_testsets.py --fixtures`. PNG: режим RGB, без альфа-канала,",
             "без метаданных, `compress_level=0`; повторная генерация даёт побайтно идентичные файлы.",
             "Координаты в пикселях, (0,0) — левый верхний угол, bbox = (x0, y0, x1, y1) включительно.",
             "`markers.json` — точные пиксели {name, x, y, color:[r,g,b]} для автоматической проверки.",
             "Рендер-тесты и эталонные PNG — зона Backend (`/workspace/badge_generator/tests/`).", ""]
    for name, w, h, idx in FIXTURES:
        meta = {}
        im = pattern(w, h, idx, meta)
        save_png_deterministic(im, out / name)
        markers[name] = [{"name": n, "x": x, "y": y, "color": list(im.getpixel((x, y)))}
                         for n, x, y in _probe_points(meta)]
        lines += [f"## {name} — {w}×{h}, #{idx}", "", "| Элемент | Позиция |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in meta.items()]
        lines += ["", "Контрольные пиксели (markers.json):", ""]
        lines += [f"- {mk['name']}: ({mk['x']}, {mk['y']}) = {tuple(mk['color'])}" for mk in markers[name]] + [""]
    (out / "markers.json").write_text(json.dumps(markers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    return out


def img(p, idx=1, size=None):
    pattern(*(size or SIZES[(idx - 1) % len(SIZES)]), idx).save(p)


def person(i, photo):
    return [LN[i % 6] + (str(i) if i >= 6 else ""), FN[i % 6], "Иванович", "Инженер", "ИТ",
            photo, f"user{i}@example.com", f"+7 900 {i:03d}-00-00"[:17], "0;0;1.0;0;0;0"]


def write_csv(p, header, rows):
    with open(p.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


def write_xlsx(p, header, rows):
    wb = Workbook(); ws = wb.active; ws.append(header)
    for r in rows: ws.append(r)
    wb.save(p)


def make(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    # clean
    d = out / "clean"; (d / "photos").mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(5):
        img(d / "photos" / f"p{i+1}.jpg", i + 1); rows.append(person(i, f"p{i+1}.jpg"))
    write_csv(d / "persons.csv", H, rows)
    # zero_byte_and_broken
    d = out / "zero_byte_and_broken"; ph = d / "photos"; ph.mkdir(parents=True, exist_ok=True)
    img(ph / "IMG_2.JPG", 2); img(ph / "img_10.png", 10); img(ph / "img_1.webp", 1)
    (ph / "empty.jpg").write_bytes(b"")
    (ph / "broken.jpg").write_bytes(b"\xff\xd8\xff not really a jpeg")
    (ph / "notes.txt").write_text("x")
    write_csv(d / "persons.csv", H, [person(0, "IMG_2.JPG"), person(1, "empty.jpg"),
                                     person(2, "broken.jpg"), person(3, "missing.jpg")])
    # duplicates
    d = out / "duplicates"; d.mkdir(exist_ok=True)
    write_csv(d / "persons.csv", H, [person(0, ""), person(1, ""), person(0, ""),
                                     ["  иванов ", "Иван", "Иванович", "", "", "", "user0@example.com", "", ""]])
    # missing_fields / bad formats
    d = out / "missing_fields"; d.mkdir(exist_ok=True)
    write_csv(d / "persons.csv", H, [
        ["", "Иван", "", "", "", "", "", "", ""],
        ["Петров", "", "", "", "", "", "", "", ""],
        ["Сидоров", "Олег", "", "", "", "", "bad-email", "123", ""],
        ["Козлов", "Ян", "", "", "", "", "", "", "0;0;1.0;1.5;0;0"],
        ["Ок", "Норм", "", "", "", "", "ok@example.com", "+7 (900) 111-22-33", ""]])
    # messy headers: сырые данные для Backend (маппинг заголовков — зона Backend), нашими тестами не проверяется
    d = out / "messy_headers"; d.mkdir(exist_ok=True)
    write_xlsx(d / "persons_raw.xlsx", ["  ФИО ", "ДОЛЖНОСТЬ", "отдел", "E-mail", "Тел.", "Лишняя колонка"],
               [["Ёлкин  Пётр Сергеевич", "Директор", "Админ", "e@example.com", "89001112233", "x"],
                ["Смирнова Анна", "Бухгалтер", "Фин", "", "", ""]])
    # large: 5 базовых изображений (все размеры), строки ссылаются на них по кругу
    d = out / "large"; (d / "photos").mkdir(parents=True, exist_ok=True)
    base = [f"base_{k + 1}.jpg" for k in range(len(SIZES))]
    for k, name in enumerate(base):
        img(d / "photos" / name, k + 1)
    write_csv(d / "persons.csv", H, [person(i, base[i % len(base)]) for i in range(1000)])
    return out


if __name__ == "__main__":
    here = Path(__file__).parent
    args = [a for a in sys.argv[1:] if a != "--fixtures"]
    if "--fixtures" in sys.argv:
        print(make_fixtures(Path(args[0]) if args else here / "fixtures" / "photo_config"))
    else:
        print(make(Path(args[0]) if args else here / "sets"))
        print(make_fixtures(here / "fixtures" / "photo_config"))
