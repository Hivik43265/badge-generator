"""Импорт макетов Smart IDesigner: .csd (бинарный дизайн карточки) и .csp (INI-проект).

Геометрия .csd хранится в единицах 0.1 мм. Перевод в текущие единицы хранения
шаблона (пиксели холста 300 DPI) — только через _to_storage_units.
"""
from __future__ import annotations

import configparser
import json
import struct
from pathlib import Path

from .. import db as _db
from ..db import now_iso
from .project_session import TemplateEditActiveError
from .photos import project_base_dir
from .template_file import EL_COLS, _store_bytes, _unique_name, _verify_image
from .templates import get_template_edit_state, _name as _tpl_name

STORAGE_DPI = 300
CSD_UNITS_PER_INCH = 254  # 25.4 мм × 10
PHOTO_FIELD_NAMES = frozenset({"photo", "фото"})
KNOWN_TAGS = {"ET", "MI", "ER"}
REC_MARKER = b"\x01\x80"
FACE_H_UNITS = 538  # высота лицевой стороны в образцах IDP; y >= 538 → оборот (догадка)
FIELD_REC_SIZE = 2122
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _to_storage_units(v) -> int:
    """Единицы .csd (0.1 мм) → единицы хранения шаблона.

    После миграции v8 сетка хранения совпадает с .csd — функция тождественная.
    """
    return int(v)


def _is_photo_field(name) -> bool:
    return (name or "").casefold() in PHOTO_FIELD_NAMES


def _clean_u16(s: str | None) -> str:
    """Убрать NUL и крайние пробелы из UTF-16 строки (кириллица сохраняется)."""
    if not s:
        return ""
    return str(s).replace("\x00", "").strip()


def _utf16z(data: bytes, off: int, max_chars: int = 64) -> str:
    if off < 0 or off >= len(data):
        return ""
    chars = []
    i = 0
    while i < max_chars:
        p = off + i * 2
        if p + 2 > len(data):
            break
        ch = struct.unpack_from("<H", data, p)[0]
        if ch == 0:
            break
        if 0xD800 <= ch <= 0xDBFF and p + 4 <= len(data):
            ch2 = struct.unpack_from("<H", data, p + 2)[0]
            if 0xDC00 <= ch2 <= 0xDFFF:
                chars.append(chr(0x10000 + ((ch - 0xD800) << 10) + (ch2 - 0xDC00)))
                i += 2
                continue
        if 0xD800 <= ch <= 0xDFFF:
            i += 1
            continue
        try:
            chars.append(chr(ch))
        except ValueError:
            break
        i += 1
    return _clean_u16("".join(chars))


def _i32_at(data: bytes, off: int, default=None):
    if off < 0 or off + 4 > len(data):
        return default
    return struct.unpack_from("<i", data, off)[0]


def _u16_at(data: bytes, off: int, default=None):
    if off < 0 or off + 2 > len(data):
        return default
    return struct.unpack_from("<H", data, off)[0]


def _extract_png(data: bytes, start: int = 0) -> tuple[bytes | None, int, int]:
    j = data.find(PNG_MAGIC, start)
    if j < 0:
        return None, -1, -1
    iend = data.find(b"IEND", j)
    if iend < 0:
        return None, j, -1
    end = iend + 8
    return data[j:end], j, end


def _read_card_size(data: bytes) -> tuple[int, int, int | None]:
    """Ширина и высота карточки в единицах 0.1 мм. В образце IDP: 856×538."""
    limit = min(len(data) - 4, 512)
    # шаг 1: в образце IDP пара 856×538 стоит на нечётном смещении 109
    for off in range(0, limit):
        w, h = struct.unpack_from("<HH", data, off)
        if w in (854, 855, 856, 857) and h in (538, 539, 540):
            return w, h, off
    return 856, 538, None


def _read_dpi(data: bytes, size_off: int | None) -> int:
    if size_off is not None:
        for extra in (10, 8, 12, 6, 14, 4):
            v = _u16_at(data, size_off + 4 + extra)
            if v in (200, 300, 600):
                return v
        chunk = data[size_off:size_off + 24]
        for i in range(0, max(0, len(chunk) - 1), 2):
            v = struct.unpack_from("<H", chunk, i)[0]
            if v in (200, 300, 600) and i >= 4:
                return v
    return STORAGE_DPI


def _read_printer(data: bytes) -> str:
    j = data.find(b"PRN\x00")
    if j < 0:
        return ""
    # после PRN\0 обычно несколько служебных байт, затем UTF-16 имя
    region = data[j + 4:j + 200]
    # ищем начало печатной UTF-16 строки
    for off in range(0, min(12, len(region) - 4), 2):
        s = _utf16z(region, off, 64)
        if len(s) >= 3 and any(c.isalpha() for c in s):
            return s
    s = _utf16z(region, 4, 64)
    return s


def _scan_objects(data: bytes) -> list[int]:
    hits = []
    i = 0
    n = len(data)
    while True:
        j = data.find(REC_MARKER, i)
        if j < 0:
            break
        if j + 8 <= n and data[j + 3:j + 6] == b"\x00\x00\x00":
            tag = data[j + 6:j + 8]
            if len(tag) == 2 and tag.isalpha() and tag.isupper():
                hits.append(j)
        i = j + 1
    return hits


def _parse_style_and_text(blob: bytes) -> dict:
    out = {"font_family": None, "font_size": None, "color": None, "align": None, "text": None,
           "style_notes": []}
    if len(blob) < 0x30:
        return out
    col = blob[0x2C:0x2F]
    if len(col) == 3:
        out["color"] = f"#{col[0]:02X}{col[1]:02X}{col[2]:02X}"
        out["style_notes"].append("color: Windows COLORREF (R,G,B в байтах 0x2C)")
    align_code = None
    for off in (0x8B, 0x8A):
        if off < len(blob) and blob[off] in (0x01, 0x02, 0x10, 0x11, 0x12):
            align_code = blob[off]
            break
    if align_code is not None:
        out["align"] = {0: "left", 1: "center", 2: "right"}[align_code & 3]
        out["style_notes"].append("align: байт 0x8B (запасной 0x8A), как DT_LEFT/CENTER/RIGHT")
    if len(blob) >= 0x94:
        size = _i32_at(blob, 0x90)
        if size is not None and 1 <= size <= 200:
            out["font_size"] = size
    if len(blob) >= 0x96:
        best = None
        for off in range(0x94, min(len(blob) - 4, 0xA4)):
            raw = _utf16z(blob, off, 32)
            fam = raw.lstrip("@").strip()
            if not fam or not ("A" <= fam[0] <= "Z" or "a" <= fam[0] <= "z"):
                continue
            if not fam.replace(" ", "").isascii():
                continue
            score = sum(c.isalpha() for c in fam)
            if score >= 2 and (best is None or score > best[0]):
                best = (score, fam)
        if best:
            out["font_family"] = best[1]
    if len(blob) >= 0xDD + 4:
        n = _i32_at(blob, 0xDD)
        if n is not None and 0 < n <= 500 and 0xDD + 4 + n * 2 <= len(blob):
            try:
                out["text"] = blob[0xE1:0xE1 + n * 2].decode("utf-16le")
            except UnicodeDecodeError:
                out["text"] = None
    if out["text"] is None:
        # запасной поиск: int32 длина + печатная UTF-16 ближе к концу заголовка
        for off in range(0xC0, min(len(blob) - 6, 0x200)):
            n = _i32_at(blob, off)
            if n is None or not (1 <= n <= 200):
                continue
            raw = blob[off + 4:off + 4 + n * 2]
            if len(raw) != n * 2:
                continue
            try:
                s = raw.decode("utf-16le")
            except UnicodeDecodeError:
                continue
            if s.isprintable() and any(c.isalnum() for c in s):
                out["text"] = s
                break
    return out


def _find_filename(blob: bytes) -> str | None:
    for off in range(0, min(len(blob) - 6, 400)):
        n = _i32_at(blob, off)
        if n is None or not (3 <= n <= 240):
            continue
        raw = blob[off + 4:off + 4 + n * 2]
        if len(raw) != n * 2:
            continue
        try:
            s = raw.decode("utf-16le")
        except UnicodeDecodeError:
            continue
        if not s.isprintable() or "\x00" in s:
            continue
        low = s.casefold()
        if any(low.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff")):
            return _clean_u16(s)
    return None


def _parse_fields(data: bytes) -> list[dict]:
    j = data.find(b"CGFld")
    if j < 0:
        return []
    count = _u16_at(data, j - 8)
    if not count or count < 1 or count > 256:
        count = 1
        # посчитаем подряд идущие записи, пока имя похоже на идентификатор
        while True:
            off = j + count * FIELD_REC_SIZE
            if off + 80 > len(data):
                break
            name = _utf16z(data, off + 9, 32)
            if not name or not any(c.isalnum() for c in name):
                break
            count += 1
    out = []
    for i in range(count):
        off = j + i * FIELD_REC_SIZE
        if off + 80 > len(data):
            break
        name = _clean_u16(_utf16z(data, off + 9, 32))
        if not name or not any(c.isalnum() for c in name):
            continue
        n = _i32_at(data, off + 73, 0) or 0
        val = ""
        if 0 < n <= 1000 and off + 77 + n * 2 <= len(data):
            try:
                val = _clean_u16(data[off + 77:off + 77 + n * 2].decode("utf-16le"))
            except UnicodeDecodeError:
                val = ""
        out.append({"name": name, "value": val})
    return out


def _match_field(text: str | None, filename: str | None, fields: list[dict]) -> str | None:
    if text:
        key = text.strip()
        for f in fields:
            if (f.get("value") or "").strip() == key:
                return f["name"]
    if filename:
        fn = filename.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        for f in fields:
            val = (f.get("value") or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()
            if val and val == fn:
                return f["name"]
    return None


def _side_of(x, y, w, h, card_w, card_h, guessed: list) -> tuple[str, int, int]:
    # Порог 538 — высота лицевой стороны в .csd IDP; наш холст 856×540, координаты не подгоняем.
    if y >= FACE_H_UNITS:
        note = "объект с y ≥ 538 отнесён на оборот (y уменьшен на 538) — догадка, явного флага стороны нет"
        if note not in guessed:
            guessed.append(note)
        return "back", x, y - FACE_H_UNITS
    return "front", x, y


def parse_csd(src) -> dict:
    """Разобрать .csd в промежуточную структуру (геометрия — в 0.1 мм). Не падает на неизвестных записях."""
    if isinstance(src, (bytes, bytearray, memoryview)):
        data = bytes(src)
        source = "<bytes>"
    else:
        p = Path(src)
        if not p.is_file():
            raise FileNotFoundError(p)
        data = p.read_bytes()
        source = str(p)
    if not data.startswith(b"CSD"):
        raise ValueError("файл не является .csd (нет сигнатуры CSD)")

    guessed, skipped, warnings = [], [], []
    card_w, card_h, size_off = _read_card_size(data)
    if size_off is None:
        warnings.append("размер карточки в заголовке не найден, принят 856×538 (0.1 мм)")
        guessed.append("размер карточки по умолчанию 856×538")
    dpi = _read_dpi(data, size_off)
    printer = _read_printer(data)

    fields = _parse_fields(data)
    starts = _scan_objects(data)
    ends = starts[1:] + [len(data)]

    # фоновый PNG — до первого объекта
    background_png = None
    first_obj = starts[0] if starts else len(data)
    pos = 0
    while pos < first_obj:
        blob, j, end = _extract_png(data, pos)
        if blob is None or j < 0 or j >= first_obj:
            break
        background_png = blob
        pos = end if end > j else j + 1
    if background_png:
        note_bg = "встроенный PNG до первого объекта принят за фон лицевой стороны — догадка"
        if note_bg not in guessed:
            guessed.append(note_bg)

    objects = []
    for start, end in zip(starts, ends):
        try:
            blob = data[start:end]
            if len(blob) < 28:
                skipped.append({"offset": start, "reason": "слишком короткая запись"})
                continue
            tag = blob[6:8].decode("ascii", errors="replace")
            flags, x, y, w, h = struct.unpack_from("<iiiii", blob, 8)
            rotation = _i32_at(blob, 28, 0) or 0
            rec = {"tag": tag, "flags": flags, "x": x, "y": y, "w": w, "h": h,
                   "offset": start, "text": None, "font_family": None, "font_size": None,
                   "color": None, "align": None, "png": None, "filename": None,
                   "field_name": None, "type": None, "side": "front",
                   "rotation": rotation, "border_color": None}
            note_rot = "угол: int32 сразу после h, в градусах (в образце IDP все 0) — догадка"
            if note_rot not in guessed:
                guessed.append(note_rot)
            if tag == "ET":
                st = _parse_style_and_text(blob)
                rec.update({k: st[k] for k in ("text", "font_family", "font_size", "color", "align")})
                rec["text"] = _clean_u16(rec.get("text"))
                rec["field_name"] = _match_field(rec["text"], None, fields)
                rec["type"] = "field" if rec["field_name"] else "text"
                for n in st.get("style_notes") or []:
                    if n not in guessed:
                        guessed.append(n)
            elif tag == "MI":
                rec["filename"] = _clean_u16(_find_filename(blob) or "") or None
                png, _, _ = _extract_png(blob, 0)
                rec["png"] = png
                rec["field_name"] = _match_field(None, rec["filename"], fields)
                rec["type"] = "photo" if _is_photo_field(rec["field_name"]) else "image"
            elif tag == "ER":
                rec["type"] = "rect"
                rec["border_color"] = "#000000"
                note_er = "ER → rect, рамка solid без заливки, цвет чёрный (стиль угадан)"
                if note_er not in guessed:
                    guessed.append(note_er)
            else:
                rec["type"] = None
                skipped.append({"tag": tag, "x": x, "y": y, "w": w, "h": h,
                                "reason": "неизвестный тип объекта, пропущен"})
                continue
            side, sx, sy = _side_of(x, y, w, h, card_w, card_h, guessed)
            rec["side"], rec["x"], rec["y"] = side, sx, sy
            objects.append(rec)
        except Exception as e:
            skipped.append({"offset": start, "reason": f"запись не разобрана: {e}"})

    return {
        "source": source,
        "printer": printer,
        "card_w": card_w,
        "card_h": card_h,
        "dpi": dpi,
        "fields": fields,
        "objects": objects,
        "background_png": background_png,
        "skipped": skipped,
        "guessed": guessed,
        "warnings": warnings,
    }


def _read_ini(path: Path) -> configparser.ConfigParser:
    raw = path.read_bytes()
    text = None
    last_err = None
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "cp1251", "utf-8"):
        try:
            cand = raw.decode(enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
        if "[" not in cand and "=" not in cand:
            continue
        text = cand
        break
    if text is None:
        raise ValueError(f"не удалось прочитать .csp ({path.name}): {last_err}")
    cfg = configparser.ConfigParser(interpolation=None)
    try:
        cfg.read_string(text)
    except configparser.Error as e:
        raise ValueError(f"некорректный INI в .csp: {e}") from e
    return cfg


def _ini_get(cfg: configparser.ConfigParser, key: str, default: str | None = None) -> str | None:
    want = key.casefold()
    for sec in cfg.sections():
        for k, v in cfg.items(sec):
            if k.casefold() == want:
                return v
    for k, v in cfg.defaults().items():
        if k.casefold() == want:
            return v
    return default


def parse_csp(path) -> dict:
    """Прочитать .csp (INI) и вернуть пути/привязки. Кодировки: utf-8-sig, utf-16, cp1251."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    cfg = _read_ini(p)
    csd_name = _ini_get(cfg, "CSD_Name")
    db_path = _ini_get(cfg, "SQLiteDBPath")
    db_name = _ini_get(cfg, "SQLiteDBName")
    table = _ini_get(cfg, "TableName")
    csd_fields = [x.strip() for x in (_ini_get(cfg, "CSD_Fields") or "").split("|") if x.strip()]
    tbl_fields = [x.strip() for x in (_ini_get(cfg, "TBL_Fields") or "").split("|") if x.strip()]
    return {
        "path": p,
        "csd_name": csd_name,
        "sqlite_db_path": db_path,
        "sqlite_db_name": db_name,
        "table_name": table,
        "csd_fields": csd_fields,
        "tbl_fields": tbl_fields,
    }


def _resolve_next_to(base: Path, *parts) -> list[Path]:
    out = []
    for part in parts:
        if not part:
            continue
        q = Path(part)
        out.append(q if q.is_absolute() else base / q)
    return out


def _unique_search_paths(cands) -> list[str]:
    seen, out = set(), []
    for c in cands:
        if not c:
            continue
        s = str(Path(c))
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _missing_sidecar_error(kind: str, project_name: str, hint: str, cands) -> FileNotFoundError:
    listed = _unique_search_paths(cands)
    paths = "\n".join(f"  {x}" for x in listed) or "  (пути не заданы в проекте)"
    if kind == "csd":
        head = f"Не найден файл макета (.csd) для проекта {project_name}."
    else:
        head = f"Не найдена база данных записей для проекта {project_name}."
    extra = f"{hint}\n" if hint else ""
    return FileNotFoundError(f"{head}\n{extra}Искали по путям:\n{paths}")


def resolve_csp_csd(info: dict) -> Path:
    p = info["path"]
    name = info.get("csd_name")
    cands = _resolve_next_to(p.parent, name)
    if name:
        cands.append(p.parent / Path(name).name)
    cands.append(p.with_suffix(".csd"))
    for c in cands:
        if c and c.is_file():
            return c
    hint = f"В проекте указано CSD_Name={name!r}."
    raise _missing_sidecar_error("csd", p.name, hint, cands)


def resolve_csp_db(info: dict) -> Path:
    p = info["path"]
    d, n = info.get("sqlite_db_path"), info.get("sqlite_db_name")
    cands = []
    if d and n:
        cands.append(Path(d) / n)
        cands.append(p.parent / d / n)
    if n:
        cands.append(Path(n))
        cands.append(p.parent / n)
    if d:
        pd = Path(d)
        cands.append(pd)
        cands.append(p.parent / pd)
    for c in cands:
        if c and c.is_file():
            return c
    hint = f"В проекте указано SQLiteDBPath={d!r}, SQLiteDBName={n!r}."
    raise _missing_sidecar_error("db", p.name, hint, cands)


def _style_of(obj: dict) -> dict:
    st = {}
    if obj.get("font_family"):
        st["font_family"] = obj["font_family"]
    if obj.get("font_size") is not None:
        st["font_size"] = obj["font_size"]
    if obj.get("color"):
        st["color"] = obj["color"]
    if obj.get("align"):
        st["align"] = obj["align"]
    rot = obj.get("rotation") or 0
    if rot:
        st["rotation"] = rot
    if obj.get("type") == "rect" or obj.get("tag") == "ER":
        color = obj.get("border_color") or "#000000"
        st["border_style"] = "solid"
        st["border_width"] = 1
        st["border_color"] = color
        st["bg_fill"] = False
        st["stroke"] = color
        st["stroke_width"] = 1
    return st


def _ensure_fields(con, names: list[str]) -> list[str]:
    """Создать отсутствующие поля, иначе D24 проглотит колонки, а import_template отвяжет объекты."""
    have = {r[0].casefold(): r[0] for r in con.execute("SELECT name FROM person_fields")}
    so = con.execute("SELECT COALESCE(MAX(sort_order), -1) FROM person_fields").fetchone()[0]
    created = []
    for name in names:
        if not name or name.casefold() in have:
            continue
        so += 1
        dt = "image" if _is_photo_field(name) else "text"
        con.execute(
            "INSERT INTO person_fields(name, label, sort_order, data_type) VALUES (?,?,?,?)",
            (name, name, so, dt))
        have[name.casefold()] = name
        created.append(name)
    return created


def apply_parsed_csd(con, parsed: dict, *, name: str, report: dict) -> int:
    """Полностью заменить активный шаблон содержимым разобранного .csd (как import_template)."""
    if get_template_edit_state(con) is not None:
        raise TemplateEditActiveError("нельзя импортировать шаблон во время правки макета")
    tid = _db.active_template_id(con)
    final_name = _unique_name(con, name, tid)
    bound = [o.get("field_name") for o in parsed["objects"] if o.get("field_name")]
    bound += [f["name"] for f in parsed.get("fields") or []]
    base = project_base_dir(con)
    now = now_iso()
    imported = []
    with con:
        created = _ensure_fields(con, bound)
        report["created_fields"] = list(created)
        fields = {r[0] for r in con.execute("SELECT name FROM person_fields")}
        con.execute("UPDATE templates SET name=?, updated_at=? WHERE id=?",
                    (final_name, now, tid))
        con.execute("DELETE FROM template_elements WHERE template_id=?", (tid,))
        con.execute("DELETE FROM template_backgrounds2 WHERE template_id=?", (tid,))
        bg_path = None
        if parsed.get("background_png"):
            try:
                raw = parsed["background_png"]
                _verify_image(raw, "csd-background.png")
                bg_path = _store_bytes(base, raw, "png", "template_bg")
            except (ValueError, OSError) as e:
                report.setdefault("warnings", []).append(f"фон из встроенного PNG не сохранён: {e}")
        con.execute(
            "INSERT INTO template_backgrounds2(template_id, side, image_path, color) VALUES (?,?,?,?)",
            (tid, "front", bg_path, "#FFFFFF"))
        for z, obj in enumerate(parsed["objects"]):
            typ = obj["type"]
            fn = obj.get("field_name") or None
            if fn and fn not in fields:
                fn = None
                if typ == "field":
                    typ = "text"
            if typ == "field" and not fn:
                typ = "text"
            x = _to_storage_units(obj["x"])
            y = _to_storage_units(obj["y"])
            w = max(1, _to_storage_units(obj["w"]))
            h = max(1, _to_storage_units(obj["h"]))
            sv = None
            if typ == "text":
                sv = obj.get("text")
            elif typ == "image" and obj.get("png"):
                try:
                    raw = obj["png"]
                    _verify_image(raw, obj.get("filename") or "csd-image.png")
                    ext = Path(obj["filename"] or "x.png").suffix or ".png"
                    sv = _store_bytes(base, raw, ext, "template_bg")
                except (ValueError, OSError) as e:
                    report.setdefault("warnings", []).append(f"картинка {obj.get('filename')!r} не сохранена: {e}")
                    continue
            style = _style_of(obj)
            con.execute(
                f"INSERT INTO template_elements({','.join(EL_COLS)},template_id) "
                f"VALUES ({','.join('?' * len(EL_COLS))},?)",
                (typ, x, y, w, h, fn, sv, json.dumps(style, ensure_ascii=False),
                 obj.get("side") or "front", z, tid))
            imported.append({"tag": obj["tag"], "type": typ, "field_name": fn,
                             "x": x, "y": y, "w": w, "h": h, "side": obj.get("side") or "front",
                             "native": {"x": obj["x"], "y": obj["y"], "w": obj["w"], "h": obj["h"]}})
    report["imported"] = imported
    report.setdefault("skipped", []).extend(parsed.get("skipped") or [])
    report.setdefault("guessed", []).extend(parsed.get("guessed") or [])
    report.setdefault("warnings", []).extend(parsed.get("warnings") or [])
    report["card_size_native"] = {"w": parsed["card_w"], "h": parsed["card_h"], "unit": "0.1mm"}
    report["printer"] = parsed.get("printer") or ""
    report["name"] = final_name
    return tid


def _import_csp_persons(con, info: dict, report: dict) -> int:
    from .sources import import_rows, open_source
    try:
        dbp = resolve_csp_db(info)
    except FileNotFoundError as e:
        report.setdefault("warnings", []).append(str(e))
        return 0
    table = info.get("table_name")
    csd_f, tbl_f = info.get("csd_fields") or [], info.get("tbl_fields") or []
    if len(csd_f) != len(tbl_f):
        report.setdefault("warnings", []).append(
            f"CSD_Fields ({len(csd_f)}) и TBL_Fields ({len(tbl_f)}) разной длины, сопоставляю по минимуму")
    mapping = {t: c for t, c in zip(tbl_f, csd_f) if t and c}
    extra = _ensure_fields(con, csd_f)
    if extra:
        seen = list(report.get("created_fields") or [])
        for n in extra:
            if n not in seen:
                seen.append(n)
        report["created_fields"] = seen
    sheets = open_source(dbp)
    try:
        sheet = None
        if table:
            sheet = next((s for s in sheets if s.name == table), None)
            if sheet is None:
                report.setdefault("warnings", []).append(
                    f"таблица {table!r} не найдена в {dbp.name}, беру первую")
        if sheet is None:
            sheet = sheets[0] if sheets else None
        if sheet is None:
            report.setdefault("warnings", []).append("в SQLite-базе нет таблиц")
            return 0
        photo_dir = dbp.parent
        rep = import_rows(con, sheet, mapping=mapping or None, photo_dir=photo_dir)
        if getattr(rep, "skipped_columns", None):
            report.setdefault("warnings", []).append(
                f"пропущены колонки без поля: {[c.get('key') for c in rep.skipped_columns]}")
        if getattr(rep, "warnings", None):
            report.setdefault("warnings", []).extend(rep.warnings)
        return int(rep.added or 0)
    finally:
        for s in sheets:
            try:
                s.close()
            except OSError:
                pass


def import_smartid(con, path) -> dict:
    """Импортировать .csd (макет) или .csp (макет + записи из SQLite).

    Полностью заменяет активный шаблон, как import_template (id шаблона не меняется).
    Записи из .csp ДОБАВЛЯЮТСЯ к уже существующим (существующий import_rows),
    маппинг колонок: TBL_Fields → CSD_Fields (CSD_Fields→TBL_Fields в .csp).
    Пишет в переданное соединение (рабочая копия сессии); файл проекта не сохраняет.
    Отсутствующие поля из привязок CSD создаются (текст; Photo/ФОТО — image)
    и перечисляются в report['created_fields'].
    Режим правки шаблона → TemplateEditActiveError.

    Возвращает dict:
      template_id, name, persons_imported,
      report = {imported, skipped, guessed, warnings, created_fields, card_size_native, printer}.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Файл не найден: {p}")
    suf = p.suffix.lower()
    report = {"imported": [], "skipped": [], "guessed": [], "warnings": [], "created_fields": []}
    persons = 0
    if suf == ".csp":
        info = parse_csp(p)
        csd_path = resolve_csp_csd(info)
        parsed = parse_csd(csd_path)
        tid = apply_parsed_csd(con, parsed, name=csd_path.stem, report=report)
        persons = _import_csp_persons(con, info, report)
    elif suf == ".csd":
        parsed = parse_csd(p)
        tid = apply_parsed_csd(con, parsed, name=p.stem, report=report)
    else:
        raise ValueError(f"ожидался файл .csd или .csp, получено {suf or p.name}")
    return {
        "template_id": tid,
        "name": report.get("name"),
        "persons_imported": persons,
        "report": report,
    }


def _resolved_import_sources(path) -> list[Path]:
    """Пути исходников Smart ID, поверх которых нельзя сохранить наш проект."""
    p = Path(path).resolve()
    out = [p]
    if p.suffix.lower() != ".csp":
        return out
    info = parse_csp(p)
    out.append(resolve_csp_csd(info).resolve())
    out.append(resolve_csp_db(info).resolve())
    return out


def import_smartid_as_new_project(path):
    """Создать несохранённый проект и импортировать в него .csd или .csp.

    Возвращает (ProjectSession, result), где result — как у import_smartid.
    source_path пустой (первое сохранение — save_as); своя временная base_dir
    для фонов и картинок. Сам файл проекта не пишет.
    Для .csp сначала находит .csd и SQLite-базу (нет файла — FileNotFoundError
    со всеми проверенными путями). Для .csd записи не импортируются.
    """
    from .project_session import create_unsaved_project
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Файл не найден: {p}")
    suf = p.suffix.lower()
    if suf not in {".csd", ".csp"}:
        raise ValueError(f"ожидался файл .csd или .csp, получено {suf or p.name}")
    sources = _resolved_import_sources(p)
    session = create_unsaved_project(p.stem)
    session.import_source_paths = sources
    try:
        result = import_smartid(session.con, p)
    except Exception:
        session.discard()
        raise
    return session, result
