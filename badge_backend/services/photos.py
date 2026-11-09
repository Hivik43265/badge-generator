"""Сохранение фото в проект (камера/вставка/выбор файла).

project_base_dir(con) -> Path   каталог БД проекта (база относительных photo_path); :memory: → cwd (как ui.backend_api)
save_photo(con, image_bytes, *, person_id=None, ext='jpg', base_dir=None) -> 'photos/<имя>'
"""
from __future__ import annotations
import io, re, uuid
from pathlib import Path

PHOTO_SUBDIR = "photos"

_CON_BASE_DIR: dict[int, Path] = {}

def set_project_base_dir(con, path) -> None:
    """Привязать к соединению каталог исходника (не .work). path=None — снять."""
    if path is None: _CON_BASE_DIR.pop(id(con), None)
    else: _CON_BASE_DIR[id(con)] = Path(path)

def project_base_dir(con) -> Path:
    """Каталог исходного файла проекта (session.base_dir), не каталог рабочей копии .work."""
    custom = _CON_BASE_DIR.get(id(con))
    if custom: return custom
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


# ---------- D43: отмена формы записи ----------
def referenced_photo_paths(con) -> set[str]:
    """Все пути фото, на которые ссылаются записи: persons.photo_path и значения image-полей."""
    import json
    refs = {r[0] for r in con.execute("SELECT photo_path FROM persons WHERE photo_path IS NOT NULL AND photo_path<>''")}
    img = [r[0] for r in con.execute("SELECT name FROM person_fields WHERE data_type='image'")]
    if img:
        for (fj,) in con.execute("SELECT fields_json FROM persons"):
            try: d = json.loads(fj or "{}")
            except (TypeError, ValueError): continue
            for n in img:
                v = d.get(n)
                if isinstance(v, str) and v: refs.add(v)
    return {str(p).replace("\\", "/") for p in refs}

def discard_photo(con, paths, base_dir=None):
    """Удалить файлы фото, созданные в отменённой сессии формы (D43).
    paths — один путь (str/Path → bool: удалён ли файл) или список путей (→ список удалённых).
    Не удаляется: путь вне <base>/photos/ (исходники, абсолютные пути вне каталога), путь, на который
    ссылается любая запись (photo_path или image-поле), несуществующий файл. → список удалённых путей."""
    if isinstance(paths, (str, Path)): return bool(discard_photo(con, [paths], base_dir))
    base = (Path(base_dir) if base_dir else project_base_dir(con)).resolve()
    photos = base / PHOTO_SUBDIR
    refs = {(base / r).resolve() if not Path(r).is_absolute() else Path(r).resolve() for r in referenced_photo_paths(con)}
    out = []
    for rel in paths or []:
        if not rel: continue
        p = Path(str(rel)); p = (p if p.is_absolute() else base / p).resolve()
        if p.parent != photos or p in refs or not p.is_file(): continue
        p.unlink(); out.append(str(rel))
    return out

class PhotoSession:
    """Сессия формы записи (D43). Frontend: s = PhotoSession(con) при открытии формы;
    все новые фото — через s.save_photo(...) / s.apply_and_save_photo(...) или s.track(rel);
    «Отмена» → s.discard() (удаляет созданные в сессии файлы без ссылок); «Сохранить» → s.commit()
    (ничего не удаляет). Если в сессии фото заменили несколько раз, при сохранении записи
    s.commit(discard_unreferenced=True) уберёт промежуточные файлы, на которые запись не ссылается."""
    def __init__(self, con, base_dir=None):
        self.con, self.base_dir, self.created = con, base_dir, []
    def track(self, rel):
        if rel and rel not in self.created: self.created.append(rel)
        return rel
    def save_photo(self, image_bytes, **kw):
        kw.setdefault("base_dir", self.base_dir)
        return self.track(save_photo(self.con, image_bytes, **kw))
    def apply_and_save_photo(self, source_path, params, **kw):
        from .photo_edit import apply_and_save_photo
        kw.setdefault("base_dir", self.base_dir)
        return self.track(apply_and_save_photo(self.con, source_path, params, **kw))
    def discard(self) -> list[str]:
        out = discard_photo(self.con, self.created, self.base_dir); self.created = []; return out
    def commit(self, discard_unreferenced: bool = False) -> list[str]:
        out = discard_photo(self.con, self.created, self.base_dir) if discard_unreferenced else []
        self.created = []; return out
