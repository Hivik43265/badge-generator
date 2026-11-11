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
таблица полей CGFld и значения для повторной привязки. Неизвестные байты
эталонного .csd копируются без изменений (см. ниже).

Что записать нельзя (честный список, в отчёт dropped, без молчаливой потери)
---------------------------------------------------------------------------
- начертание bold / italic / underline — в записи ET неизвестны смещения;
- угол поворота объекта не записывается: в int32 сразу после h остаётся
  значение из эталонной записи того же типа (или 0, если эталона нет).
  Ненулевой угол объекта попадает в dropped. Семантика этого поля
  (градусы или иное) не подтверждена;
- цвет и заливка рамки ER — импортёр всегда считает рамку чёрной, solid,
  без заливки; иное из style попадает в dropped;
- фон оборотной стороны — импортёр принимает за фон только PNG до первого
  объекта (лицевая сторона);
- объекты qr, barcode, line и прочие неизвестные типы — в .csd нет понятных
  тегов, записи пропускаются.

Неизвестные байты (заголовок до фонового PNG, хвост после таблицы CGFld,
неразобранные поля каждой записи) копируются как есть из эталонного .csd:
исходник шаблона (template["source"] / import_source_paths), иначе
встроенный badge_backend/assets/smartid/reference.csd; явно — параметр reference_csd.
Известные поля (размер карточки, dpi, принтер, геометрия, шрифт, цвет,
выравнивание, текст, PNG, имена полей) записываются поверх эталона.

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

TYPE_TITLES = {
    "text": "Текст",
    "field": "Поле",
    "photo": "Фото",
    "image": "Картинка",
    "rect": "Прямоугольник",
    "qr": "QR-код",
    "barcode": "Штрихкод",
    "line": "Линия",
}


def _fmt_comma(val) -> str:
    """Число для пользователя: десятичная запятая, без лишних нулей."""
    x = float(val)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _fmt_mm_from_units(u) -> str:
    """Единицы шаблона (0,1 мм) → строка в миллиметрах."""
    from .. import units_to_mm
    return f"{_fmt_comma(units_to_mm(float(u)))} мм"


def _obj_caption(obj: dict) -> str:
    for key in ("text", "static_value", "label"):
        val = obj.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _human_title(typ: str | None, n: int, obj: dict) -> str:
    kind = (typ or "").casefold() or "объект"
    caption = _obj_caption(obj)
    if kind == "qr":
        return f"QR-код «{caption}»" if caption else f"QR-код {n}"
    if kind == "barcode":
        return f"Штрихкод «{caption}»" if caption else f"Штрихкод {n}"
    base = TYPE_TITLES.get(kind, "Объект")
    return f"{base} {n}"


def _drop(dropped: list, title: str, user_msg: str, tech: str | None = None) -> None:
    dropped.append(f"{title}: {user_msg}")
    log.info("smartid_write %s: %s", title, tech or user_msg)


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
        log.info("write_csd %s: исходник не PNG, записан как PNG", label)
        return buf.getvalue()
    except Exception as e:
        _drop(dropped, label, "нет изображения", tech=f"не удалось прочитать изображение ({e})")
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
        _drop(dropped, label, "нет изображения", tech=f"файл изображения не найден ({src})")
        return None
    return _ensure_png(p.read_bytes(), dropped, label)


def _objects_of(template: dict) -> list[dict]:
    objs = template.get("objects")
    if objs is None:
        objs = template.get("elements") or []
    return list(objs)


def _flag_on(val) -> bool:
    """Флаг стиля: True/1/"1"/"true"/"yes" — включён; False/0/"0"/"false"/""/None — нет."""
    if isinstance(val, str):
        return val.strip().casefold() not in ("", "0", "false", "no", "off", "none", "normal")
    return bool(val)


def _weight_is_bold(weight) -> bool:
    if weight is None or weight == "":
        return False
    if isinstance(weight, str):
        w = weight.strip().casefold()
        if w.isdigit():
            return int(w) >= 600
        return any(k in w for k in ("bold", "black", "heavy"))
    try:
        return float(weight) >= 600
    except (TypeError, ValueError):
        return False


def _note_dropped_style(obj: dict, st: dict, dropped: list, title: str) -> None:
    """Жирный / курсив / подчёркивание → dropped, по одной строке на начертание.

    Источники (любой включает): style["bold"] / style["italic"] / style["underline"]
    (ключи модели), те же ключи на уровне объекта, font_weight (≥600 или «bold»),
    font_style italic/oblique.
    """
    def get(key):
        return st.get(key) if st.get(key) is not None else obj.get(key)

    reasons: dict[str, list[str]] = {}
    for key in ("bold", "italic", "underline"):
        if _flag_on(get(key)):
            reasons.setdefault(key, []).append(f"style[{key!r}]")
    weight = get("font_weight")
    if _weight_is_bold(weight):
        reasons.setdefault("bold", []).append(f"font_weight={weight!r}")
    fstyle = get("font_style")
    if isinstance(fstyle, str) and fstyle.strip().casefold() in ("italic", "oblique"):
        reasons.setdefault("italic", []).append(f"font_style={fstyle!r}")
    for key, user_msg in (("bold", "жирный"), ("italic", "курсив"), ("underline", "подчёркивание")):
        if key in reasons:
            _drop(dropped, title, user_msg,
                  tech=f"начертание {key} не записывается ({', '.join(reasons[key])}): "
                       "смещение в записи ET неизвестно")



def bundled_reference_csd() -> Path | None:
    """Встроенный эталон .csd (замечание №1, 11.11): app_paths.find_asset("smartid", "reference.csd").

    Порядок: <app_root>/assets/smartid/reference.csd (exe onedir — папка assets рядом с exe),
    badge_backend/assets/smartid/reference.csd (исходники), <_MEIPASS>/badge_backend/assets/smartid/
    (старые onefile-сборки). Нет нигде → None.
    """
    from ..app_paths import find_asset
    return find_asset("smartid", "reference.csd")


def default_reference_csd() -> Path | None:
    """Эталон неизвестных байтов: встроенный ресурс."""
    return bundled_reference_csd()


def _first_existing(cands) -> Path | None:
    seen: set[Path] = set()
    for c in cands:
        try:
            key = c.resolve() if c.exists() else c
        except OSError:
            key = c
        if key in seen:
            continue
        seen.add(key)
        if c.is_file():
            return c
    return None


def _resolve_reference(template, reference_csd, import_source_paths) -> Path | None:
    if reference_csd is not None:
        p = Path(reference_csd)
        if not p.is_file():
            raise FileNotFoundError(p)
        return p
    paths = []
    if isinstance(template, dict):
        paths.append(template.get("source") or template.get("source_path"))
        paths.extend(template.get("import_source_paths") or [])
    paths.extend(import_source_paths or [])
    for raw in paths:
        q = _as_path(raw)
        if q is None:
            continue
        if q.is_file() and q.suffix.lower() == ".csd":
            return q
        if q.is_file() and q.suffix.lower() == ".csp":
            try:
                info = smartid.parse_csp(q)
                csd = smartid.resolve_csp_csd(info)
            except (OSError, ValueError, FileNotFoundError):
                continue
            if csd.is_file():
                return csd
    return default_reference_csd()


def _load_reference(path) -> dict | None:
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    data = p.read_bytes()
    if not data.startswith(b"CSD"):
        return None
    starts = smartid._scan_objects(data)
    first_obj = starts[0] if starts else len(data)
    png_at = data.find(PNG_MAGIC)
    header_end = png_at if 0 <= png_at < first_obj else first_obj
    j = data.find(b"CGFld")
    prefix_off = j - 8 if j >= 8 else None
    if starts:
        ends = list(starts[1:])
        last_end = prefix_off if prefix_off is not None and prefix_off > starts[-1] else len(data)
        ends.append(last_end)
    else:
        ends = []
    by_tag: dict[str, list[bytes]] = {}
    objects = []
    for start, end in zip(starts, ends):
        if end < start:
            end = len(data)
        blob = data[start:end]
        if len(blob) < 8:
            continue
        tag = blob[6:8].decode("ascii", errors="replace")
        objects.append({"tag": tag, "start": start, "end": end, "blob": blob})
        by_tag.setdefault(tag, []).append(blob)
    field_prefix = b""
    field_recs: list[bytes] = []
    tail = b""
    if j >= 8:
        field_prefix = data[j - 8:j]
        count = smartid._u16_at(data, j - 8) or 0
        if count < 1 or count > 256:
            count = max(1, len(data[j:]) // FIELD_REC_SIZE)
        for i in range(count):
            rec = data[j + i * FIELD_REC_SIZE:j + (i + 1) * FIELD_REC_SIZE]
            if len(rec) < FIELD_REC_SIZE:
                break
            field_recs.append(rec)
        tail = data[j + len(field_recs) * FIELD_REC_SIZE:]
    size_off = smartid._read_card_size(data)[2]
    return {
        "path": p,
        "header": data[:header_end],
        "size_off": size_off,
        "by_tag": by_tag,
        "objects": objects,
        "field_prefix": field_prefix,
        "field_recs": field_recs,
        "tail": tail,
    }


def _take_skeleton(ref: dict | None, counters: dict, tag: str) -> bytes | None:
    if not ref:
        return None
    arr = ref.get("by_tag", {}).get(tag) or []
    if not arr:
        return None
    i = counters.get(tag, 0)
    counters[tag] = i + 1
    return arr[i] if i < len(arr) else arr[-1]


def _overlay_printer(buf: bytearray, printer: str, size_off: int | None) -> None:
    current = smartid._read_printer(bytes(buf))
    if (printer or "") == (current or ""):
        return
    j = bytes(buf).find(b"PRN\x00")
    if j < 0:
        return
    region_off = j + 4
    start = None
    region = bytes(buf[region_off:region_off + 200])
    for off in range(0, min(12, max(0, len(region) - 4)), 2):
        s = smartid._utf16z(region, off, 64)
        if len(s) >= 3 and any(c.isalpha() for c in s):
            start = region_off + off
            break
    if start is None:
        start = region_off + 4
    limit = size_off if size_off is not None else len(buf)
    # не заходим на байты размера карточки и нетривиальный хвост заголовка
    end = start
    while end + 2 <= limit and end + 2 <= len(buf):
        ch = struct.unpack_from("<H", buf, end)[0]
        end += 2
        if ch == 0:
            while end + 2 <= limit and end + 2 <= len(buf) and struct.unpack_from("<H", buf, end)[0] == 0:
                end += 2
            break
    room = end - start
    raw = (printer or "").encode("utf-16le") + b"\x00\x00"
    raw = raw[: room - (room % 2)]
    buf[start:start + len(raw)] = raw
    if len(raw) < room:
        buf[start + len(raw):end] = b"\x00" * (end - start - len(raw))


def _header_from_ref(ref: dict, card_w, card_h, dpi, printer: str) -> bytes:
    buf = bytearray(ref["header"])
    size_off = ref.get("size_off")
    if size_off is not None and size_off + 4 <= len(buf):
        buf[size_off:size_off + 2] = _u16(card_w)
        buf[size_off + 2:size_off + 4] = _u16(card_h)
        for extra in (10, 8, 12, 6, 14, 4):
            off = size_off + 4 + extra
            if off + 2 <= len(buf):
                cur = struct.unpack_from("<H", buf, off)[0]
                if cur in (200, 300, 600):
                    buf[off:off + 2] = _u16(dpi)
    _overlay_printer(buf, printer, size_off)
    return bytes(buf)


def _note_angle(obj: dict, st: dict, dropped: list, title: str) -> None:
    raw = obj.get("rotation") if obj.get("rotation") is not None else st.get("rotation")
    try:
        rot = float(raw or 0)
    except (TypeError, ValueError):
        rot = 0
    if rot:
        _drop(dropped, title, f"поворот {_fmt_comma(rot)}°",
              tech=f"угол {raw!r} не записывается: int32 после h остаётся из эталона (или 0)")


def _overlay_xywh(rec: bytearray, obj: dict, st: dict) -> None:
    if len(rec) < 28:
        rec.extend(b"\x00" * (28 - len(rec)))
    flags = obj.get("flags")
    if flags is None:
        flags = st.get("flags")
    if flags is not None:
        rec[8:12] = _i32(int(flags))
    rec[12:28] = (_i32(int(obj["x"])) + _i32(int(obj["y"]))
                  + _i32(int(obj["w"])) + _i32(int(obj["h"])))



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



def _existing_font(blob: bytes) -> tuple[int | None, str, str]:
    """Как parse_csd: первое подходящее имя в окне 0x94..0xA4."""
    if len(blob) < 0x96:
        return None, "", ""
    best = None
    for off in range(0x94, min(len(blob) - 4, 0xA4)):
        raw = smartid._utf16z(blob, off, 32)
        fam = raw.lstrip("@").strip()
        if not fam or not ("A" <= fam[0] <= "Z" or "a" <= fam[0] <= "z"):
            continue
        if not fam.replace(" ", "").isascii():
            continue
        score = sum(c.isalpha() for c in fam)
        if score >= 2 and (best is None or score > best[0]):
            best = (score, off, raw, fam)
    if not best:
        return None, "", ""
    return best[1], best[2], best[3]


def _write_font_name(rec: bytearray, family: str, dropped: list, label: str) -> None:
    off, raw, fam = _existing_font(bytes(rec))
    if fam == family:
        return
    if off is None:
        off = 0x97
        payload = ("@" + family).encode("utf-16le")
    else:
        prefix = "@" if raw.startswith("@") else ""
        payload = (prefix + family).encode("utf-16le")
    room = 0xDD - off
    if room < 2:
        return
    if len(payload) > room:
        payload = payload[: room - (room % 2)]
        _drop(dropped, label, "имя шрифта обрезано",
              tech=f"имя шрифта обрезано до {len(payload) // 2} символов")
    rec[off:off + len(payload)] = payload
    end = off + len(payload)
    if end + 2 <= 0xDD:
        rec[end:end + 2] = b"\x00\x00"
    if not family.replace(" ", "").isascii():
        _drop(dropped, label, "имя шрифта",
              tech=f"имя шрифта {family!r} не ASCII — импортёр его при чтении пропустит")


def _build_et(obj: dict, st: dict, text: str, dropped: list, label: str,
              skeleton: bytes | None = None) -> bytes:
    _note_dropped_style(obj, st, dropped, label)
    _note_angle(obj, st, dropped, label)
    family = (st.get("font_family") or obj.get("font_family") or "").strip()
    rgb = _parse_color(st.get("color") or obj.get("color"))
    align_src = st.get("align") if st.get("align") is not None else (
        obj.get("align") if obj.get("align") is not None else obj.get("alignment"))
    size = st.get("font_size") if st.get("font_size") is not None else obj.get("font_size")
    if skeleton:
        rec = bytearray(skeleton)
        if len(rec) < 0xE1:
            rec.extend(b"\x00" * (0xE1 - len(rec)))
        _overlay_xywh(rec, obj, st)
        if rgb is not None and len(rec) >= 0x2F:
            rec[0x2C:0x2F] = bytes(rgb)
        if align_src is not None and len(rec) > 0x8B:
            rec[0x8B] = _align_byte(align_src)
        if size is not None:
            rec[0x90:0x94] = _i32(int(size))
        if family:
            _write_font_name(rec, family, dropped, label)
        old_n = struct.unpack_from("<i", rec, 0xDD)[0]
        if old_n < 0 or old_n > 10000:
            old_n = 0
        old_end = min(len(rec), 0xE1 + old_n * 2)
        tail = bytes(rec[old_end:])
        n, raw = _utf16_payload(text or "")
        return bytes(rec[:0xDD]) + _i32(n) + raw + tail

    rec = bytearray(0xDD)
    rec[0:8] = bytes.fromhex("01 80 05 00 00 00") + b"ET"
    flags = int(obj.get("flags") or st.get("flags") or 0x01000000)
    rec[8:28] = _i32(flags) + _i32(int(obj["x"])) + _i32(int(obj["y"])) + _i32(int(obj["w"])) + _i32(int(obj["h"]))
    rec[28:32] = _i32(0)
    rec[0x20:0x2C] = bytes.fromhex("ff 00 01 00 00 00 00 00 00 00 00 00")
    rec[0x2C:0x30] = bytes(rgb or (0, 0, 0)) + b"\x00"
    rec[0x8B] = _align_byte(align_src)
    if size is not None:
        rec[0x90:0x94] = _i32(int(size))
    rec[0x94:0x97] = bytes.fromhex("01 80 00")
    if family:
        face = ("@" + family).encode("utf-16le")
        room = 0xDD - 0x97
        if len(face) > room:
            face = face[: room - (room % 2)]
            _drop(dropped, label, "имя шрифта обрезано",
                  tech=f"имя шрифта обрезано до {len(face) // 2} символов")
        rec[0x97:0x97 + len(face)] = face
        if not family.replace(" ", "").isascii():
            _drop(dropped, label, "имя шрифта",
                  tech=f"имя шрифта {family!r} не ASCII — импортёр его при чтении пропустит")
    n, raw = _utf16_payload(text or "")
    rec += _i32(n) + raw
    return bytes(rec)


def _mi_filename_offset(blob: bytes) -> int | None:
    name = smartid._find_filename(blob)
    if name:
        n, raw = _utf16_payload(name)
        needle = _i32(n) + raw
        pos = blob.find(needle)
        if pos >= 0:
            return pos
    png_at = blob.find(PNG_MAGIC)
    if png_at >= 8:
        # типичная раскладка: [имя][int32 размер PNG][PNG]
        return None
    return 195 if len(blob) >= 199 else None


def _build_mi(obj: dict, st: dict, png: bytes | None, filename: str | None,
              dropped: list, label: str, skeleton: bytes | None = None) -> bytes:
    _note_angle(obj, st, dropped, label)
    name = filename or obj.get("filename") or st.get("filename") or "image.png"
    blob = png or _PLACEHOLDER_PNG
    if png is None:
        _drop(dropped, label, "нет изображения",
              tech="нет пикселей изображения, записана заглушка 1×1 PNG")
    n, raw = _utf16_payload(name)
    payload = _i32(n) + raw + _i32(len(blob)) + blob
    if skeleton:
        rec = bytearray(skeleton)
        _overlay_xywh(rec, obj, st)
        fn_off = _mi_filename_offset(bytes(skeleton))
        png_at = skeleton.find(PNG_MAGIC)
        if png_at < 0:
            tail = b""
            cut = fn_off if fn_off is not None else min(195, len(rec))
        else:
            extracted, _, png_end = smartid._extract_png(skeleton, png_at)
            cut_end = png_end if png_end and png_end > 0 else png_at
            tail = bytes(rec[cut_end:])
            cut = fn_off if fn_off is not None else (png_at - 4 if png_at >= 4 else png_at)
            # если нашли имя, режем с его префикса длины
            if fn_off is not None:
                cut = fn_off
        if cut < 0:
            cut = 0
        return bytes(rec[:cut]) + payload + tail

    rec = bytearray(195)
    rec[0:8] = bytes.fromhex("01 80 04 00 00 00") + b"MI"
    flags = int(obj.get("flags") or st.get("flags") or 0x01000000)
    rec[8:28] = (_i32(flags) + _i32(int(obj["x"])) + _i32(int(obj["y"]))
                 + _i32(int(obj["w"])) + _i32(int(obj["h"])))
    rec[28:32] = _i32(0)
    rec[0x20:0x2C] = bytes.fromhex("ff 00 01 00 00 00 00 00 00 00 00 00")
    rec += payload
    return bytes(rec)


def _build_er(obj: dict, st: dict, dropped: list, label: str,
              skeleton: bytes | None = None) -> bytes:
    _note_angle(obj, st, dropped, label)
    color = st.get("border_color") or st.get("stroke") or obj.get("border_color")
    parsed = _parse_color(color) if color else None
    if parsed is not None and parsed != (0, 0, 0):
        _drop(dropped, label, "цвет рамки",
              tech=f"цвет рамки {color!r} не записывается: импортёр читает ER как чёрную solid без заливки")
    if st.get("bg_fill") or st.get("fill") or obj.get("bg_fill"):
        _drop(dropped, label, "заливка",
              tech="заливка прямоугольника не записывается")
    bw = st.get("border_width") if st.get("border_width") is not None else st.get("stroke_width")
    if bw not in (None, "", 1, 1.0, "1"):
        try:
            user_bw = f"толщина рамки {_fmt_mm_from_units(bw)}"
        except (TypeError, ValueError):
            user_bw = "толщина рамки"
        _drop(dropped, label, user_bw,
              tech=f"толщина рамки {bw!r} ед. (0,1 мм) не записывается")
    if skeleton:
        rec = bytearray(skeleton)
        _overlay_xywh(rec, obj, st)
        return bytes(rec)
    rec = bytearray(131)
    rec[0:8] = bytes.fromhex("01 80 00 00 00 00") + b"ER"
    flags = int(obj.get("flags") or st.get("flags") or 0x01000000)
    rec[8:28] = (_i32(flags) + _i32(int(obj["x"])) + _i32(int(obj["y"]))
                 + _i32(int(obj["w"])) + _i32(int(obj["h"])))
    rec[32:40] = bytes.fromhex("00 00 01 00 00 00 00 00")
    rec[40:44] = bytes.fromhex("01 00 00 00")
    return bytes(rec)


def _overlay_field_rec(base: bytes, i: int, name: str, value: str) -> bytes:
    rec = bytearray(base)
    if len(rec) < FIELD_REC_SIZE:
        rec.extend(b"\x00" * (FIELD_REC_SIZE - len(rec)))
    if i == 0:
        rec[0:5] = b"CGFld"
    else:
        rec[3] = 0x0E
        rec[4] = 0x80
        rec[5] = i & 0xFF
    n_name, raw_name = _utf16_payload(name)
    raw_name = raw_name[:62]
    rec[9:9 + len(raw_name)] = raw_name
    # нуль после имени, если дальше ещё есть место (для более короткого имени)
    end = 9 + len(raw_name)
    if end + 2 <= 73:
        rec[end:end + 2] = b"\x00\x00"
    n_val, raw_val = _utf16_payload(value)
    max_val = FIELD_REC_SIZE - 77
    raw_val = raw_val[: max_val - (max_val % 2)]
    n_val = len(raw_val) // 2
    rec[73:77] = _i32(n_val)
    rec[77:77 + len(raw_val)] = raw_val
    return bytes(rec[:FIELD_REC_SIZE])


def _build_fields_table(pairs: list[tuple[str, str]], ref: dict | None = None) -> bytes:
    if not pairs:
        return b""
    out = bytearray()
    if ref and ref.get("field_prefix"):
        prefix = bytearray(ref["field_prefix"])
        if len(prefix) >= 2:
            prefix[0:2] = _u16(len(pairs))
        out += prefix
    else:
        out += _u16(len(pairs)) + bytes.fromhex("ff ff 00 00 05 00")
    ref_recs = (ref or {}).get("field_recs") or []
    for i, (name, value) in enumerate(pairs):
        if ref_recs:
            base = ref_recs[i] if i < len(ref_recs) else ref_recs[-1]
            out += _overlay_field_rec(base, i, name, value)
        else:
            rec = bytearray(FIELD_REC_SIZE)
            out += _overlay_field_rec(bytes(rec), i, name, value)
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


def build_csd_bytes(template: dict, *, base_dir=None, reference_csd=None,
                    import_source_paths=None) -> tuple[bytes, list[str]]:
    """Собрать байты .csd и список неучтённых свойств. Файл не пишет."""
    if not isinstance(template, dict):
        raise TypeError("template должен быть dict (результат parse_csd или снимок элементов)")
    dropped: list[str] = []
    card_w = int(template.get("card_w") or DEFAULT_CARD_W)
    card_h = int(template.get("card_h") or DEFAULT_CARD_H)
    dpi = int(template.get("dpi") or DEFAULT_DPI)
    printer = template.get("printer") or ""
    ref_path = _resolve_reference(template, reference_csd, import_source_paths)
    ref = _load_reference(ref_path)
    if ref:
        parts = [_header_from_ref(ref, card_w, card_h, dpi, printer)]
    else:
        parts = [_header(card_w, card_h, dpi, printer)]

    bg = template.get("background_png")
    if bg is None:
        bgs = template.get("backgrounds") or {}
        bg = bgs.get("front") if isinstance(bgs, dict) else None
    bg_png = _load_png(bg, base_dir, dropped, "Фон лицевой стороны")
    bgs = template.get("backgrounds") or {}
    if isinstance(bgs, dict) and bgs.get("back"):
        _drop(dropped, "Фон оборота", "не поддерживается в .csd",
              tech="импортёр принимает за фон только PNG до первого объекта")
    if bg_png:
        parts.append(bg_png)

    used_fields: list[tuple[str, str]] = []
    counters: dict[str, int] = {}
    type_n: dict[str, int] = {}
    for idx, raw in enumerate(_objects_of(template)):
        obj = dict(raw)
        st = _style_of(obj)
        typ = _classify(obj)
        kind = typ or (obj.get("tag") or "объект")
        type_n[kind] = type_n.get(kind, 0) + 1
        title = _human_title(kind, type_n[kind], obj)
        label = title
        log.debug("write_csd элемент[%s] type=%r → %s", idx, kind, title)
        if typ not in WRITABLE_TYPES:
            _drop(dropped, title, "не поддерживается в .csd",
                  tech=f"элемент[{idx}] type={kind!r} не записывается (text/field/photo/image/rect)")
            continue
        x, y, w, h = _csd_xy(obj)
        rec_obj = {**obj, "x": x, "y": y, "w": max(1, w), "h": max(1, h)}
        tag = WRITABLE_TYPES[typ]
        skel = _take_skeleton(ref, counters, tag)
        if typ in ("text", "field"):
            text = obj.get("text")
            if text is None:
                text = obj.get("static_value") if typ == "text" else None
            fname = obj.get("field_name") or None
            if typ == "field" and fname:
                if text is None or text == "":
                    text = _field_value_for(template, fname) or fname
                used_fields.append((fname, str(text)))
            parts.append(_build_et(rec_obj, st, "" if text is None else str(text),
                                   dropped, label, skel))
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
            parts.append(_build_mi(rec_obj, st, png, filename, dropped, label, skel))
        else:
            parts.append(_build_er(rec_obj, st, dropped, label, skel))

    parts.append(_build_fields_table(_field_pairs(template, used_fields), ref))
    if ref and ref.get("tail"):
        parts.append(ref["tail"])
    return b"".join(parts), dropped


def _field_value_for(template: dict, name: str) -> str | None:
    want = (name or "").casefold()
    for item in template.get("fields") or []:
        if isinstance(item, dict) and (item.get("name") or "").casefold() == want:
            val = item.get("value")
            return None if val is None else str(val)
    return None


def write_csd(template, path, *, overwrite: bool = False, import_source_paths=None,
              base_dir=None, reference_csd=None) -> dict:
    """Записать .csd. Возвращает {"path": Path, "dropped": [str, ...]}.

    overwrite=False (по умолчанию) — не трогать существующий файл.
    overwrite=True разрешает заменить файл, но не исходник Smart ID
    (см. import_source_paths и template["source"] в docstring модуля).
    reference_csd — явный эталон неизвестных байтов; иначе исходник шаблона
    или badge_backend/assets/smartid/reference.csd.
    """
    dest = _check_target(path, overwrite=overwrite, template=template,
                         import_source_paths=import_source_paths)
    if base_dir is None and isinstance(template, dict):
        base_dir = template.get("base_dir")
    data, dropped = build_csd_bytes(
        template, base_dir=base_dir, reference_csd=reference_csd,
        import_source_paths=import_source_paths,
    )
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
        _drop(dropped, "Привязки полей",
              "число имён в макете и в таблице не совпадает",
              tech=f"CSD_Fields ({len(fields_a)}) и TBL_Fields ({len(fields_b)}) разной длины")
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
    "bundled_reference_csd",
    "default_reference_csd",
]
