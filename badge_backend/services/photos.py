"""Сохранение фото в проект (камера/вставка/выбор файла).

project_base_dir(con) -> Path   каталог БД проекта (база относительных photo_path); :memory: → cwd (как ui.backend_api)
save_photo(con, image_bytes, *, person_id=None, ext='jpg', base_dir=None) -> 'photos/<имя>'
"""
from __future__ import annotations
import io, re, uuid
from pathlib import Path

PHOTO_SUBDIR = "photos"

def project_base_dir(con) -> Path:
    for _, name, file in con.execute("PRAGMA database_list"):
        if name == "main": return Path(file).resolve().parent if file else Path.cwd()
    return Path.cwd()

def save_photo(con, image_bytes, *, person_id=None, ext: str = "jpg", base_dir=None) -> str:
    """Проверить картинку Pillow (пустая/битая → ValueError), записать байты как есть в
    <base_dir>/photos/ под уникальным именем, вернуть относительный путь ('photos/…', '/' как разделитель).
    person_id → persons.photo_path записи (нет записи → ValueError, файл не остаётся)."""
    from PIL import Image, UnidentifiedImageError
    data = bytes(image_bytes or b"")
    if not data: raise ValueError("пустое изображение")
    try:
        with Image.open(io.BytesIO(data)) as im: im.verify()
        with Image.open(io.BytesIO(data)) as im: im.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        raise ValueError(f"повреждённое изображение: {e}") from None
    ext = re.sub(r"[^a-z0-9]", "", str(ext or "jpg").lower().lstrip(".")) or "jpg"
    if ext == "jpeg": ext = "jpg"
    base = Path(base_dir) if base_dir else project_base_dir(con)
    d = base / PHOTO_SUBDIR; d.mkdir(parents=True, exist_ok=True)
    prefix = f"p{int(person_id)}" if person_id is not None else "photo"
    while True:
        name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
        try:
            with open(d / name, "xb") as f: f.write(data)
            break
        except FileExistsError: continue
    rel = f"{PHOTO_SUBDIR}/{name}"
    if person_id is not None:
        with con:
            n = con.execute("UPDATE persons SET photo_path=?, updated_at=datetime('now') WHERE id=?", (rel, int(person_id))).rowcount
        if not n:
            (d / name).unlink(missing_ok=True); raise ValueError(f"нет записи id={person_id}")
    return rel


def _person_fields(person) -> dict:
    import json
    if not person: return {}
    f = person.get("fields")
    if isinstance(f, dict) and person.get("fields_json") is None: return f
    fj = person.get("fields_json")
    if isinstance(fj, dict): return fj
    try: return json.loads(fj) if fj else {}
    except (TypeError, ValueError): return {}

def abs_path(rel, base_dir=None) -> Path | None:
    """Относительный путь проекта → абсолютный Path (база base_dir, иначе cwd); пусто → None."""
    if rel in (None, ""): return None
    p = Path(str(rel))
    if not p.is_absolute(): p = Path(base_dir or Path.cwd()) / p
    return p.absolute()

def resolve_photo_path(person, element=None, base_dir=None) -> Path | None:
    """Единое правило фото записи (вариант (a)).
    person   dict/Row записи: fields_json (str|dict) или {'fields': {...}}, photo_path.
    element  элемент photo (dict с 'field_name') или имя image-поля (str); None — только photo_path.
    Значение привязанного image-поля, если непусто, иначе persons.photo_path → абсолютный Path; нет обоих → None.
    Существование файла не проверяется (вызывающий решает: placeholder / warning)."""
    if person is not None and not isinstance(person, dict): person = dict(person)
    fname = element if isinstance(element, str) else (element or {}).get("field_name")
    if fname:
        v = _person_fields(person).get(fname)
        if v not in (None, ""): return abs_path(v, base_dir)
    return abs_path((person or {}).get("photo_path"), base_dir)

def photo_file_issue(path) -> str | None:
    """None — файл есть и читается; иначе 'PHOTO_NOT_FOUND' | 'PHOTO_EMPTY' | 'PHOTO_BROKEN'."""
    p = Path(path)
    if not p.is_file(): return "PHOTO_NOT_FOUND"
    if p.stat().st_size == 0: return "PHOTO_EMPTY"
    try:
        from PIL import Image
        with Image.open(p) as im: im.verify()
    except Exception:
        return "PHOTO_BROKEN"
    return None
