"""Этап 15 B4: шаблон как файл .bgt (ZIP + template.json + картинки фонов/элементов).

import_template полностью заменяет АКТИВНЫЙ шаблон (id и active_template_id не меняются).
"""
from __future__ import annotations
import io, json, os, posixpath, tempfile, zipfile
from pathlib import Path
from .. import db as _db
from ..db import now_iso
from .project_session import TemplateEditActiveError
from .photos import project_base_dir
from .templates import get_template_edit_state, _name as _tpl_name

FORMAT = "badge-generator-template"
FORMAT_VERSION = 2
SCHEMA_MIN = 8
EL_TYPES = {"text", "field", "photo", "image", "rect", "qr", "barcode", "line", "ellipse"}
SIDES = {"front", "back"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_MEMBERS = 64
MAX_FILE = 20 * 1024 * 1024
MAX_UNCOMP = 50 * 1024 * 1024
ZIP_BOMB_RATIO = 100
ZIP_BOMB_MIN = 1024 * 1024
EL_COLS = ("type", "x", "y", "w", "h", "field_name", "static_value", "style_json", "side", "z_order")


def _safe_member(name: str) -> str:
    if not name or name.endswith("/"): raise ValueError(f"опасный путь в архиве: {name!r}")
    n = name.replace("\\", "/")
    if n.startswith("/") or posixpath.isabs(n): raise ValueError(f"опасный путь в архиве: {name!r}")
    if ":" in n.split("/")[0]: raise ValueError(f"опасный путь в архиве: {name!r}")
    norm = posixpath.normpath(n)
    if norm.startswith("..") or "/../" in f"/{norm}/" or norm == ".":
        raise ValueError(f"опасный путь в архиве: {name!r}")
    return norm


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _check_zip(zf: zipfile.ZipFile):
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ValueError(f"слишком много файлов в архиве ({len(infos)} > {MAX_MEMBERS})")
    total = 0
    for i in infos:
        if i.is_dir(): continue
        if _is_symlink(i): raise ValueError(f"символические ссылки запрещены: {i.filename}")
        _safe_member(i.filename)
        if i.file_size > MAX_FILE:
            raise ValueError(f"файл слишком большой: {i.filename}")
        total += i.file_size
        if i.compress_size and i.file_size > ZIP_BOMB_MIN and i.file_size / max(1, i.compress_size) > ZIP_BOMB_RATIO:
            raise ValueError(f"подозрение на zip-bomb: {i.filename}")
    if total > MAX_UNCOMP:
        raise ValueError("суммарный размер архива слишком велик")


def _read_template_json(zf: zipfile.ZipFile) -> dict:
    names = {_safe_member(i.filename): i for i in zf.infolist() if not i.is_dir()}
    if "template.json" not in names:
        raise ValueError("в архиве нет template.json")
    raw = zf.read("template.json")
    try: data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"template.json повреждён: {e}") from e
    if data.get("format") != FORMAT:
        raise ValueError("это не файл шаблона Badge Generator")
    ver = data.get("format_version")
    if not isinstance(ver, int) or ver < 1:
        raise ValueError("неподдерживаемая версия шаблона")
    if ver > FORMAT_VERSION:
        raise ValueError("неподдерживаемая версия шаблона")
    tpl = data.get("template") or {}
    if not isinstance(tpl, dict) or not str(tpl.get("name") or "").strip():
        raise ValueError("в шаблоне нет имени")
    els = data.get("elements")
    if not isinstance(els, list): raise ValueError("elements должен быть списком")
    for e in els:
        if not isinstance(e, dict) or e.get("type") not in EL_TYPES:
            raise ValueError(f"неизвестный тип элемента: {e.get('type') if isinstance(e, dict) else e}")
        if e.get("side", "front") not in SIDES:
            raise ValueError(f"некорректная сторона: {e.get('side')}")
        try:
            x, y, w, h = int(e["x"]), int(e["y"]), int(e["w"]), int(e["h"])
        except (KeyError, TypeError, ValueError) as ex:
            raise ValueError(f"некорректная геометрия элемента: {ex}") from ex
        if e["type"] != "line" and (w <= 0 or h <= 0):
            raise ValueError("ширина и высота элемента должны быть > 0")
        if e["type"] == "line" and w == 0 and h == 0:
            raise ValueError("линия не может иметь нулевую длину")
        st = e.get("style")
        if st is None: e["style"] = {}
        elif not isinstance(st, dict): raise ValueError("style должен быть объектом")
    if ver == 1:
        _convert_bgt_v1(data)
    bgs = data.get("backgrounds") or []
    if not isinstance(bgs, list): raise ValueError("backgrounds должен быть списком")
    data["_members"] = names
    return data


def _convert_bgt_v1(data: dict) -> None:
    """Геометрия и отступы .bgt v1 были в px @ 300 DPI."""
    from .. import px_to_units
    def conv_style(st):
        if not isinstance(st, dict):
            return
        for k in ("padding", "radius"):
            if st.get(k) is not None:
                try: st[k] = px_to_units(st[k])
                except (TypeError, ValueError): pass
        src = st.get("stroke_width")
        if src is None and "border_width" in st and "border_style" not in st:
            src = st.get("border_width")
        if src not in (None, ""):
            try:
                bw = px_to_units(src)
            except (TypeError, ValueError):
                bw = None
            if bw is not None:
                st["border_width"] = bw
                if bw > 0 and "border_style" not in st:
                    st["border_style"] = "solid"
    tpl = data.get("template") or {}
    conv_style(tpl.get("style") if isinstance(tpl.get("style"), dict) else None)
    for e in data.get("elements") or []:
        if not isinstance(e, dict):
            continue
        for k in ("x", "y", "w", "h"):
            if k in e:
                try: e[k] = px_to_units(e[k])
                except (TypeError, ValueError): pass
        conv_style(e.get("style"))


def _verify_image(data: bytes, name: str):
    ext = Path(name).suffix.lower()
    if ext not in IMAGE_EXT:
        raise ValueError(f"недопустимый тип картинки: {name}")
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        raise ValueError(f"повреждённое изображение {name}: {e}") from e


def _project_fields(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM person_fields")}


def _unlinked_from_data(data: dict, fields: set[str] | None) -> tuple[list[str], list[dict]]:
    missing, objs = [], []
    seen = set()
    for e in data["elements"]:
        fn = e.get("field_name")
        if not fn: continue
        if fields is not None and fn not in fields:
            if fn not in seen:
                seen.add(fn); missing.append(fn)
            objs.append({"type": e["type"], "side": e.get("side") or "front", "field_name": fn,
                         "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"]})
    return missing, objs


def preview_template_file(src_path, con=None) -> dict:
    """Просмотр .bgt без изменения проекта. Битый/опасный архив → ValueError."""
    data = _load(src_path)
    fields_in_file = []
    seen = set()
    for e in data["elements"]:
        fn = e.get("field_name")
        if fn and fn not in seen:
            seen.add(fn); fields_in_file.append(fn)
    have = _project_fields(con) if con is not None else None
    missing, unlinked = _unlinked_from_data(data, have if have is not None else set())
    if con is None:
        missing, unlinked = [], []
    bgs = [b.get("side") for b in data.get("backgrounds") or [] if isinstance(b, dict) and b.get("side") in SIDES]
    has_images = any((b.get("image") if isinstance(b, dict) else None) for b in (data.get("backgrounds") or [])) \
        or any(e.get("type") == "image" and e.get("static_value") for e in data["elements"])
    return {"name": data["template"]["name"], "format_version": data.get("format_version"),
            "style": data["template"].get("style") or {},
            "elements": len(data["elements"]), "fields": fields_in_file,
            "missing_fields": missing, "unlinked_objects": unlinked,
            "backgrounds": bgs, "has_images": bool(has_images)}


def _load(src_path) -> dict:
    p = Path(src_path)
    if not p.is_file(): raise FileNotFoundError(p)
    try:
        zf = zipfile.ZipFile(p)
    except zipfile.BadZipFile as e:
        raise ValueError("файл не является ZIP/.bgt") from e
    with zf:
        _check_zip(zf)
        return _read_template_json(zf)


def _unique_name(con, name: str, except_id: int) -> str:
    n = _tpl_name(name)
    if con.execute("SELECT 1 FROM templates WHERE name=? COLLATE NOCASE AND id<>?", (n, except_id)).fetchone() is None:
        return n
    i = 2
    while True:
        cand = f"{n} ({i})"
        if con.execute("SELECT 1 FROM templates WHERE name=? COLLATE NOCASE AND id<>?", (cand, except_id)).fetchone() is None:
            return cand
        i += 1


def _store_bytes(base: Path, data: bytes, ext: str, subdir: str) -> str:
    ext = ext.lower().lstrip(".") or "png"
    if f".{ext}" not in IMAGE_EXT and ext != "jpeg":
        ext = "png"
    if ext == "jpeg": ext = "jpg"
    d = base / subdir; d.mkdir(parents=True, exist_ok=True)
    import uuid
    while True:
        name = f"{uuid.uuid4().hex[:12]}.{ext}"
        dest = d / name
        if not dest.exists():
            dest.write_bytes(data)
            return f"{subdir}/{name}"


def _extract_member(zf: zipfile.ZipFile, rel: str) -> bytes:
    rel = _safe_member(rel)
    return zf.read(rel)


def export_template(con, dest_path, template_id: int | None = None, *, overwrite: bool = False) -> Path:
    """Экспорт шаблона (None — активный) в .bgt.
    Существующий dest и overwrite=False → FileExistsError; overwrite=True — атомарная замена через tmp рядом."""
    dest = Path(dest_path)
    if dest.suffix.lower() != ".bgt":
        dest = dest.with_suffix(dest.suffix + ".bgt") if dest.suffix else dest.with_suffix(".bgt")
    if dest.exists() and not overwrite:
        raise FileExistsError(dest)
    tid = template_id or _db.active_template_id(con)
    t = con.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()
    if t is None: raise ValueError(f"нет шаблона id={tid}")
    base = project_base_dir(con)
    els, bgs, files = [], [], {}
    for r in con.execute("SELECT type,x,y,w,h,field_name,static_value,style_json,side,z_order "
                         "FROM template_elements WHERE template_id=? ORDER BY z_order, id", (tid,)):
        e = {k: r[k] for k in ("type", "x", "y", "w", "h", "field_name", "static_value", "side", "z_order")}
        e["style"] = json.loads(r["style_json"] or "{}")
        if e["type"] == "image" and e.get("static_value"):
            src = Path(e["static_value"]) if Path(e["static_value"]).is_absolute() else base / e["static_value"]
            if src.is_file():
                arc = f"images/{src.name}"
                files[arc] = src.read_bytes()
                e["static_value"] = arc
        els.append(e)
    for r in con.execute("SELECT side, image_path, color FROM template_backgrounds2 WHERE template_id=?", (tid,)):
        img = None
        if r["image_path"]:
            src = Path(r["image_path"]) if Path(r["image_path"]).is_absolute() else base / r["image_path"]
            if src.is_file():
                ext = src.suffix.lower().lstrip(".") or "png"
                img = f"backgrounds/{r['side']}.{ext}"
                files[img] = src.read_bytes()
        bgs.append({"side": r["side"], "color": r["color"] or "#FFFFFF", "image": img})
    payload = {"format": FORMAT, "format_version": FORMAT_VERSION, "schema_min": SCHEMA_MIN,
               "units": "0.1mm", "exported_at": now_iso(),
               "template": {"name": t["name"], "style": json.loads(t["style_json"] or "{}")},
               "elements": els, "backgrounds": bgs}
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=str(dest.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("template.json", json.dumps(payload, ensure_ascii=False, indent=2))
            for arc, data in files.items():
                zf.writestr(arc, data)
        if dest.exists() and not overwrite:
            raise FileExistsError(dest)
        os.replace(tmp, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def import_template(con, src_path) -> dict:
    """Полностью заменить АКТИВНЫЙ шаблон содержимым .bgt (id шаблона и active_template_id не меняются).
    Объекты с полем, которого нет в проекте, импортируются отвязанными (field_name=NULL).
    Имя всегда из файла; если оно занято ДРУГИМ шаблоном, добавляется « (2)».
    Режим правки шаблона → TemplateEditActiveError. Поля не создаются."""
    if get_template_edit_state(con) is not None:
        raise TemplateEditActiveError("нельзя импортировать шаблон во время правки макета")
    p = Path(src_path)
    with zipfile.ZipFile(p) as zf:
        _check_zip(zf)
        data = _read_template_json(zf)
        tid = _db.active_template_id(con)
        wanted = data["template"]["name"]
        final_name = _unique_name(con, wanted, tid)
        renamed_from = None if final_name == _tpl_name(wanted) else _tpl_name(wanted)
        fields = _project_fields(con)
        missing, unlinked = _unlinked_from_data(data, fields)
        base = project_base_dir(con)
        style = data["template"].get("style") or {}
        style_json = json.dumps({k: style[k] for k in ("font_family", "padding") if k in style}, ensure_ascii=False) \
            if style else "{}"
        now = now_iso()
        with con:
            con.execute("UPDATE templates SET name=?, style_json=?, updated_at=? WHERE id=?",
                        (final_name, style_json, now, tid))
            con.execute("DELETE FROM template_elements WHERE template_id=?", (tid,))
            con.execute("DELETE FROM template_backgrounds2 WHERE template_id=?", (tid,))
            for e in data["elements"]:
                fn = e.get("field_name") or None
                if fn and fn not in fields: fn = None
                sv = e.get("static_value")
                if e.get("type") == "image" and sv:
                    raw = _extract_member(zf, sv)
                    _verify_image(raw, sv)
                    sv = _store_bytes(base, raw, Path(sv).suffix, "template_bg")
                con.execute(
                    f"INSERT INTO template_elements({','.join(EL_COLS)},template_id) VALUES ({','.join('?'*len(EL_COLS))},?)",
                    (e["type"], int(e["x"]), int(e["y"]), int(e["w"]), int(e["h"]), fn, sv,
                     json.dumps(e.get("style") or {}, ensure_ascii=False),
                     e.get("side") or "front", int(e.get("z_order") or 0), tid))
            for b in data.get("backgrounds") or []:
                if not isinstance(b, dict) or b.get("side") not in SIDES: continue
                img_path = None
                if b.get("image"):
                    raw = _extract_member(zf, b["image"])
                    _verify_image(raw, b["image"])
                    img_path = _store_bytes(base, raw, Path(b["image"]).suffix, "template_bg")
                con.execute("INSERT INTO template_backgrounds2(template_id, side, image_path, color) VALUES (?,?,?,?)",
                            (tid, b["side"], img_path, b.get("color") or "#FFFFFF"))
        return {"template_id": tid, "name": final_name, "renamed_from": renamed_from,
                "unlinked_fields": missing, "unlinked_objects": unlinked,
                "active_template_id": tid}
