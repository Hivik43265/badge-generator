"""Этап 14: редактор фото (бэкенд).

apply_photo_edit(img, params) -> Image             правка фото (вход не изменяется)
detect_face_crop(img, aspect) -> (x,y,w,h)|None    кадр по лицу (OpenCV Haar), w/h == aspect
get_photo_edit_defaults(con) / set_photo_edit_defaults(con, params)   умолчания проекта (project_settings)
apply_and_save_photo(con, source_path, params, *, person_id=None, field_name=None, base_dir=None) -> rel_path

Параметры (DEFAULT_PHOTO_EDIT; неизвестные ключи игнорируются, значения приводятся к типу и обрезаются в диапазон):
  brightness int  -50..50   0 — без изменений; множитель яркости 1 + b/100
  contrast   int  -50..50   0 — без изменений; множитель контраста 1 + c/100
  scale      int  10..400   % размера; 100 — без изменений (LANCZOS)
  rotate     float -180..180 градусов ПО ЧАСОВОЙ стрелке (PIL rotate — против, поэтому rotate(-deg)),
             expand=True, углы заливаются белым (RGBA — прозрачным)
  crop       (x,y,w,h) | None — в пикселях УЖЕ преобразованного изображения (после scale/rotate);
             обрезается границами изображения; пустое пересечение → ValueError
  autoeffect bool  ImageOps.autocontrast(cutoff=1%) + нормализация средней яркости к 128
             (множитель 0.6..1.6); ручные brightness/contrast применяются поверх
Порядок: autoeffect → brightness → contrast → scale → rotate → crop.
Скорость превью: UI передаёт уменьшенное изображение (crop тогда в его пикселях); при параметрах по
умолчанию возвращается копия без пересчёта.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps, ImageStat

DEFAULT_PHOTO_EDIT = {"brightness": 0, "contrast": 0, "scale": 100, "rotate": 0.0, "crop": None, "autoeffect": False}
RANGES = {"brightness": (-50, 50), "contrast": (-50, 50), "scale": (10, 400), "rotate": (-180.0, 180.0)}
SETTINGS_KEY = "photo_edit_defaults"


def _clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v

def normalize_params(params: dict | None) -> dict:
    """Привести/обрезать параметры к допустимым; None/{} → DEFAULT_PHOTO_EDIT. Нечисло → ValueError."""
    p = dict(DEFAULT_PHOTO_EDIT)
    for k, v in (params or {}).items():
        if k not in p or v is None and k != "crop": continue
        try:
            if k in ("brightness", "contrast", "scale"): p[k] = int(round(_clamp(float(v), *RANGES[k])))
            elif k == "rotate": p[k] = float(_clamp(float(v), *RANGES[k]))
            elif k == "autoeffect": p[k] = bool(v)
            elif k == "crop":
                if v is None: p[k] = None
                else:
                    x, y, w, h = (int(round(float(t))) for t in v)
                    if w <= 0 or h <= 0: raise ValueError("crop: w и h должны быть > 0")
                    p[k] = (x, y, w, h)
        except (TypeError, ValueError) as e:
            raise ValueError(f"параметр {k}={v!r}: {e}") from None
    return p

def _is_identity(p): return p == DEFAULT_PHOTO_EDIT

def _split_alpha(im):
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA"); return im.convert("RGB"), im.getchannel("A")
    return (im if im.mode in ("RGB", "L") else im.convert("RGB")), None

def _autoeffect(im):
    im = ImageOps.autocontrast(im, cutoff=1)
    mean = sum(ImageStat.Stat(im.convert("L")).mean) or 1.0
    return ImageEnhance.Brightness(im).enhance(_clamp(128.0 / mean, 0.6, 1.6))

def apply_photo_edit(img: Image.Image, params: dict | None) -> Image.Image:
    """Применить правку (порядок и параметры — в docstring модуля). Вход не изменяется; → новое Image
    (режим RGB/L, либо RGBA, если у входа была прозрачность)."""
    p = normalize_params(params)
    if _is_identity(p): return img.copy()
    im, alpha = _split_alpha(img.copy())
    if p["autoeffect"]: im = _autoeffect(im)
    if p["brightness"]: im = ImageEnhance.Brightness(im).enhance(1 + p["brightness"] / 100)
    if p["contrast"]: im = ImageEnhance.Contrast(im).enhance(1 + p["contrast"] / 100)
    if alpha is not None: im = im.convert("RGBA"); im.putalpha(alpha)
    if p["scale"] != 100:
        im = im.resize((max(1, round(im.width * p["scale"] / 100)), max(1, round(im.height * p["scale"] / 100))), Image.LANCZOS)
    if p["rotate"]:
        fill = (0, 0, 0, 0) if im.mode == "RGBA" else (255 if im.mode == "L" else (255, 255, 255))
        im = im.rotate(-p["rotate"], resample=Image.BICUBIC, expand=True, fillcolor=fill)
    if p["crop"]:
        x, y, w, h = p["crop"]
        l, t, r, b = max(0, x), max(0, y), min(im.width, x + w), min(im.height, y + h)
        if r <= l or b <= t: raise ValueError(f"crop {p['crop']} вне изображения {im.size}")
        im = im.crop((l, t, r, b))
    return im

# ---------- лицо ----------
CASCADE = "haarcascade_frontalface_default.xml"
FACE_HEIGHT = 0.65      # доля высоты кадра, занимаемая лицом (60–70%)
HEADROOM = 0.12         # отступ над верхом прямоугольника лица, доля высоты кадра

def cascade_path() -> str:
    """Путь к Haar-каскаду: в exe (PyInstaller) — <_MEIPASS>/cv2/data/, иначе cv2.data.haarcascades."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = os.path.join(sys._MEIPASS, "cv2", "data", CASCADE)
        if os.path.isfile(p): return p
    import cv2
    return os.path.join(cv2.data.haarcascades, CASCADE)

_clf = None
def _classifier():
    global _clf
    if _clf is None:
        import cv2
        c = cv2.CascadeClassifier(cascade_path())
        if c.empty(): raise RuntimeError(f"не удалось загрузить каскад {cascade_path()}")
        _clf = c
    return _clf

def detect_face_crop(img: Image.Image, aspect: float):
    """Кадр (x, y, w, h) в пикселях переданного img по самому крупному лицу; нет лица → None.
    Кадр: высота H = лицо / FACE_HEIGHT, ширина W = H·aspect (aspect = w/h элемента photo), лицо по центру
    по горизонтали, верх кадра на HEADROOM·H выше верха лица. Без «полей»: если кадр больше изображения,
    он уменьшается (с сохранением aspect) до вписывания, затем сдвигается внутрь границ."""
    import numpy as np
    import cv2
    aspect = float(aspect)
    if not aspect > 0: raise ValueError("aspect должен быть > 0")
    g = np.asarray(img.convert("L"))
    m = max(20, min(g.shape) // 12)
    faces = _classifier().detectMultiScale(g, scaleFactor=1.1, minNeighbors=5, minSize=(m, m))
    if len(faces) == 0: return None
    fx, fy, fw, fh = max(faces, key=lambda f: int(f[2]) * int(f[3]))
    H = fh / FACE_HEIGHT; W = H * aspect
    k = min(1.0, img.width / W, img.height / H); W *= k; H *= k
    cx = fx + fw / 2
    x = _clamp(cx - W / 2, 0, img.width - W); y = _clamp(fy - HEADROOM * H, 0, img.height - H)
    h = max(1, int(round(H))); w = max(1, min(img.width, int(round(h * aspect))))
    if w > img.width: w = img.width; h = max(1, int(round(w / aspect)))
    x = int(_clamp(round(x), 0, img.width - w)); y = int(_clamp(round(y), 0, img.height - h))
    return (x, y, w, h)

# ---------- умолчания проекта ----------
def get_photo_edit_defaults(con) -> dict:
    """Умолчания проекта (project_settings['photo_edit_defaults']); не сохранены → DEFAULT_PHOTO_EDIT."""
    r = con.execute("SELECT value FROM project_settings WHERE key=?", (SETTINGS_KEY,)).fetchone()
    try: return normalize_params(json.loads(r[0]) if r else None)
    except (ValueError, TypeError): return dict(DEFAULT_PHOTO_EDIT)

def set_photo_edit_defaults(con, params: dict | None) -> dict:
    """Сохранить умолчания проекта (нормализованные; crop не сохраняется — он зависит от фото). → сохранённое."""
    p = normalize_params(params); p["crop"] = None
    with con: con.execute("INSERT INTO project_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (SETTINGS_KEY, json.dumps(p)))
    return p

# ---------- применить и сохранить ----------
def apply_and_save_photo(con, source_path, params, *, person_id=None, field_name=None, base_dir=None) -> str:
    """Загрузить исходник (относительный — от base_dir/каталога проекта; EXIF-поворот учитывается),
    применить apply_photo_edit, сохранить НОВЫЙ JPEG через save_photo (исходник не перезаписывается).
    field_name (поле data_type='image', нужен person_id) → значение поля; иначе person_id → persons.photo_path.
    Нет записи/поле не image → ValueError (новый файл удаляется). → относительный путь 'photos/…'."""
    import io
    from .photos import abs_path, project_base_dir, save_photo
    base = Path(base_dir) if base_dir else project_base_dir(con)
    if field_name is not None:
        if person_id is None: raise ValueError("field_name требует person_id")
        r = con.execute("SELECT data_type FROM person_fields WHERE name=?", (field_name,)).fetchone()
        if r is None or r[0] != "image": raise ValueError(f"поле «{field_name}» не существует или не типа «изображение»")
    src = abs_path(source_path, base)
    try:
        with Image.open(src) as im: im = ImageOps.exif_transpose(im); im.load()
    except (OSError, ValueError) as e:
        raise ValueError(f"не удалось открыть исходное фото {source_path}: {e}") from None
    out = apply_photo_edit(im, params)
    if out.mode != "RGB":
        bg = Image.new("RGB", out.size, (255, 255, 255))
        o = out.convert("RGBA"); bg.paste(o, mask=o.getchannel("A")); out = bg
    buf = io.BytesIO(); out.save(buf, "JPEG", quality=92)
    rel = save_photo(con, buf.getvalue(), ext="jpg", base_dir=base)
    if person_id is None: return rel
    import json as _j
    row = con.execute("SELECT fields_json FROM persons WHERE id=?", (int(person_id),)).fetchone()
    if row is None:
        (base / rel).unlink(missing_ok=True); raise ValueError(f"нет записи id={person_id}")
    with con:
        if field_name is not None:
            d = _j.loads(row[0] or "{}"); d[field_name] = rel
            con.execute("UPDATE persons SET fields_json=?, updated_at=datetime('now') WHERE id=?",
                        (_j.dumps(d, ensure_ascii=False), int(person_id)))
        else:
            con.execute("UPDATE persons SET photo_path=?, updated_at=datetime('now') WHERE id=?", (rel, int(person_id)))
    return rel
