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
  crop       (x,y,w,h) | None — координаты в пикселях изображения ПОСЛЕ scale и rotate
             (и ПОСЛЕ EXIF-поворота при загрузке), но ДО brightness/contrast (они геометрию не меняют).
             Не в пикселях исходного файла, если scale≠100 или rotate≠0.
             Обрезается границами этого преобразованного изображения; пустое пересечение → ValueError.
             Формат хранения не менять: JSON-массив/кортеж из четырёх чисел (x, y, w, h).
  autoeffect bool  галочка «Автоэффект» — только маркер UI (как portrait). apply_photo_edit и рендер
             карточки флаг ИГНОРИРУЮТ: пиксельный эффект уже записан в brightness/contrast
             (их подбирает autoeffect_params). Повторно autocontrast не применяется.
  portrait   bool  галочка «Портрет» — только маркер UI; в apply_photo_edit на пиксели не влияет.
             Кадр по лицу пишет portrait_params в crop. Строки "true"/"false"/"1"/"0" принимаются.
Умолчания проекта: project_settings key="photo_edit_defaults", JSON всех ключей кроме crop (=null);
старые значения без "portrait" читаются как portrait=False.
Порядок правки пикселей: brightness → contrast → scale → rotate → crop.
После «Портрет»/«Автоэффект» флаг в возвращённых/сохранённых params остаётся True (маркер для UI);
сброс при ручном движении ползунка — на стороне UI.
Скорость превью: UI передаёт уменьшенное изображение (crop тогда в его пикселях); при параметрах по
умолчанию возвращается копия без пересчёта.
"""
from __future__ import annotations
import json, logging, os, sys
from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps, ImageStat
log = logging.getLogger(__name__)

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
    if (params or {}).get("placement"):   # этап 15: перенесённый photo_config (x;y;scale;crop_x;crop_y;angle)
        from ..photo_config import normalize as _pc_norm
        p["placement"] = _pc_norm(params["placement"])
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

def _is_identity(p):  # portrait/autoeffect — флаги UI; placement — перенесённый photo_config
    q = {**p, "portrait": False, "autoeffect": False}; q.pop("placement", None)
    return q == DEFAULT_PHOTO_EDIT

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
    # autoeffect и portrait — маркеры UI, на пиксели не влияют
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
HEAD_TOP = 0.50     # макушка = верх Haar − HEAD_TOP·fh (Haar идёт от бровей, не от макушки)
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

DETECT_MAX_SIDE = 800   # Haar на уменьшенной копии; тестовые фикстуры ≤800 px не масштабируются

def detect_face_crop(img: Image.Image, aspect: float):
    """Рамка (x, y, w, h) в пикселях img по самому крупному лицу; нет лица → None. D40/D42 (слова Ивана:
    «рамка не должна полностью брать лицо, учитывается размер рамки в шаблоне»).
    aspect = w/h фото-элемента шаблона (см. get_photo_frame_spec()['aspect']).
    Макушка = верх Haar − HEAD_TOP·fh; подбородок ≈ низ прямоугольника Haar. Голова занимает HEAD_SHARE
    высоты рамки, над макушкой HEADROOM высоты, остальное (~40 %) — шея и плечи. Лицо по центру по горизонтали.
    Рамка за краем фото: сначала сдвиг внутрь; если рамка больше фото — уменьшение (aspect сохраняется,
    центр по горизонтали — лицо, верх — по возможности на месте) и снова сдвиг.
    Поиск лица — на копии не шире DETECT_MAX_SIDE (рамка пересчитывается в пиксели img)."""
    import numpy as np
    aspect = float(aspect)
    if not aspect > 0: raise ValueError("aspect должен быть > 0")
    iw, ih = img.width, img.height
    gray = img if img.mode == "L" else img.convert("L")
    max_side = max(iw, ih)
    if max_side > DETECT_MAX_SIDE:
        k = DETECT_MAX_SIDE / max_side
        det = gray.resize((max(1, round(iw * k)), max(1, round(ih * k))), Image.BILINEAR)
        back = 1.0 / k
    else:
        det, back = gray, 1.0
    g = np.asarray(det)
    m = max(20, min(g.shape) // 12)
    faces = _classifier().detectMultiScale(g, scaleFactor=1.1, minNeighbors=5, minSize=(m, m))
    if len(faces) == 0: return None
    fx, fy, fw, fh = (float(v) * back for v in max(faces, key=lambda f: int(f[2]) * int(f[3])))
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
def _frame_spec(eid, w, h, side):
    from .. import DPI
    wmm, hmm = w * 25.4 / DPI, h * 25.4 / DPI
    return {"aspect": w / h, "width_mm": round(wmm, 2), "height_mm": round(hmm, 2),
            "width_px": int(round(wmm / 25.4 * DPI)), "height_px": int(round(hmm / 25.4 * DPI)),
            "element_id": eid, "side": side}

def get_photo_frame_spec(con, field=None, *, element_id=None, field_name=None):
    """Пропорции рамки фото-элемента активного шаблона (D42, этап 15 B5).

    element_id  id элемента (двойной щелчок). Должен быть type='photo' на АКТИВНОМ шаблоне,
                иначе ValueError. Если задан — field/field_name не используются.
    field / field_name  (устарели) имя image-поля (str) или rowid (int) из person_fields.
                Первый фото-элемент этого поля на активном шаблоне (front, z_order, id).
                Поле не найдено / не image / нет элемента → None.
    без них     первый фото-элемент активного шаблона: side='front' раньше оборота,
                затем z_order, id. Предпочтения поля «Фото» нет. Нет фото-элементов → None.

    Размеры элемента в px холста 300 DPI → мм = px·25.4/300.
    → {'aspect': w/h, 'width_mm', 'height_mm', 'width_px', 'height_px' (300 DPI, округл.), 'element_id', 'side'}
    """
    from ..db import active_template_id
    tid = active_template_id(con)
    if element_id is not None:
        r = con.execute("SELECT id, type, w, h, side, template_id FROM template_elements WHERE id=?",
                        (int(element_id),)).fetchone()
        if r is None:
            raise ValueError(f"нет элемента id={element_id}")
        eid, typ, w, h, side, etid = r[0], r[1], r[2], r[3], r[4], r[5]
        if typ != "photo":
            raise ValueError(f"элемент id={element_id} имеет тип «{typ}», нужен «photo»")
        if etid != tid:
            raise ValueError(f"элемент id={element_id} не на активном шаблоне")
        return _frame_spec(eid, w, h, side)
    if field is None: field = field_name
    name = None
    if field is not None:
        col = "rowid" if isinstance(field, int) and not isinstance(field, bool) else "name"
        r = con.execute(f"SELECT name, data_type FROM person_fields WHERE {col}=?", (field,)).fetchone()
        if r is None or r[1] != "image": return None
        name = r[0]
        r = con.execute("SELECT id, w, h, side FROM template_elements WHERE type='photo' AND template_id=? AND field_name=? "
                        "ORDER BY side<>'front', z_order, id LIMIT 1", (tid, name)).fetchone()
    else:
        r = con.execute("SELECT id, w, h, side FROM template_elements WHERE type='photo' AND template_id=? "
                        "ORDER BY side<>'front', z_order, id LIMIT 1", (tid,)).fetchone()
    if r is None: return None
    return _frame_spec(r[0], r[1], r[2], r[3])

def photo_edit_target(con, field_name=None, *, element_id=None, field=None):
    """Цель редактора фото: get_photo_frame_spec + 'size': (width_px, height_px).
    element_id — как в get_photo_frame_spec (ValueError, если не фото активного шаблона).
    field_name / field — устаревшие (имя или rowid image-поля). Нет элемента → None."""
    s = get_photo_frame_spec(con, field if field is not None else field_name, element_id=element_id)
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
    from .photos import abs_path, open_photo_file, open_photo_bytes, photo_image_bytes
    blob = photo_image_bytes(path)
    if blob is not None:
        try:
            im = open_photo_bytes(blob)
        except (OSError, ValueError, SyntaxError) as e:
            raise ValueError(f"не удалось открыть фото {path}: {e}") from None
    else:
        src = abs_path(path, base_dir)
        if src is None: raise ValueError("путь к фото пуст")
        try:
            im = open_photo_file(src)
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
    (None — persons.photo_path). Не сохранены → умолчания проекта (crop=None). Всегда нормализованы
    (нет ключа portrait → False). crop — (x,y,w,h) в px после scale/rotate, см. docstring модуля.
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
    применяют параметры к исходнику в памяти. crop — (x,y,w,h) в пикселях изображения ПОСЛЕ scale и rotate
    (не исходного файла, если scale≠100 или rotate≠0); формат не менять. params=None — удалить вид
    (вернуться к умолчаниям). → сохранённое."""
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

_VIEW_OVERSAMPLE = 1.25   # запас пикселей над рамкой, чтобы cover/LANCZOS не мылил печать 300 DPI

def _src_for_frame(src: Image.Image, p: dict, w: int, h: int):
    """Уменьшить исходник так, чтобы после scale/crop размер был чуть больше рамки w×h.
    crop задан в координатах после scale/rotate — умножается на тот же коэффициент.
    placement не трогаем: его координаты привязаны к полному результату apply_photo_edit."""
    p = dict(p)
    sc = (p.get("scale") or 100) / 100.0
    if p.get("crop"):
        cw, ch = float(p["crop"][2]), float(p["crop"][3])
    else:
        cw, ch = src.width * sc, src.height * sc
    cw, ch = max(1.0, cw), max(1.0, ch)
    need = max(w / cw, h / ch) * _VIEW_OVERSAMPLE
    if need >= 0.99:
        return src, p
    nw, nh = max(1, round(src.width * need)), max(1, round(src.height * need))
    if nw >= src.width and nh >= src.height:
        return src, p
    src2 = src.resize((nw, nh), Image.BILINEAR)
    if p.get("crop"):
        x, y, cw, ch = p["crop"]
        p["crop"] = (int(round(x * need)), int(round(y * need)),
                     max(1, int(round(cw * need))), max(1, int(round(ch * need))))
    return src2, p

def apply_photo_view(src: Image.Image, w: int, h: int, params: dict | None) -> Image.Image:
    """Единственный путь рендера фото в рамку w×h (общий с карточкой): apply_photo_edit к исходнику
    в памяти, затем 'placement' (перенесённый photo_config) через transform_photo, без него — cover w×h.
    Без placement исходник заранее уменьшается до размера рамки (печать остаётся в 300 DPI рамки)."""
    from ..render import transform_photo, _cover_crop
    params = dict(params or {}); placement = params.pop("placement", None)
    try:
        work, p = (src, params) if placement else _src_for_frame(src, normalize_params(params), w, h)
        im = apply_photo_edit(work, p)
    except ValueError as e:
        log.warning("вид фото не применён (%s) — исходник целиком", e); im = src
    if placement:
        return transform_photo(im, w, h, placement)
    return _cover_crop(im.convert("RGBA"), w, h)


def render_photo(con, person_id: int, field_name: str | None = None, *, size=None, base_dir=None):
    """Фото записи с применённым видом (в памяти) → PIL.Image; size=(w,h) — в этот размер тем же
    путём, что фото на карточке (apply_photo_view: placement / cover). None — после apply_photo_edit
    без вписывания в рамку. Исходник — значение image-поля, иначе persons.photo_path. Нет фото → ValueError."""
    from .photos import resolve_photo_path, project_base_dir
    r = con.execute("SELECT * FROM persons WHERE id=?", (int(person_id),)).fetchone()
    if r is None: raise ValueError(f"нет записи id={person_id}")
    base = Path(base_dir) if base_dir else project_base_dir(con)
    src = resolve_photo_path(dict(r), field_name or None, base)
    if src is None: raise ValueError("у записи нет фото")
    src_im = load_photo_for_edit(src)
    params = get_photo_view(con, person_id, field_name)
    if size is not None:
        w, h = int(size[0]), int(size[1])
        if w <= 0 or h <= 0: raise ValueError("size должен быть > 0")
        return apply_photo_view(src_im, w, h, params)
    return apply_photo_edit(src_im, params)

def portrait_params(img: Image.Image, aspect: float, params: dict | None = None) -> dict | None:
    """«Портрет»: кадр по лицу (detect_face_crop, правило D42) для изображения ПОСЛЕ scale/rotate из params.
    → полный нормализованный набор с crop=(x,y,w,h) в тех же координатах (после scale/rotate) и
    portrait=True (маркер UI, рендер флаг игнорирует). Лицо не найдено → None. Пиксели не меняются."""
    p = normalize_params(params)
    geo = {**p, "crop": None, "autoeffect": False, "brightness": 0, "contrast": 0}
    iw, ih = img.width, img.height
    max_side = max(iw, ih)
    if max_side > DETECT_MAX_SIDE:
        k = DETECT_MAX_SIDE / max_side
        work = img.resize((max(1, round(iw * k)), max(1, round(ih * k))), Image.BILINEAR)
        base = apply_photo_edit(work, geo)
        box = detect_face_crop(base, aspect)
        if box is None: return None
        box = tuple(int(round(v / k)) for v in box)
    else:
        base = apply_photo_edit(img, geo)
        box = detect_face_crop(base, aspect)
        if box is None: return None
    p["crop"] = tuple(int(v) for v in box); p["portrait"] = True
    return p

def autoeffect_params(img: Image.Image, params: dict | None = None) -> dict:
    """«Автоэффект»: подобрать яркость и контраст по изображению и вернуть их как ЗНАЧЕНИЯ ползунков.
    → полный нормализованный набор с brightness/contrast (-50..50) и autoeffect=True (маркер UI;
    рендер флаг игнорирует — повторно autocontrast не применяется). Остальные ключи params сохраняются."""
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
    p["autoeffect"] = True
    return p


def get_photo_editor_state(con, person_id: int, element_id=None) -> dict:
    """Всё, что нужно редактору фото при открытии: сохранённые ползунки/кадр, рамка, исходник.

    person_id     запись. Нет записи → ValueError.
    element_id    фото-элемент активного шаблона (как get_photo_frame_spec). None — первый
                  фото-элемент активного шаблона (front, z_order, id). Не photo / другой шаблон
                  / нет такого id → ValueError. Нет ни одного фото-элемента и element_id не задан
                  → frame=None, вид берётся для persons.photo_path (field_name пустой).

    → {
        'params':      нормализованный вид (get_photo_view); нет portrait → False;
                       crop=(x,y,w,h) в px после scale/rotate (см. docstring модуля);
        'frame':       get_photo_frame_spec + 'size', либо None;
        'photo_path':  относительный путь исходника в проекте (поле элемента или photo_path),
                       либо None, если у записи нет фото. Файл на диске не меняется;
        'element_id':  id использованного элемента или None;
        'field_name':  имя image-поля элемента (None, если объект не привязан — тогда вид '').
      }
    """
    if con.execute("SELECT 1 FROM persons WHERE id=?", (int(person_id),)).fetchone() is None:
        raise ValueError(f"нет записи id={person_id}")
    fname = None; eid = None; frame = None
    if element_id is not None:
        frame = photo_edit_target(con, element_id=element_id)
        eid = int(element_id)
        r = con.execute("SELECT field_name FROM template_elements WHERE id=?", (eid,)).fetchone()
        fname = (r[0] if r and r[0] else None)
    else:
        frame = photo_edit_target(con)
        if frame is not None:
            eid = frame["element_id"]
            r = con.execute("SELECT field_name FROM template_elements WHERE id=?", (eid,)).fetchone()
            fname = (r[0] if r and r[0] else None)
    params = get_photo_view(con, person_id, fname)
    row = con.execute("SELECT fields_json, photo_path FROM persons WHERE id=?", (int(person_id),)).fetchone()
    stored = None
    if fname:
        try: fields = json.loads(row[0] or "{}")
        except (TypeError, ValueError): fields = {}
        stored = fields.get(fname) or None
    if not stored:
        stored = row[1] or None
    if stored in ("", None): stored = None
    return {"params": params, "frame": frame, "photo_path": stored,
            "element_id": eid, "field_name": fname}
