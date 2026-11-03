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
