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


# ---------- режим правки шаблона: черновик через снимок (project_settings, без новой таблицы) ----------
EDIT_KEY = "template_edit_snapshot"
_EL_ALL = ("id", "type", "x", "y", "w", "h", "field_name", "static_value", "style_json", "side", "z_order", "template_id")

def get_template_edit_state(con) -> dict | None:
    """Незавершённая правка шаблона (снимок есть) → {'template_id','name','started_at','elements'} или None.
    При старте UI: не None → спросить «Шаблон не был сохранён. Восстановить прежний или оставить правки?»
    (восстановить = cancel_template_edit, оставить = commit_template_edit)."""
    r = con.execute("SELECT value FROM project_settings WHERE key=?", (EDIT_KEY,)).fetchone()
    if r is None: return None
    s = json.loads(r[0])
    return {"template_id": s["template_id"], "name": s["template"]["name"], "started_at": s["started_at"],
            "elements": len(s["elements"])}

def begin_template_edit(con, template_id: int | None = None) -> dict:
    """«Режим шаблона»: запомнить шаблон целиком (строка templates, все элементы с id и привязками, фоны,
    список существующих полей) в project_settings['template_edit_snapshot']. Правки дальше пишутся в БД как обычно.
    Уже идёт правка → ValueError. → get_template_edit_state."""
    tid = template_id or _db.active_template_id(con)
    t = _need(con, tid)
    if get_template_edit_state(con) is not None: raise ValueError("правка шаблона уже начата — сохраните или отмените её")
    snap = {"template_id": tid, "started_at": _db.now_iso(),
            "template": {k: t[k] for k in ("name", "style_json", "updated_at")},
            "elements": [dict(r) for r in con.execute(f"SELECT {','.join(_EL_ALL)} FROM template_elements WHERE template_id=? "
                                                       "ORDER BY id", (tid,))],
            "backgrounds": [dict(r) for r in con.execute("SELECT side, image_path, color FROM template_backgrounds2 "
                                                          "WHERE template_id=?", (tid,))],
            "fields": [r[0] for r in con.execute("SELECT name FROM person_fields")]}
    with con: con.execute("INSERT INTO project_settings(key, value) VALUES (?, ?)", (EDIT_KEY, json.dumps(snap, ensure_ascii=False)))
    return get_template_edit_state(con)

def commit_template_edit(con) -> dict | None:
    """«✓ Сохранить шаблон» в режиме правки: удалить снимок, обновить updated_at. Режима нет → None.
    → get_template (сохранённый шаблон)."""
    st = get_template_edit_state(con)
    if st is None: return None
    with con:
        con.execute("DELETE FROM project_settings WHERE key=?", (EDIT_KEY,))
        con.execute("UPDATE templates SET updated_at=? WHERE id=?", (_db.now_iso(), st["template_id"]))
    return get_template(con, st["template_id"])

def _field_has_data(con, name):
    return con.execute("SELECT 1 FROM persons WHERE COALESCE(CAST(json_extract(fields_json, ?) AS TEXT), '') <> '' LIMIT 1",
                       ('$."' + name + '"',)).fetchone() is not None

def cancel_template_edit(con) -> dict | None:
    """«Не сохранять»: ОДНОЙ транзакцией вернуть шаблон к снимку (имя, стиль, все элементы с прежними id и
    привязками, фоны) и удалить снимок. Поля, созданные во время правки («Связать» с созданием, авто-«Фото»),
    удаляются, если в записях нет их данных и на них не ссылаются объекты других шаблонов.
    Режима нет → None. → {'template_id', 'removed_fields': [...]}."""
    r = con.execute("SELECT value FROM project_settings WHERE key=?", (EDIT_KEY,)).fetchone()
    if r is None: return None
    s = json.loads(r[0]); tid = s["template_id"]; removed = []
    with con:
        if con.execute("SELECT 1 FROM templates WHERE id=?", (tid,)).fetchone() is not None:
            t = s["template"]
            con.execute("UPDATE templates SET name=?, style_json=?, updated_at=? WHERE id=?",
                        (t["name"], t["style_json"], t["updated_at"], tid))
            con.execute("DELETE FROM template_elements WHERE template_id=?", (tid,))
            for e in s["elements"]:
                con.execute(f"INSERT INTO template_elements({','.join(_EL_ALL)}) VALUES ({','.join('?' * len(_EL_ALL))})",
                            tuple(e[k] for k in _EL_ALL))
            con.execute("DELETE FROM template_backgrounds2 WHERE template_id=?", (tid,))
            for b in s["backgrounds"]:
                con.execute("INSERT INTO template_backgrounds2(template_id, side, image_path, color) VALUES (?,?,?,?)",
                            (tid, b["side"], b["image_path"], b["color"]))
        before = set(s["fields"])
        for (name,) in con.execute("SELECT name FROM person_fields").fetchall():
            if name in before or _field_has_data(con, name): continue
            if con.execute("SELECT 1 FROM template_elements WHERE field_name=? LIMIT 1", (name,)).fetchone(): continue
            con.execute("DELETE FROM person_fields WHERE name=?", (name,)); removed.append(name)
        con.execute("DELETE FROM project_settings WHERE key=?", (EDIT_KEY,))
    return {"template_id": tid, "removed_fields": removed}
