"""Этап 15: несколько шаблонов проекта, активный шаблон, стиль шаблона (шрифт/отступы).

Все записи печатаются на АКТИВНОМ шаблоне (project_settings['active_template_id']); у записи своего шаблона нет.
Элементы и фоны принадлежат шаблону (template_elements.template_id, template_backgrounds2).
"""
from __future__ import annotations
import json
from .. import db as _db

STYLE_KEYS = ("font_family", "padding")   # стиль шаблона по умолчанию; style_json элемента важнее

def _tpl(con, r, active):
    return {"id": r["id"], "name": r["name"], "active": r["id"] == active, "style": json.loads(r["style_json"] or "{}"),
            "elements": con.execute("SELECT COUNT(*) FROM template_elements WHERE template_id=?", (r["id"],)).fetchone()[0],
            "created_at": r["created_at"], "updated_at": r["updated_at"]}

def _need(con, template_id):
    r = con.execute("SELECT * FROM templates WHERE id=?", (int(template_id),)).fetchone()
    if r is None: raise ValueError(f"нет шаблона id={template_id}")
    return r

def _name(name):
    n = str(name or "").strip()
    if not n: raise ValueError("имя шаблона не может быть пустым")
    return n

def list_templates(con) -> list[dict]:
    """→ [{'id','name','active','style','elements','created_at','updated_at'}] по имени (без учёта регистра)."""
    a = _db.active_template_id(con)
    return [_tpl(con, r, a) for r in con.execute("SELECT * FROM templates ORDER BY name COLLATE NOCASE, id")]

def get_template(con, template_id: int | None = None) -> dict:
    """Шаблон по id (None — активный). Нет → ValueError."""
    tid = template_id or _db.active_template_id(con)
    return _tpl(con, _need(con, tid), _db.active_template_id(con))

def get_active_template(con) -> dict:
    return get_template(con, None)

def set_active_template(con, template_id: int) -> bool:
    """Сделать шаблон активным (на нём печатаются все записи). Нет шаблона → ValueError. → True.
    Во время режима правки шаблона (begin_template_edit) сменить активный нельзя → ValueError."""
    _need(con, template_id)
    st = get_template_edit_state(con)
    if st is not None and int(template_id) != _db.active_template_id(con):
        raise ValueError(f"идёт правка шаблона «{st['name']}» — сначала сохраните или отмените её")
    with con: con.execute("INSERT INTO project_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (_db.ACTIVE_KEY, str(int(template_id))))
    return True

def create_template(con, name: str, *, copy_from: int | None = None, activate: bool = False) -> int:
    """Новый шаблон: пустой или копия copy_from (элементы, фоны, стиль). Имя занято/пустое → ValueError. → id."""
    n = _name(name)
    if con.execute("SELECT 1 FROM templates WHERE name=? COLLATE NOCASE", (n,)).fetchone():
        raise ValueError(f"шаблон «{n}» уже есть")
    src = _need(con, copy_from) if copy_from is not None else None
    now = _db.now_iso()
    with con:
        tid = con.execute("INSERT INTO templates(name, style_json, created_at, updated_at) VALUES (?,?,?,?)",
                          (n, src["style_json"] if src else "{}", now, now)).lastrowid
        if src is not None:
            cols = "type,x,y,w,h,field_name,static_value,style_json,side,z_order"
            con.execute(f"INSERT INTO template_elements({cols},template_id) SELECT {cols}, ? FROM template_elements "
                        "WHERE template_id=? ORDER BY id", (tid, src["id"]))
            con.execute("INSERT INTO template_backgrounds2(template_id,side,image_path,color) "
                        "SELECT ?, side, image_path, color FROM template_backgrounds2 WHERE template_id=?", (tid, src["id"]))
    if activate: set_active_template(con, tid)
    return tid

def rename_template(con, template_id: int, name: str) -> bool:
    """Переименовать. Имя занято другим шаблоном → ValueError. → True."""
    _need(con, template_id); n = _name(name)
    if con.execute("SELECT 1 FROM templates WHERE name=? COLLATE NOCASE AND id<>?", (n, int(template_id))).fetchone():
        raise ValueError(f"шаблон «{n}» уже есть")
    with con: con.execute("UPDATE templates SET name=?, updated_at=? WHERE id=?", (n, _db.now_iso(), int(template_id)))
    return True

def delete_template(con, template_id: int) -> bool:
    """Удалить шаблон с его элементами и фонами. Активный или единственный → ValueError. Нет → False."""
    if con.execute("SELECT 1 FROM templates WHERE id=?", (int(template_id),)).fetchone() is None: return False
    st = get_template_edit_state(con)
    if st is not None and st["template_id"] == int(template_id):
        raise ValueError(f"идёт правка шаблона «{st['name']}» — удалить его нельзя")
    if int(template_id) == _db.active_template_id(con): raise ValueError("нельзя удалить активный шаблон — сначала активируйте другой")
    if con.execute("SELECT COUNT(*) FROM templates").fetchone()[0] <= 1: raise ValueError("нельзя удалить единственный шаблон")
    with con:
        con.execute("DELETE FROM template_elements WHERE template_id=?", (int(template_id),))
        con.execute("DELETE FROM template_backgrounds2 WHERE template_id=?", (int(template_id),))
        con.execute("DELETE FROM templates WHERE id=?", (int(template_id),))
    return True

def save_template(con, template_id: int | None = None) -> dict:
    """«✓ Сохранить шаблон»: элементы пишутся в БД сразу при правке, здесь фиксируется updated_at
    и делается commit. → get_template (с числом элементов)."""
    tid = template_id or _db.active_template_id(con); _need(con, tid)
    with con: con.execute("UPDATE templates SET updated_at=? WHERE id=?", (_db.now_iso(), tid))
    return get_template(con, tid)

# ---------- стиль: шрифт / отступы ----------
def _clean_style(style):
    out = {}
    for k, v in (style or {}).items():
        if k not in STYLE_KEYS: raise ValueError(f"неизвестный ключ стиля шаблона {k!r}; допустимо {STYLE_KEYS}")
        if v in (None, ""): out[k] = None; continue
        if k == "padding":
            try: v = int(round(float(v)))
            except (TypeError, ValueError): raise ValueError(f"padding: ожидается число px, получено {v!r}") from None
            if not 0 <= v <= 200: raise ValueError("padding: 0..200 px")
        else: v = str(v).strip()
        out[k] = v
    return out

def get_template_style(con, template_id: int | None = None) -> dict:
    """Стиль шаблона по умолчанию {'font_family'?, 'padding'?} (только заданные ключи)."""
    tid = template_id or _db.active_template_id(con)
    return json.loads(_need(con, tid)["style_json"] or "{}")

def set_template_style(con, style: dict, template_id: int | None = None) -> dict:
    """Слить style в стиль шаблона (значение None/'' — удалить ключ). Ключи: font_family (имя семейства, см.
    list_font_families), padding (px холста 300 DPI, 0..200). Действует на text/field-объекты шаблона,
    у которых в style_json нет своего значения. Неверно → ValueError. → итоговый стиль."""
    tid = template_id or _db.active_template_id(con)
    cur = get_template_style(con, tid)
    for k, v in _clean_style(style).items():
        if v is None: cur.pop(k, None)
        else: cur[k] = v
    with con: con.execute("UPDATE templates SET style_json=?, updated_at=? WHERE id=?",
                          (json.dumps(cur, ensure_ascii=False), _db.now_iso(), tid))
    return cur

def update_element_style(con, element_id: int, **changes) -> dict | None:
    """Слить ключи в style_json объекта (None — удалить ключ; font_family/padding проверяются как у шаблона).
    Нет объекта → None. → итоговый style."""
    r = con.execute("SELECT style_json FROM template_elements WHERE id=?", (int(element_id),)).fetchone()
    if r is None: return None
    st = json.loads(r[0] or "{}")
    chk = _clean_style({k: v for k, v in changes.items() if k in STYLE_KEYS})
    for k, v in changes.items():
        v = chk.get(k, v)
        if v is None: st.pop(k, None)
        else: st[k] = v
    with con: con.execute("UPDATE template_elements SET style_json=? WHERE id=?", (json.dumps(st, ensure_ascii=False), int(element_id)))
    return st

def list_font_families() -> list[str]:
    """Семейства шрифтов, для которых найден TTF (кириллица), для списка «Шрифт»."""
    from ..render.fonts import _FAMILIES, _find
    return [f for f, (reg, _b) in _FAMILIES.items() if _find(reg)]


def get_template_edit_state(con):   # режим правки шаблона — отдельным коммитом
    return None
