# Этап 1 — Backend: схема БД и photo_config

Корень: `/workspace/badge_generator`, пакет `badge_backend/`: `schema.sql` (единственная схема), `db.py`, `photo_config.py`, `render/`, `services/`.

## Миграции
`badge_backend/db.py`: `MIGRATIONS = [schema.sql]`, версия = `PRAGMA user_version`. `connect(path)` открывает БД, включает `foreign_keys` и применяет недостающие миграции в транзакции (идемпотентно). Текущая версия: 1. Будущие версии добавляются как ALTER-скрипты в `MIGRATIONS`. Дубль `db/` удалён.

## Полный DDL (`badge_backend/schema.sql`, миграция v1)
```sql
-- Единая схема Badge Generator = миграция v1 (PRAGMA user_version=1), применяется badge_backend/db.py
CREATE TABLE person_fields (
    name TEXT PRIMARY KEY, label TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE persons (
    id           INTEGER PRIMARY KEY,
    fields_json  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(fields_json)),
    photo_path   TEXT,               -- относительный путь (к photo_dir проекта)
    photo_config TEXT NOT NULL DEFAULT '0;0;1.0;0;0;0',
    print_mark   INTEGER NOT NULL DEFAULT 0 CHECK (print_mark IN (0,1)),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_persons_print_mark ON persons(print_mark);
CREATE TABLE template_elements (
    id           INTEGER PRIMARY KEY,
    type         TEXT NOT NULL CHECK (type IN ('text','field','photo','image','rect','qr','barcode')),
    x INTEGER NOT NULL, y INTEGER NOT NULL,
    w INTEGER NOT NULL CHECK (w > 0), h INTEGER NOT NULL CHECK (h > 0),   -- px холста 1011x638
    field_name   TEXT,
    static_value TEXT,
    style_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(style_json)),
    side         TEXT NOT NULL DEFAULT 'front' CHECK (side IN ('front','back')),
    z_order      INTEGER NOT NULL DEFAULT 0,
    CHECK (type <> 'field' OR field_name IS NOT NULL));
CREATE INDEX idx_te_side_z ON template_elements(side, z_order);
CREATE TABLE template_backgrounds (
    side TEXT PRIMARY KEY CHECK (side IN ('front','back')),
    image_path TEXT, color TEXT NOT NULL DEFAULT '#FFFFFF');
CREATE TRIGGER persons_touch AFTER UPDATE ON persons
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN UPDATE persons SET updated_at = datetime('now') WHERE id = NEW.id; END;
```

## Зачем person_fields и template_backgrounds
- **person_fields**: только метаданные колонок (ключ, исходный заголовок как label, порядок). Нужна Frontend для заголовков таблицы и выбора `field_name` в редакторе шаблона. **Данные записей хранятся только в `persons.fields_json`.**
- **template_backgrounds**: фон каждой стороны (`front`/`back`): `color` и/или `image_path` (картинка растягивается cover поверх цвета).

## Спецификация photo_config
Строка `x;y;scale;crop_x;crop_y;angle`, default `0;0;1.0;0;0;0`.
| поле | тип | смысл |
|---|---|---|
| x, y | int, px холста | сдвиг фото относительно центра рамки photo-элемента (+x вправо, +y вниз) |
| scale | float > 0 (всегда с точкой при записи) | зум относительно cover-fit: 1.0 = обрезанное фото ровно закрывает рамку |
| crop_x, crop_y | int ≥ 0, px исходника | левый верхний угол обрезки; используется область `[crop_x..W) × [crop_y..H)` |
| angle | float, градусы **по часовой** | поворот вокруг центра фото |

Порядок применения: crop → cover-fit в рамку × scale → поворот по часовой → центр фото в центр рамки + (x, y) → обрезка рамкой.
Чтение принимает запятую как десятичный разделитель. Невалидная строка (не 6 значений, нечисловые, дробные x/y/crop, scale ≤ 0, отрицательный crop, NaN/inf) даёт **default + `logging.warning` + `RuntimeWarning`**, исключения нет. Пустая строка или None даёт default без предупреждения. API: `PhotoConfig.parse(s)`, `PhotoConfig.dump()`, `normalize(s)`, `DEFAULT`.

## pytest -v (tests/test_schema.py — приёмка этапа 1)
```
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- /workspace/badge_generator/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /workspace/badge_generator
configfile: pytest.ini
collecting ... collected 29 items

tests/test_schema.py::test_card_px PASSED                                [  3%]
tests/test_schema.py::test_migration_from_scratch PASSED                 [  6%]
tests/test_schema.py::test_defaults PASSED                               [ 10%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('field',0,0,1,1)] PASSED [ 13%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,side) VALUES ('text',0,0,1,1,'top')] PASSED [ 17%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('circle',0,0,1,1)] PASSED [ 20%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('rect',0,0,0,1)] PASSED [ 24%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,style_json) VALUES ('rect',0,0,1,1,'{bad')] PASSED [ 27%]
tests/test_schema.py::test_checks[INSERT INTO persons(print_mark) VALUES (2)] PASSED [ 31%]
tests/test_schema.py::test_checks[INSERT INTO persons(fields_json) VALUES ('not json')] PASSED [ 34%]
tests/test_schema.py::test_types_ok[qr] PASSED                           [ 37%]
tests/test_schema.py::test_types_ok[barcode] PASSED                      [ 41%]
tests/test_schema.py::test_types_ok[photo] PASSED                        [ 44%]
tests/test_schema.py::test_types_ok[image] PASSED                        [ 48%]
tests/test_schema.py::test_types_ok[text] PASSED                         [ 51%]
tests/test_schema.py::test_types_ok[rect] PASSED                         [ 55%]
tests/test_schema.py::test_roundtrip[0;0;1.0;0;0;0-exp0] PASSED          [ 58%]
tests/test_schema.py::test_roundtrip[10;-5;1.25;120;40;15.5-exp1] PASSED [ 62%]
tests/test_schema.py::test_roundtrip[3;4;2,5;0;0;-90-exp2] PASSED        [ 65%]
tests/test_schema.py::test_bad_gives_default_and_warning[1;2;3] PASSED   [ 68%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;0;0;0;0] PASSED [ 72%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;-1;0;0;0] PASSED [ 75%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0.5;0;0] PASSED [ 79%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0;1.5;0] PASSED [ 82%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;-3;0;0] PASSED [ 86%]
tests/test_schema.py::test_bad_gives_default_and_warning[a;0;1;0;0;0] PASSED [ 89%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;nan;0;0;0] PASSED [ 93%]
tests/test_schema.py::test_bad_gives_default_and_warning[1.5;0;1;0;0;0] PASSED [ 96%]
tests/test_schema.py::test_empty_is_default_silently PASSED              [100%]

============================== 29 passed in 0.04s ==============================
```
