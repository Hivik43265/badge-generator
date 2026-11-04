"""Этап 14: редактор фото (бэкенд).

apply_photo_edit(img, params) -> Image             правка фото (вход не изменяется)
detect_face_crop(img, aspect) -> (x,y,w,h)|None    кадр по лицу (OpenCV Haar), w/h == aspect
get_photo_edit_defaults(con) / set_photo_edit_defaults(con, params)   умолчания проекта (project_settings)
apply_and_save_photo(con, source_path, params, *, person_id=None, field_name=None, base_dir=None) -> rel_path
load_photo_for_edit(path, base_dir=None) -> Image   EXIF-поворот + режим (одно место для UI и сохранения)

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
  portrait   bool  галочка «Портрет» (UI: кадрировать по лицу через detect_face_crop); в apply_photo_edit
             не влияет на пиксели, хранится в умолчаниях проекта. Строки "true"/"false"/"1"/"0" принимаются.
Умолчания проекта: project_settings key="photo_edit_defaults", JSON всех ключей кроме crop (=null);
старые значения без "portrait" читаются как portrait=False.
Порядок: autoeffect → brightness → contrast → scale → rotate → crop.
Скорость превью: UI передаёт уменьшенное изображение (crop тогда в его пикселях); при параметрах по
умолчанию возвращается копия без пересчёта.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps, ImageStat

DEFAULT_PHOTO_EDIT = {"brightness": 0, "contrast": 0, "scale": 100, "rotate": 0.0, "crop": None, "autoeffect": False,
                      "portrait": False}
RANGES = {"brightness": (-50, 50), "contrast": (-50, 50), "scale": (10, 400), "rotate": (-180.0, 180.0)}
SETTINGS_KEY = "photo_edit_defaults"


def _clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v

def _to_bool(v):
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ("1", "true", "yes", "on", "да"): return True
        if t in ("", "0", "false", "no", "off", "нет"): return False
        raise ValueError("ожидается bool")
    return bool(v)

def normalize_params(params: dict | None) -> dict:
    """Привести/обрезать параметры к допустимым; None/{} → DEFAULT_PHOTO_EDIT. Нечисло → ValueError."""
    p = dict(DEFAULT_PHOTO_EDIT)
    for k, v in (params or {}).items():
        if k not in p or v is None and k != "crop": continue
        try:
            if k in ("brightness", "contrast", "scale"): p[k] = int(round(_clamp(float(v), *RANGES[k])))
            elif k == "rotate": p[k] = float(_clamp(float(v), *RANGES[k]))
            elif k in ("autoeffect", "portrait"): p[k] = _to_bool(v)
            elif k == "crop":
                if v is None: p[k] = None
                else:
                    x, y, w, h = (int(round(float(t))) for t in v)
                    if w <= 0 or h <= 0: raise ValueError("crop: w и h должны быть > 0")
                    p[k] = (x, y, w, h)
        except (TypeError, ValueError) as e:
            raise ValueError(f"параметр {k}={v!r}: {e}") from None
    return p

def _is_identity(p):  # portrait — флаг UI (галочка «Портрет»), на пиксели не влияет
    return {**p, "portrait": False} == DEFAULT_PHOTO_EDIT

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
HEAD_TOP = 0.25     # макушка = верх Haar − HEAD_TOP·fh (Haar начинается ото лба)
HEAD_SHARE = 0.50   # голова (макушка..подбородок = низ Haar) занимает ~50 % высоты рамки (45–55 %)
HEADROOM = 0.10     # запас над макушкой — 10 % высоты рамки; ниже подбородка ~40 % (шея, плечи)

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
    """Рамка (x, y, w, h) в пикселях img по самому крупному лицу; нет лица → None. D40/D42 (слова Ивана:
    «рамка не должна полностью брать лицо, учитывается размер рамки в шаблоне»).
    aspect = w/h фото-элемента шаблона (см. get_photo_frame_spec()['aspect']).
    Макушка = верх Haar − HEAD_TOP·fh; подбородок ≈ низ прямоугольника Haar. Голова занимает HEAD_SHARE
    высоты рамки, над макушкой HEADROOM высоты, остальное (~40 %) — шея и плечи. Лицо по центру по горизонтали.
    Рамка за краем фото: сначала сдвиг внутрь; если рамка больше фото — уменьшение (aspect сохраняется,
    центр по горизонтали — лицо, верх — по возможности на месте) и снова сдвиг."""
    import numpy as np
    aspect = float(aspect)
    if not aspect > 0: raise ValueError("aspect должен быть > 0")
    g = np.asarray(img.convert("L"))
    m = max(20, min(g.shape) // 12)
    faces = _classifier().detectMultiScale(g, scaleFactor=1.1, minNeighbors=5, minSize=(m, m))
    if len(faces) == 0: return None
    fx, fy, fw, fh = (float(v) for v in max(faces, key=lambda f: int(f[2]) * int(f[3])))
    iw, ih = img.width, img.height
    head_top = fy - HEAD_TOP * fh; head_h = fy + fh - head_top
    H = head_h / HEAD_SHARE; W = H * aspect
    cx = fx + fw / 2; y = head_top - HEADROOM * H
    k = min(1.0, iw / W, ih / H)          # сдвиг не помогает только если рамка больше фото
    if k < 1.0: W *= k; H *= k
    x = _clamp(cx - W / 2, 0, iw - W); y = _clamp(y, 0, ih - H)
    h = max(1, min(ih, int(round(H)))); w = max(1, int(round(h * aspect)))
    if w > iw: w = iw; h = max(1, min(ih, int(round(w / aspect))))
    x = int(_clamp(round(x), 0, iw - w)); y = int(_clamp(round(y), 0, ih - h))
    return (x, y, w, h)

# ---------- рамка из шаблона ----------
def get_photo_frame_spec(con, field=None):
    """Пропорции и размер выходного фото для image-поля (D42).
    field: имя поля (str) или rowid (int) из person_fields; None — фото записи: этап 15 — объект, связанный
    с полем «Фото», иначе несвязанный фото-объект. Только АКТИВНЫЙ шаблон. Берётся первый фото-элемент:
    сначала лицевая сторона, затем z_order, id. Размеры элемента в px холста 300 DPI → мм = px·25.4/300.
    → {'aspect': w/h, 'width_mm', 'height_mm', 'width_px', 'height_px' (300 DPI, округл.), 'element_id', 'side'}
    Нет связанного элемента (или поле не image / не найдено) → None: редактор работает без фикс. пропорций."""
    from .. import DPI
    name = None
    if field is not None:
        col = "rowid" if isinstance(field, int) and not isinstance(field, bool) else "name"
        r = con.execute(f"SELECT name, data_type FROM person_fields WHERE {col}=?", (field,)).fetchone()
        if r is None or r[1] != "image": return None
        name = r[0]
    from ..db import active_template_id, PHOTO_FIELD
    tid = active_template_id(con)
    if name is not None:
        r = con.execute("SELECT id, w, h, side FROM template_elements WHERE type='photo' AND template_id=? AND field_name=? "
                        "ORDER BY side<>'front', z_order, id LIMIT 1", (tid, name)).fetchone()
    else:   # этап 15 (п.7): сначала объект, связанный с полем «Фото», затем несвязанный; только активный шаблон
        r = con.execute("SELECT id, w, h, side FROM template_elements WHERE type='photo' AND template_id=? "
                        "AND (COALESCE(field_name, '')='' OR field_name=?) "
                        "ORDER BY COALESCE(field_name, '')<>?, side<>'front', z_order, id LIMIT 1",
                        (tid, PHOTO_FIELD, PHOTO_FIELD)).fetchone()
    if r is None: return None
    eid, w, h, side = r
    wmm, hmm = w * 25.4 / DPI, h * 25.4 / DPI
    return {"aspect": w / h, "width_mm": round(wmm, 2), "height_mm": round(hmm, 2),
            "width_px": int(round(wmm / 25.4 * DPI)), "height_px": int(round(hmm / 25.4 * DPI)),
            "element_id": eid, "side": side}

def photo_edit_target(con, field_name):
    """Цель редактора фото (имя согласовано с Frontend): get_photo_frame_spec + 'size': (width_px, height_px).
    Нет связанного фото-элемента → None."""
    s = get_photo_frame_spec(con, field_name)
    if s is None: return None
    s["size"] = (s["width_px"], s["height_px"]); return s

from .photos import PhotoSession, discard_photo  # noqa: E402,F401  (D43, ре-экспорт)

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

# ---------- загрузка ----------
def load_photo_for_edit(path, base_dir=None) -> Image.Image:
    """Открыть фото для редактора/сохранения: относительный путь — от base_dir (иначе cwd), EXIF-поворот
    (ImageOps.exif_transpose), режим → RGB (прозрачность → RGBA, оттенки серого → L). Файл закрывается.
    Нет файла/не картинка → ValueError. Единая точка для UI-превью и apply_and_save_photo."""
    from .photos import abs_path
    src = abs_path(path, base_dir)
    if src is None: raise ValueError("путь к фото пуст")
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im); im.load()
    except (OSError, ValueError, SyntaxError) as e:
        raise ValueError(f"не удалось открыть фото {path}: {e}") from None
    if im.mode in ("RGB", "L", "RGBA"): return im
    has_alpha = im.mode in ("LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    return im.convert("RGBA" if has_alpha else "L" if im.mode in ("1", "I", "I;16", "F") else "RGB")

# ---------- применить и сохранить ----------
def apply_and_save_photo(con, source_path, params, *, person_id=None, field_name=None, base_dir=None,
                         size=None, target_field=None) -> str:
    """Загрузить исходник (относительный — от base_dir/каталога проекта; EXIF-поворот учитывается),
    применить apply_photo_edit, сохранить НОВЫЙ JPEG через save_photo (исходник не перезаписывается).
    field_name (поле data_type='image', нужен person_id) → значение поля; иначе person_id → persons.photo_path.
    Нет записи/поле не image → ValueError (новый файл удаляется). → относительный путь 'photos/…'.
    D44: size=(w, h) — итоговый размер в px; target_field — имя image-поля;
    размер берётся из photo_edit_target(con, target_field)['size'] (нет элемента → без ресайза).
    size важнее target_field. Результат приводится ровно к size (LANCZOS), даже если пропорции не совпадают
    (кадр должен уже иметь aspect рамки — тогда искажения нет). Без size/target_field — как раньше."""
    import io
    from .photos import project_base_dir, save_photo
    base = Path(base_dir) if base_dir else project_base_dir(con)
    if field_name is not None:
        if person_id is None: raise ValueError("field_name требует person_id")
        r = con.execute("SELECT data_type FROM person_fields WHERE name=?", (field_name,)).fetchone()
        if r is None or r[0] != "image": raise ValueError(f"поле «{field_name}» не существует или не типа «изображение»")
    if size is None and target_field is not None:
        t = photo_edit_target(con, target_field)
        if t is not None: size = t["size"]
    if size is not None:
        size = (int(size[0]), int(size[1]))
        if size[0] <= 0 or size[1] <= 0: raise ValueError("size должен быть > 0")
    out = apply_photo_edit(load_photo_for_edit(source_path, base), params)
    if size is not None and out.size != size: out = out.resize(size, Image.LANCZOS)
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
            con.execute("UPDATE persons SET fields_json=?, updated_at=? WHERE id=?",
                        (_j.dumps(d, ensure_ascii=False), _now(), int(person_id)))
        else:
            con.execute("UPDATE persons SET photo_path=?, updated_at=? WHERE id=?", (rel, _now(), int(person_id)))
    return rel


def _now():
    from ..db import now_iso
    return now_iso()

# ---------- этап 15: вид фото записи (исходник не меняется) ----------
def _view_key(con, field_name):
    if field_name in (None, ""): return ""
    r = con.execute("SELECT data_type FROM person_fields WHERE name=?", (field_name,)).fetchone()
    if r is None or r[0] != "image": raise ValueError(f"поле «{field_name}» не существует или не типа «изображение»")
    return field_name

def get_photo_view(con, person_id: int, field_name: str | None = None) -> dict:
    """Параметры вида фото записи (кадр, масштаб, поворот, яркость, контраст, флаги) для image-поля
    (None — persons.photo_path). Не сохранены → умолчания проекта (crop=None). Всегда нормализованы.
    Нет записи → ValueError."""
    key = _view_key(con, field_name)
    if con.execute("SELECT 1 FROM persons WHERE id=?", (int(person_id),)).fetchone() is None:
        raise ValueError(f"нет записи id={person_id}")
    r = con.execute("SELECT params_json FROM person_photo_views WHERE person_id=? AND field_name=?",
                    (int(person_id), key)).fetchone()
    if r is None: return get_photo_edit_defaults(con)
    try: return normalize_params(json.loads(r[0]))
    except (ValueError, TypeError): return get_photo_edit_defaults(con)

def set_photo_view(con, person_id: int, params: dict | None, field_name: str | None = None) -> dict:
    """Сохранить вид фото записи (нормализованный). Файл фото НЕ создаётся и НЕ меняется: рендер/печать/экспорт
    применяют параметры к исходнику в памяти. crop — (x,y,w,h) в px исходника после scale/rotate
    (как apply_photo_edit). params=None — удалить вид (вернуться к умолчаниям). → сохранённое."""
    key = _view_key(con, field_name)
    if con.execute("SELECT 1 FROM persons WHERE id=?", (int(person_id),)).fetchone() is None:
        raise ValueError(f"нет записи id={person_id}")
    with con:
        if params is None:
            con.execute("DELETE FROM person_photo_views WHERE person_id=? AND field_name=?", (int(person_id), key))
            return get_photo_edit_defaults(con)
        p = normalize_params(params)
        con.execute("INSERT INTO person_photo_views(person_id, field_name, params_json, updated_at) VALUES (?,?,?,?) "
                    "ON CONFLICT(person_id, field_name) DO UPDATE SET params_json=excluded.params_json, updated_at=excluded.updated_at",
                    (int(person_id), key, json.dumps(p), _now()))
    return p

def render_photo(con, person_id: int, field_name: str | None = None, *, size=None, base_dir=None):
    """Фото записи с применённым видом (в памяти) → PIL.Image; size=(w,h) — cover в этот размер
    (None — размер кадра). Исходник — значение image-поля, иначе persons.photo_path. Нет фото → ValueError."""
    from .photos import resolve_photo_path, project_base_dir
    r = con.execute("SELECT * FROM persons WHERE id=?", (int(person_id),)).fetchone()
    if r is None: raise ValueError(f"нет записи id={person_id}")
    base = Path(base_dir) if base_dir else project_base_dir(con)
    src = resolve_photo_path(dict(r), field_name or None, base)
    if src is None: raise ValueError("у записи нет фото")
    im = apply_photo_edit(load_photo_for_edit(src), get_photo_view(con, person_id, field_name))
    if size is not None:
        w, h = int(size[0]), int(size[1])
        if w <= 0 or h <= 0: raise ValueError("size должен быть > 0")
        im = ImageOps.fit(im, (w, h), Image.LANCZOS)
    return im

def portrait_params(img: Image.Image, aspect: float, params: dict | None = None) -> dict | None:
    """«Портрет»: кадр по лицу (detect_face_crop, правило D42) для изображения ПОСЛЕ scale/rotate из params.
    → полный нормализованный набор параметров с crop=(x,y,w,h) и portrait=True (значения — в ползунки);
    лицо не найдено → None. Пиксели не меняются."""
    p = normalize_params(params)
    base = apply_photo_edit(img, {**p, "crop": None, "autoeffect": False, "brightness": 0, "contrast": 0})
    box = detect_face_crop(base, aspect)
    if box is None: return None
    p["crop"] = tuple(int(v) for v in box); p["portrait"] = True
    return p

def autoeffect_params(img: Image.Image, params: dict | None = None) -> dict:
    """«Автоэффект»: подобрать яркость и контраст по изображению и вернуть их как ЗНАЧЕНИЯ ползунков.
    → полный нормализованный набор с brightness/contrast (-50..50) и autoeffect=False (эффект уже выражен
    ползунками — повторно не применяется). Остальные ключи params сохраняются."""
    p = normalize_params(params)
    g = img.convert("L"); hist = g.histogram(); n = sum(hist) or 1
    lo = hi = None; acc = 0
    for i, c in enumerate(hist):
        acc += c
        if lo is None and acc > n * 0.01: lo = i
        if hi is None and acc >= n * 0.99: hi = i
    lo, hi = lo or 0, hi if hi is not None else 255
    contrast = (255.0 / max(1, hi - lo) - 1) * 100
    mean = ImageStat.Stat(g).mean[0] or 1.0
    brightness = (128.0 / mean - 1) * 100
    p["contrast"] = int(round(_clamp(contrast, *RANGES["contrast"])))
    p["brightness"] = int(round(_clamp(brightness, *RANGES["brightness"])))
    p["autoeffect"] = False
    return p
