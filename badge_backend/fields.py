"""D24: типы полей person_fields.data_type и преобразование значений.

FIELD_TYPES = text | number | date | image | bool (по умолчанию text).
normalize_value(data_type, value) -> (хранимое значение, None | текст ошибки)
    text   — как есть;
    number — '1 234,5' → '1234.5', целые без '.0'; не число → ошибка;
    date   — хранится ISO 'YYYY-MM-DD'; принимается 'YYYY-MM-DD', 'DD.MM.YYYY' (и 'D.M.YYYY'), date/datetime;
    bool   — '1'/'0'; принимается 1/0, да/нет, true/false, yes/no, x/+/-, истина/ложь;
    image  — путь к файлу (значение поля = persons.photo_path записи).
Пустое значение ('' / None) — всегда допустимо и хранится как ''.
format_value(field, value) — строка для показа/рендера: date → 'DD.MM.YYYY', bool → 'Да'/'Нет', иначе str(value).
"""
from __future__ import annotations
import datetime as _dt
import re

FIELD_TYPES = ("text", "number", "date", "image", "bool")
_TRUE = {"1", "да", "true", "yes", "y", "x", "+", "истина", "д"}
_FALSE = {"0", "нет", "false", "no", "n", "-", "ложь", "н"}

class FieldValueWarning(UserWarning):
    """Значение не соответствует data_type поля (create/update_person сохраняют его как есть)."""

def check_type(data_type) -> str:
    dt = (data_type or "text").strip().lower()
    if dt not in FIELD_TYPES: raise ValueError(f"неизвестный тип поля: {data_type!r} (допустимо: {', '.join(FIELD_TYPES)})")
    return dt

def normalize_value(data_type, value):
    if value is None: return "", None
    if isinstance(value, bool): value = "1" if value else "0"
    dt = check_type(data_type)
    if isinstance(value, _dt.datetime) and dt == "date": return value.date().isoformat(), None
    if isinstance(value, _dt.date) and dt == "date": return value.isoformat(), None
    s = str(value).strip()
    if s == "": return "", None
    if dt in ("text", "image"): return (str(value) if dt == "text" else s), None
    if dt == "number":
        t = re.sub(r"[\s\u00a0]", "", s).replace(",", ".")
        try: f = float(t)
        except ValueError: return s, f"не число: {s!r}"
        if f != f or f in (float("inf"), float("-inf")): return s, f"не число: {s!r}"
        return (str(int(f)) if f.is_integer() and "e" not in t.lower() and abs(f) < 1e15 else t), None
    if dt == "date":
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", s) or None
        try:
            if m: d = _dt.date(int(m[1]), int(m[2]), int(m[3]))
            else:
                m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
                if not m: return s, f"не дата (ожидается ДД.ММ.ГГГГ): {s!r}"
                d = _dt.date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError: return s, f"несуществующая дата: {s!r}"
        return d.isoformat(), None
    k = s.lower()   # bool
    if k in _TRUE: return "1", None
    if k in _FALSE: return "0", None
    return s, f"не логическое значение (да/нет): {s!r}"

def format_value(field, value) -> str:
    """field — dict поля (с 'data_type') или строка типа. None → ''."""
    dt = field.get("data_type") if isinstance(field, dict) else field
    if value is None: return ""
    dt = (dt or "text").lower()
    if dt == "date":
        v, err = normalize_value("date", value)
        if not err and v: y, m, d = v.split("-"); return f"{d}.{m}.{y}"
        return str(value)
    if dt == "bool":
        v, err = normalize_value("bool", value)
        return {"1": "Да", "0": "Нет"}.get(v, str(value)) if not err else str(value)
    return str(value)
