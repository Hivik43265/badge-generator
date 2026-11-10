"""Запись макетов Smart IDesigner: .csd (бинарный дизайн) и .csp (INI-проект).

Пишет тот формат, который читает badge_backend.services.smartid (parse_csd /
parse_csp / import_smartid). Геометрия — в единицах 0.1 мм, как после миграции v8.

Принимаемый template
--------------------
dict одного из двух видов (ключи можно смешивать):

1. Результат parse_csd(): objects, fields, background_png, card_w, card_h,
   printer, dpi, source.
2. Снимок шаблона из БД (строки template_elements / list_elements):
   {
     "elements" или "objects": [
       {type, x, y, w, h, side, field_name, static_value, text,
        style или style_json, font_family, font_size, color, align,
        png, filename, rotation, flags}
     ],
     "fields": [{"name", "value"}, ...],   # value попадает в текст ET и в CGFld,
                                           # чтобы импортёр заново привязал объект
     "background_png": bytes,
     "backgrounds": {"front": bytes|путь|{image_path}, "back": ...},
     "card_w": 856, "card_h": 538, "dpi": 300, "printer": str,
     "source": путь исходного .csd (защищён от перезаписи),
     "import_source_paths": [пути исходников «Открыть»],
   }

Координаты элементов — относительно стороны (как после parse_csd и как в БД).
Оборот записывается как y + 538 (высота лицевой стороны в образцах IDP).
Собрать dict из открытого соединения можно через template_from_con(con).

Что записывается
----------------
позиции (0.1 мм), сторона (сдвигом y), шрифт (имя и размер), цвет текста
(COLORREF), выравнивание (0x10/0x11/0x12), рамки ER, фон лицевой стороны (PNG
до первого объекта), фото (MI, привязанное к Photo/ФОТО), прочие картинки (MI),
таблица полей CGFld и значения для повторной привязки.

Что записать нельзя (честный список, в отчёт dropped, без молчаливой потери)
---------------------------------------------------------------------------
- начертание bold / italic / underline — в записи ET неизвестны смещения;
- смысл угла поворота: пишем int32 сразу после h, как читает импортёр, но в
  образцах это всегда 0, семантика (градусы или иное) не подтверждена;
- цвет и заливка рамки ER — импортёр всегда считает рамку чёрной, solid,
  без заливки; иное из style попадает в dropped;
- фон оборотной стороны — импортёр принимает за фон только PNG до первого
  объекта (лицевая сторона);
- объекты qr, barcode, line и прочие неизвестные типы — в .csd нет понятных
  тегов, записи пропускаются;
- неразобранные служебные байты оригинального Smart ID (длинный заголовок
  до фона, хвост после таблицы полей) — не воспроизводятся; нашему импортёру
  они не нужны.

Защита исходников
-----------------
write_csd / write_csp по умолчанию не перезаписывают существующий файл
(overwrite=False). Даже при overwrite=True отказывают, если путь совпадает
с исходником Smart ID: параметр import_source_paths (это
ProjectSession.import_source_paths после import_smartid_as_new_project),
либо template["import_source_paths"] / template["source"]. В таблице шаблонов
отдельного поля «путь исходника» нет.
"""
from __future__ import annotations

import json
import logging
import os
import struct
from pathlib import Path

from . import smartid

log = logging.getLogger(__name__)

FACE_H_UNITS = smartid.FACE_H_UNITS
FIELD_REC_SIZE = smartid.FIELD_REC_SIZE
PNG_MAGIC = smartid.PNG_MAGIC
DEFAULT_CARD_W = 856
DEFAULT_CARD_H = 538
DEFAULT_DPI = 300
ALIGN_CODES = {"left": 0x10, "center": 0x11, "right": 0x12}
WRITABLE_TYPES = {"text": "ET", "field": "ET", "photo": "MI", "image": "MI", "rect": "ER"}
TAG_TYPES = {"ET": "text", "MI": "image", "ER": "rect"}

# 1×1 RGB PNG — заглушка, если у MI нет пикселей.
_PLACEHOLDER_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63606060000000040001f61738550000000049454e44ae426082"
)


class SmartIdSourceProtectedError(PermissionError):
    """Нельзя перезаписать исходник Smart ID, открытый через «Открыть»."""


def _i32(n: int) -> bytes:
    return struct.pack("<i", int(n))


def _u16(n: int) -> bytes:
    return struct.pack("<H", int(n) & 0xFFFF)


def _utf16_payload(s: str) -> tuple[int, bytes]:
    raw = (s or "").encode("utf-16le")
    return len(raw) // 2, raw


def _same_path(a, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _as_path(p) -> Path | None:
    if p is None or p == "" or p == "<bytes>":
        return None
    return Path(p)


def _protected_paths(template, import_source_paths) -> list[Path]:
    out: list[Path] = []
    for raw in list(import_source_paths or []):
        q = _as_path(raw)
        if q is not None:
            out.append(q)
    if isinstance(template, dict):
        for raw in list(template.get("import_source_paths") or []):
            q = _as_path(raw)
            if q is not None:
                out.append(q)
        q = _as_path(template.get("source") or template.get("source_path"))
        if q is not None:
            out.append(q)
    return out


def _is_protected(path, template, import_source_paths) -> Path | None:
    dest = Path(path)
    for src in _protected_paths(template, import_source_paths):
        try:
            if _same_path(dest, src):
                return src.resolve() if src.exists() else src
        except OSError:
            if os.path.normcase(os.path.realpath(dest)) == os.path.normcase(os.path.realpath(src)):
                return src
    return None


def _check_target(path, *, overwrite: bool, template=None, import_source_paths=None) -> Path:
    dest = Path(path)
    blocked = _is_protected(dest, template, import_source_paths)
    if blocked is not None:
        raise SmartIdSourceProtectedError(
            f"нельзя перезаписать исходник Smart ID, открытый через «Открыть»: {blocked}"
        )
    if dest.exists() and not overwrite:
        raise FileExistsError(
            f"файл уже существует (передайте overwrite=True, если это не исходник Smart ID): {dest}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def _atomic_write(dest: Path, data: bytes) -> None:
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


def _parse_color(val) -> tuple[int, int, int] | None:
    if val is None or val == "":
        return None
    s = str(val).strip()
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3 and all(c in "0123456789abcdefABCDEF" for c in h):
            return tuple(int(c * 2, 16) for c in h)
        if len(h) >= 6 and all(c in "0123456789abcdefABCDEF" for c in h[:6]):
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return None


def _align_byte(val) -> int:
    if val is None or val == "":
        return 0x10
    if isinstance(val, str):
        key = val.strip().casefold()
        if key in ALIGN_CODES:
            return ALIGN_CODES[key]
        if key in ("0", "1", "2"):
            return 0x10 | (int(key) & 3)
    try:
        n = int(val)
        if n in (0x10, 0x11, 0x12, 0x01, 0x02, 0x00):
            return 0x10 | (n & 3)
        if 0 <= n <= 2:
            return 0x10 | n
    except (TypeError, ValueError):
        pass
    return 0x10


def _style_of(obj: dict) -> dict:
    raw = obj.get("style") if obj.get("style") is not None else obj.get("style_json")
    st = {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except (TypeError, ValueError):
            raw = {}
    if isinstance(raw, dict):
        st.update(raw)
    for k in ("font_family", "font_size", "color", "align", "rotation",
              "border_color", "filename", "flags"):
        if obj.get(k) is not None and st.get(k) is None:
            st[k] = obj[k]
    if obj.get("alignment") is not None and st.get("align") is None:
        st["align"] = obj["alignment"]
    return st


def _ensure_png(raw: bytes, dropped: list, label: str) -> bytes | None:
    if not raw:
        return None
    if raw.startswith(PNG_MAGIC):
        blob, _, end = smartid._extract_png(raw, 0)
        return blob if blob else raw
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(raw))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        dropped.append(f"{label}: исходник не PNG, записан как PNG")
        return buf.getvalue()
    except Exception as e:
        dropped.append(f"{label}: не удалось прочитать изображение ({e})")
        return None


def _load_png(src, base_dir, dropped: list, label: str) -> bytes | None:
    if src is None or src == "":
        return None
    if isinstance(src, dict):
        src = src.get("png") or src.get("data") or src.get("image_path")
        if src is None:
            return None
    if isinstance(src, (bytes, bytearray, memoryview)):
        return _ensure_png(bytes(src), dropped, label)
    p = Path(src)
    if not p.is_file() and base_dir:
        p = Path(base_dir) / src
    if not p.is_file():
        dropped.append(f"{label}: файл изображения не найден ({src})")
        return None
    return _ensure_png(p.read_bytes(), dropped, label)


def _objects_of(template: dict) -> list[dict]:
    objs = template.get("objects")
    if objs is None:
        objs = template.get("elements") or []
    return list(objs)


def _note_dropped_style(obj: dict, st: dict, dropped: list, label: str) -> None:
    for key, title in (("bold", "жирный"), ("italic", "курсив"), ("underline", "подчёркивание")):
        if st.get(key) or obj.get(key):
            dropped.append(f"{label}: начертание «{title}» не записывается — смещение в записи ET неизвестно")
    weight = st.get("font_weight") or obj.get("font_weight")
    if weight not in (None, "", "normal", "Normal", 400, "400"):
        dropped.append(f"{label}: font_weight={weight!r} не записывается")
    if st.get("font_style") in ("italic", "oblique") or obj.get("font_style") in ("italic", "oblique"):
        if not (st.get("italic") or obj.get("italic")):
            dropped.append(f"{label}: начертание «курсив» не записывается — смещение в записи ET неизвестно")


def _header(card_w, card_h, dpi, printer: str) -> bytes:
    buf = bytearray()
    buf += b"CSD\x00\x0d\x00\x00\x00\x00"
    buf += b"VER\x00\x10\x00\x00\x00\x01\x00\x1b\x00"
    buf += b"PRN\x00"
    buf += bytes.fromhex("94 62 00 00")  # как в образце IDP, смещение имени ~29
    n_units, raw = _utf16_payload(printer or "")
    buf += raw + b"\x00\x00"
    # размер карточки в образце стоит на смещении 109
    magic = bytes.fromhex("ff 80 05 02 00 96 00")
    if len(buf) < 102:
        buf += b"\x00" * (102 - len(buf))
        buf += magic
    else:
        buf += magic
    buf += _u16(card_w) + _u16(card_h) + _u16(100) + _u16(1) + _u16(15) + _u16(dpi)
    buf += b"\x00" * 16
    return bytes(buf)


def _build_et(obj: dict, st: dict, text: str, dropped: list, label: str) -> bytes:
    rec = bytearray(0xDD)
    rec[0:8] = bytes.fromhex("01 80 05 00 00 00") + b"ET"
    flags = int(obj.get("flags") or st.get("flags") or 0x01000000)
    x, y, w, h = (int(obj["x"]), int(obj["y"]), int(obj["w"]), int(obj["h"]))
    rot = int(obj.get("rotation") or st.get("rotation") or 0)
    rec[8:28] = _i32(flags) + _i32(x) + _i32(y) + _i32(w) + _i32(h)
    rec[28:32] = _i32(rot)
    rec[0x20:0x2C] = bytes.fromhex("ff 00 01 00 00 00 00 00 00 00 00 00")
    rgb = _parse_color(st.get("color") or obj.get("color")) or (0, 0, 0)
    rec[0x2C:0x30] = bytes(rgb) + b"\x00"
    rec[0x8B] = _align_byte(st.get("align") or obj.get("align") or obj.get("alignment"))
    size = st.get("font_size") if st.get("font_size") is not None else obj.get("font_size")
    if size is not None:
        rec[0x90:0x94] = _i32(int(size))
    rec[0x94:0x97] = bytes.fromhex("01 80 00")
    family = (st.get("font_family") or obj.get("font_family") or "").strip()
    if family:
        face = ("@" + family).encode("utf-16le")
        room = 0xDD - 0x97
        if len(face) > room:
            face = face[: room - (room % 2)]
            dropped.append(f"{label}: имя шрифта обрезано до {len(face) // 2} символов")
        rec[0x97:0x97 + len(face)] = face
        if not family.replace(" ", "").isascii():
            dropped.append(
                f"{label}: имя шрифта {family!r} не ASCII — наш импортёр его при чтении пропустит"
            )
    n, raw = _utf16_payload(text or "")
    rec += _i32(n) + raw
    _note_dropped_style(obj, st, dropped, label)
    return bytes(rec)


def _build_mi(obj: dict, st: dict, png: bytes | None, filename: str | None,
              dropped: list, label: str) -> bytes:
    rec = bytearray(195)
    rec[0:8] = bytes.fromhex("01 80 04 00 00 00") + b"MI"
    flags = int(obj.get("flags") or st.get("flags") or 0x01000000)
    rec[8:28] = (_i32(flags) + _i32(int(obj["x"])) + _i32(int(obj["y"]))
                 + _i32(int(obj["w"])) + _i32(int(obj["h"])))
    rec[28:32] = _i32(int(obj.get("rotation") or st.get("rotation") or 0))
    rec[0x20:0x2C] = bytes.fromhex("ff 00 01 00 00 00 00 00 00 00 00 00")
    name = filename or obj.get("filename") or st.get("filename") or "image.png"
    n, raw = _utf16_payload(name)
    rec += _i32(n) + raw
    blob = png or _PLACEHOLDER_PNG
    if png is None:
        dropped.append(f"{label}: нет пикселей изображения, записана заглушка 1×1 PNG")
    rec += _i32(len(blob)) + blob
    return bytes(rec)


def _build_er(obj: dict, st: dict, dropped: list, label: str) -> bytes:
    rec = bytearray(131)
    rec[0:8] = bytes.fromhex("01 80 00 00 00 00") + b"ER"
    flags = int(obj.get("flags") or st.get("flags") or 0x01000000)
    rec[8:28] = (_i32(flags) + _i32(int(obj["x"])) + _i32(int(obj["y"]))
                 + _i32(int(obj["w"])) + _i32(int(obj["h"])))
    rec[32:40] = bytes.fromhex("00 00 01 00 00 00 00 00")
    rec[40:44] = bytes.fromhex("01 00 00 00")
    color = st.get("border_color") or st.get("stroke") or obj.get("border_color")
    parsed = _parse_color(color) if color else None
    if parsed is not None and parsed != (0, 0, 0):
        dropped.append(
            f"{label}: цвет рамки {color!r} не записывается — импортёр всегда читает ER как чёрную solid без заливки"
        )
    if st.get("bg_fill") or st.get("fill") or obj.get("bg_fill"):
        dropped.append(f"{label}: заливка прямоугольника не записывается")
    bw = st.get("border_width") or st.get("stroke_width")
    if bw not in (None, "", 1, 1.0, "1"):
        dropped.append(f"{label}: толщина рамки {bw!r} не записывается")
    return bytes(rec)


def _build_fields_table(pairs: list[tuple[str, str]]) -> bytes:
    if not pairs:
        return b""
    out = bytearray()
    out += _u16(len(pairs)) + bytes.fromhex("ff ff 00 00 05 00")
    for i, (name, value) in enumerate(pairs):
        rec = bytearray(FIELD_REC_SIZE)
        if i == 0:
            rec[0:5] = b"CGFld"
        else:
            rec[3] = 0x0E
            rec[4] = 0x80
            rec[5] = i & 0xFF
        n_name, raw_name = _utf16_payload(name)
        rec[9:9 + min(len(raw_name), 62)] = raw_name[:62]
        n_val, raw_val = _utf16_payload(value)
        max_val = FIELD_REC_SIZE - 77
        raw_val = raw_val[: max_val - (max_val % 2)]
        n_val = len(raw_val) // 2
        rec[73:77] = _i32(n_val)
        rec[77:77 + len(raw_val)] = raw_val
        out += rec
    return bytes(out)


def _field_pairs(template: dict, used: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen = {}
    for item in template.get("fields") or []:
        if isinstance(item, dict):
            name = (item.get("name") or "").strip()
            if not name:
                continue
            val = item.get("value")
            if val is None:
                val = name
            seen[name] = str(val)
    for name, val in used:
        if name and name not in seen:
            seen[name] = val if val is not None else name
    return list(seen.items())


def _classify(obj: dict) -> str | None:
    typ = (obj.get("type") or "").strip().casefold()
    if typ:
        return typ
    tag = (obj.get("tag") or "").strip().upper()
    if tag == "ET":
        return "field" if obj.get("field_name") else "text"
    if tag == "MI":
        return "photo" if smartid._is_photo_field(obj.get("field_name")) else "image"
    if tag == "ER":
        return "rect"
    return None


def _csd_xy(obj: dict) -> tuple[int, int, int, int]:
    x, y, w, h = int(obj["x"]), int(obj["y"]), int(obj["w"]), int(obj["h"])
    side = (obj.get("side") or "front").casefold()
    if side in ("back", "rear"):
        y = y + FACE_H_UNITS
    return x, y, w, h


def build_csd_bytes(template: dict, *, base_dir=None) -> tuple[bytes, list[str]]:
    """Собрать байты .csd и список неучтённых свойств. Файл не пишет."""
    if not isinstance(template, dict):
        raise TypeError("template должен быть dict (результат parse_csd или снимок элементов)")
    dropped: list[str] = []
    card_w = int(template.get("card_w") or DEFAULT_CARD_W)
    card_h = int(template.get("card_h") or DEFAULT_CARD_H)
    dpi = int(template.get("dpi") or DEFAULT_DPI)
    printer = template.get("printer") or ""
    parts = [_header(card_w, card_h, dpi, printer)]

    bg = template.get("background_png")
    if bg is None:
        bgs = template.get("backgrounds") or {}
        bg = bgs.get("front") if isinstance(bgs, dict) else None
    bg_png = _load_png(bg, base_dir, dropped, "фон лицевой стороны")
    bgs = template.get("backgrounds") or {}
    if isinstance(bgs, dict) and bgs.get("back"):
        dropped.append(
            "фон оборотной стороны не записывается: импортёр принимает за фон только PNG до первого объекта"
        )
    if bg_png:
        parts.append(bg_png)

    used_fields: list[tuple[str, str]] = []
    for idx, raw in enumerate(_objects_of(template)):
        obj = dict(raw)
        st = _style_of(obj)
        typ = _classify(obj)
        label = f"элемент[{idx}] type={typ or obj.get('tag')!r}"
        if typ not in WRITABLE_TYPES:
            dropped.append(
                f"{label}: тип не записывается в .csd (поддерживаются text, field, photo, image, rect)"
            )
            continue
        x, y, w, h = _csd_xy(obj)
        rec_obj = {**obj, "x": x, "y": y, "w": max(1, w), "h": max(1, h)}
        if typ in ("text", "field"):
            text = obj.get("text")
            if text is None:
                text = obj.get("static_value") if typ == "text" else None
            fname = obj.get("field_name") or None
            if typ == "field" and fname:
                if text is None or text == "":
                    text = _field_value_for(template, fname) or fname
                used_fields.append((fname, str(text)))
            parts.append(_build_et(rec_obj, st, "" if text is None else str(text), dropped, label))
        elif typ in ("photo", "image"):
            png = obj.get("png")
            if isinstance(png, (bytes, bytearray, memoryview)):
                png = _ensure_png(bytes(png), dropped, label)
            else:
                png = _load_png(png or obj.get("static_value"), base_dir, dropped, label)
            filename = obj.get("filename")
            fname = obj.get("field_name") or None
            if typ == "photo":
                if not fname:
                    fname = "Photo"
                    rec_obj["field_name"] = fname
                if not filename:
                    filename = Path(str(_field_value_for(template, fname) or "photo.png")).name
                    if not filename:
                        filename = "photo.png"
                used_fields.append((fname, filename))
            elif fname:
                if not filename:
                    filename = Path(str(_field_value_for(template, fname) or "image.png")).name
                used_fields.append((fname, filename))
            if not filename:
                sv = obj.get("static_value")
                if isinstance(sv, str) and sv:
                    filename = Path(sv).name
            parts.append(_build_mi(rec_obj, st, png, filename, dropped, label))
        else:
            parts.append(_build_er(rec_obj, st, dropped, label))

    parts.append(_build_fields_table(_field_pairs(template, used_fields)))
    return b"".join(parts), dropped


def _field_value_for(template: dict, name: str) -> str | None:
    want = (name or "").casefold()
    for item in template.get("fields") or []:
        if isinstance(item, dict) and (item.get("name") or "").casefold() == want:
            val = item.get("value")
            return None if val is None else str(val)
    return None


def write_csd(template, path, *, overwrite: bool = False, import_source_paths=None,
              base_dir=None) -> dict:
    """Записать .csd. Возвращает {"path": Path, "dropped": [str, ...]}.

    overwrite=False (по умолчанию) — не трогать существующий файл.
    overwrite=True разрешает заменить файл, но не исходник Smart ID
    (см. import_source_paths и template["source"] в docstring модуля).
    """
    dest = _check_target(path, overwrite=overwrite, template=template,
                         import_source_paths=import_source_paths)
    if base_dir is None and isinstance(template, dict):
        base_dir = template.get("base_dir")
    data, dropped = build_csd_bytes(template, base_dir=base_dir)
    if not data.startswith(b"CSD"):
        raise ValueError("внутренняя ошибка: собранный файл не начинается с сигнатуры CSD")
    _atomic_write(dest, data)
    for item in dropped:
        log.warning("write_csd: %s", item)
    return {"path": dest, "dropped": dropped}


def _rel_parts(target: Path, origin: Path) -> tuple[str, str]:
    """Каталог и имя файла target относительно origin (как у Smart ID)."""
    try:
        rel = Path(os.path.relpath(target.resolve(), start=origin.resolve()))
    except ValueError:
        rel = target.resolve()
    if rel.parent == Path("."):
        return ".", rel.name
    return rel.parent.as_posix(), rel.name


def write_csp(path, csd_path, db_path, *, overwrite: bool = False,
              import_source_paths=None, table_name: str = "persons",
              csd_fields=None, tbl_fields=None, template=None) -> dict:
    """Записать .csp (INI). Пути к .csd и .db — относительные от каталога .csp.

    [DB] CSD_Name, SQLiteDBPath, SQLiteDBName, TableName
    [BIND] CSD_Fields, TBL_Fields  (через |, как у Smart ID)

    Защита исходников — как у write_csd. Возвращает
    {"path": Path, "dropped": list, "csd_name", "sqlite_db_path", "sqlite_db_name"}.
    """
    dest = _check_target(path, overwrite=overwrite, template=template,
                         import_source_paths=import_source_paths)
    origin = dest.parent
    csd = Path(csd_path)
    dbp = Path(db_path)
    csd_dir, csd_name = _rel_parts(csd, origin)
    csd_rel = csd_name if csd_dir in (".", "") else f"{csd_dir}/{csd_name}"
    db_dir, db_name = _rel_parts(dbp, origin)
    fields_a = [str(x).strip() for x in (csd_fields or []) if str(x).strip()]
    fields_b = [str(x).strip() for x in (tbl_fields or []) if str(x).strip()]
    dropped = []
    if fields_a and fields_b and len(fields_a) != len(fields_b):
        dropped.append(
            f"CSD_Fields ({len(fields_a)}) и TBL_Fields ({len(fields_b)}) разной длины — записываю как есть"
        )
    lines = [
        "[DB]",
        f"CSD_Name={csd_rel}",
        f"SQLiteDBPath={db_dir}",
        f"SQLiteDBName={db_name}",
        f"TableName={table_name or 'persons'}",
        "",
        "[BIND]",
        "CSD_Fields=" + "|".join(fields_a),
        "TBL_Fields=" + "|".join(fields_b),
        "",
    ]
    text = "\n".join(lines)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(text, encoding="utf-8-sig")
    os.replace(tmp, dest)
    for item in dropped:
        log.warning("write_csp: %s", item)
    return {
        "path": dest,
        "dropped": dropped,
        "csd_name": csd_rel,
        "sqlite_db_path": db_dir,
        "sqlite_db_name": db_name,
    }


def template_from_con(con, *, template_id: int | None = None, base_dir=None,
                      printer: str = "", source=None, import_source_paths=None) -> dict:
    """Снимок активного (или указанного) шаблона из БД для write_csd.

    Элементы — как в template_elements. У привязанных полей value в таблице
    CGFld будет равно имени поля (после импорта исходный образец текста в БД
    не хранится). Картинки подхватываются из static_value / image_path
    относительно base_dir.
    """
    from .. import db as _db
    from .photos import project_base_dir

    tid = template_id or _db.active_template_id(con)
    base = base_dir if base_dir is not None else project_base_dir(con)
    elements = []
    q = ("SELECT type, x, y, w, h, field_name, static_value, style_json, side, z_order "
         "FROM template_elements WHERE template_id=? ORDER BY side, z_order, id")
    for r in con.execute(q, (tid,)):
        style = {}
        try:
            style = json.loads(r[7] or "{}")
        except (TypeError, ValueError):
            style = {}
        elements.append({
            "type": r[0], "x": r[1], "y": r[2], "w": r[3], "h": r[4],
            "field_name": r[5], "static_value": r[6], "style": style,
            "side": r[8] or "front", "z_order": r[9],
        })
    backgrounds = {}
    for r in con.execute(
        "SELECT side, image_path, color FROM template_backgrounds2 WHERE template_id=?",
        (tid,),
    ):
        backgrounds[r[0]] = {"image_path": r[1], "color": r[2]}
    fields = []
    for r in con.execute("SELECT name FROM person_fields ORDER BY sort_order, name"):
        fields.append({"name": r[0], "value": r[0]})
    return {
        "elements": elements,
        "fields": fields,
        "backgrounds": backgrounds,
        "card_w": DEFAULT_CARD_W,
        "card_h": DEFAULT_CARD_H,
        "dpi": DEFAULT_DPI,
        "printer": printer or "",
        "source": source,
        "import_source_paths": list(import_source_paths or []),
        "base_dir": str(base) if base else None,
    }


__all__ = [
    "SmartIdSourceProtectedError",
    "write_csd",
    "write_csp",
    "template_from_con",
    "build_csd_bytes",
]
