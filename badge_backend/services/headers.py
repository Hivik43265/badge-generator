"""Единый модуль маппинга заголовков Excel/CSV → ключи persons.fields_json.

Публичные функции (их может вызывать data_tools):
    header_key(s)                 нормализация заголовка для сравнения
    slugify(s)                    транслит+slug для неизвестных заголовков ('Табельный №' → 'tabelnyy_n')
    map_headers(headers, mapping=None) -> list[str|None]   ключ для каждой колонки
    split_fio(value) -> (last, first, middle)
Специальные ключи: '__fio__' (ФИО делится на last_name/first_name/middle_name),
'photo_path', 'photo_config' (идут в одноимённые колонки persons, не в fields_json).
"""
import re
SYNONYMS = {
    "last_name": ["last_name", "фамилия", "surname", "last name", "lastname"],
    "first_name": ["first_name", "имя", "name", "first name", "firstname"],
    "middle_name": ["middle_name", "отчество", "patronymic", "middle name"],
    "position": ["position", "должность", "title", "job title"],
    "department": ["department", "отдел", "подразделение", "dept"],
    "photo_path": ["photo_path", "photo", "фото", "файл фото", "путь к фото", "фотография"],
    "email": ["email", "e-mail", "почта", "эл. почта", "электронная почта", "mail"],
    "phone": ["phone", "телефон", "тел", "тел.", "мобильный"],
    "photo_config": ["photo_config", "настройки фото"],
    "employee_id": ["employee_id", "табельный номер", "таб. номер", "таб №", "табельный №", "id сотрудника"],
    # D28: служебные колонки печати (xlsx/xls/csv) → persons.print_mark / printed_at, не поля
    "print_mark": ["print_mark", "отметка печати", "в очереди печати"],
    "printed": ["printed", "напечатано"],
    "printed_at": ["printed_at", "дата печати"],
    "__fio__": ["фио", "ф.и.о.", "фамилия имя отчество", "full name", "full_name", "fullname"],
}
SERVICE_KEYS = ("photo_path", "photo_config", "print_mark", "printed", "printed_at")
LABELS = {"last_name": "Фамилия", "first_name": "Имя", "middle_name": "Отчество", "position": "Должность",
          "department": "Отдел", "email": "Email", "phone": "Телефон", "employee_id": "Табельный номер"}
_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщыэюя",
    "a b v g d e e zh z i y k l m n o p r s t u f kh ts ch sh shch y e yu ya".split()))
_TR.update({"ъ": "", "ь": ""})

def header_key(s) -> str:
    s = "" if s is None else str(s)
    return re.sub(r"\s+", " ", s).strip().lower().replace("_", " ").replace("ё", "е")

def slugify(s) -> str:
    t = "".join(_TR.get(c, c) for c in str(s or "").lower().replace("№", "n"))
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    t = re.sub(r"_+", "_", t)
    return t or "field"

CANONICAL = set(SYNONYMS) - {"__fio__"}

def split_mapping(mapping):
    """Разделить mapping на (synonyms {field: [заголовки]}, explicit {header_key: field|None}).
    Значение-список/кортеж → синонимы поля (старый формат). Значение-строка → колонка с этим
    заголовком назначается на поле; None или '' → колонка исключается."""
    syn, explicit = {}, {}
    for k, v in (mapping or {}).items():
        if isinstance(v, (list, tuple, set)): syn[k] = list(v)
        elif v is None or (isinstance(v, str) and not v.strip()): explicit[header_key(k)] = None
        else: explicit[header_key(k)] = str(v).strip()
    return syn, explicit

def map_headers(headers, mapping: dict | None = None) -> list:
    """Вернуть ключ для каждой колонки (None — колонка игнорируется).

    mapping (оба формата можно смешивать):
      {field: [синонимы]}         дополняет/перекрывает SYNONYMS;
      {заголовок: 'field'}        ручное назначение колонки на поле (каноническое или новое);
      {заголовок: None | ''}      исключить колонку.
    Неизвестный непустой заголовок → slugify. Повтор известного ключа → None, неизвестного → суффикс _2."""
    syn_m, explicit = split_mapping(mapping)
    lookup = {}
    for field, names in SYNONYMS.items():
        for n in [field, *names]: lookup.setdefault(header_key(n), field)
    for field, names in syn_m.items():
        for n in [field, *names]: lookup[header_key(n)] = field
    out, used = [], set()
    for h in headers:
        if h is None or not str(h).strip(): out.append(None); continue
        hk = header_key(h)
        if hk in explicit:
            k = explicit[hk]
            if k is None: out.append(None); continue
            known = True
        else:
            known = lookup.get(hk); k = known or slugify(h)
        if k in used:
            if known: out.append(None); continue
            i = 2
            while f"{k}_{i}" in used: i += 1
            k = f"{k}_{i}"
        used.add(k); out.append(k)
    return out

def column_labels(headers, keys, mapping=None, labels=None) -> dict:
    """label для person_fields: labels[key] > канонический (при ручном назначении на каноническое поле
    или для полей из ФИО) > исходный заголовок."""
    _, explicit = split_mapping(mapping)
    out = {}
    for h, k in zip(headers, keys):
        if not k or k.startswith("__") or k in SERVICE_KEYS: continue
        manual = header_key(h) in explicit
        out[k] = LABELS.get(k, " ".join(str(h).split())) if manual and k in LABELS else " ".join(str(h).split())
    if "__fio__" in keys:
        for k in ("last_name", "first_name", "middle_name"): out.setdefault(k, LABELS[k])
    for k, v in (labels or {}).items():
        if k in out: out[k] = v
    return out

def split_fio(value):
    p = str(value or "").split()
    return (p[0] if p else "", p[1] if len(p) > 1 else "", " ".join(p[2:]))
