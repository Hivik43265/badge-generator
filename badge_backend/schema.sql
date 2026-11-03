-- Единая схема Badge Generator = миграция v1 (PRAGMA user_version=1), применяется badge_backend/db.py
-- Это снимок v1, НЕ менять (иначе сломается цепочка миграций). Дальнейшие изменения — в db.MIGRATIONS:
--   v2 persons.printed_at; v3 тип line; v4 тип ellipse + person_fields.default_value TEXT NULL;
--   v5 person_fields.data_type (text|number|date|image|bool). Полей по умолчанию нет: только upsert_field.
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
