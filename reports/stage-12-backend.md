# Этап 12 — Backend

Основание: задача Архитектора (этап 12, утверждён Иваном); сигнатуры — строго по `reports/stage-12-actions.md` §3.
`ui/` и `data_tools/` не затронуты. Дублей сервисов нет: `create_person/update_person/delete_person/get_person`
переиспользованы, новые функции добавлены только там, где их не было.

## Схема: одна миграция v4 (`db._v4_ellipse_defaults`, `LATEST = 4`)
- `template_elements` пересобрана: в CHECK типов добавлен `'ellipse'`; данные и id сохраняются, индекс `idx_te_side_z` пересоздаётся.
- `person_fields.default_value TEXT NULL`.
- Идемпотентна (повторный запуск после отката user_version ничего не ломает).
- `schema.sql` оставлен снимком v1 (менять его нельзя — сломается цепочка миграций), в шапке добавлен комментарий о v2–v4.
- `testing.create_legacy_db(path, version=0..4)`.

## Рендер
- `ellipse`: эллипс, вписанный в рамку x,y,w,h; style `fill`, `stroke` (= `border_color`), `stroke_width` (= `border_width`, px или `*_mm`); `stroke` без ширины → 1 px; `radius` игнорируется; пустой style — ничего не рисуется.
- `default_value`: если значение поля у записи пустое/None, подставляется `person_fields.default_value` (field, qr, barcode). `load_elements` добавляет `default_value` в каждый элемент, поэтому подстановка работает в `render_card_db`, `render_preview`, `snapshot`, экспорте и печати. Прямой `render_card` берёт `el["default_value"]`, если ключ есть.

## API (`badge_backend.api`)
```python
query_persons(con, where: dict | None = None, printed: bool | None = None, only_marked: bool = False, order_by: str = "id") -> list[dict]
clear_printed(con, ids) -> int                         # printed_at=NULL; print_mark не трогает
delete_persons(con, ids) -> int                        # одной транзакцией
backup_db(con, dest_path) -> Path                      # sqlite backup API, временный файл + os.replace
vacuum_db(con) -> dict                                 # {"size_before": int, "size_after": int}
compact_and_backup(con, backup_dir) -> dict            # {"backup": Path, "size_before", "size_after", "integrity": "ok"}
restore_db(target_path, backup_path) -> None           # проверка integrity_check и 1 ≤ schema_version ≤ LATEST, затем migrate
upsert_field(con, name, label, sort_order=0, default_value=...) -> None   # ... — не менять default
set_field_default(con, name, default_value) -> None    # None/'' — сброс; неизвестное поле → ValueError
delete_field(con, name, *, unlink=True) -> bool        # unlink=False и поле используется → ValueError; нет поля → False
list_fields(con) -> list[dict]                         # name, label, sort_order, default_value
list_field_links(con) -> dict[str, list[dict]]         # field → [{"element_id", "id", "type", "side", "label"}]
link_field(con, element_id, field_name) -> bool        # text|field|barcode|qr; text → field (static_value=NULL, style/геометрия сохраняются); иначе ValueError; нет элемента → False
unlink_field(con, element_id, static_value=None) -> bool   # field → text; barcode/qr остаются; static_value если задан
create_element(con, "ellipse", x, y, w, h, style={"fill", "stroke", "stroke_width"})   # сигнатура прежняя
```

## Формат условий `query_persons`
```python
Where     = {"join": "and" | "or", "terms": [Condition | Where, ...]}     # вложенность = скобки
Condition = {"field": <имя из person_fields> | "id" | "print_mark" | "printed_at",
             "op": "eq" | "ne" | "contains" | "startswith" | "empty" | "not_empty",
             "value": str | None}
```
- Можно передать одиночное `Condition` вместо `Where` (считается `{"join":"and","terms":[cond]}`).
- Сравнение строковое, без учёта регистра (casefold, в т.ч. кириллица; «ё» ≠ «е»). `empty`/`not_empty` — без value, пробелы = пусто.
- `printed`: True — printed_at задан, False — нет; `only_marked` — print_mark=1; всё соединяется через AND.
- `order_by`: `id`, `printed_at`, `print_mark` или имя поля; префикс `-` — по убыванию.
- Имена полей, op, join и order_by проверяются по белым спискам, значения — только параметры `?`. Ошибка → `ValueError`.

## Решение Архитектора: link/unlink обратимы
- `link_field` принимает и `text`: элемент становится `field`, static_value очищается, style и геометрия не меняются.
- `unlink_field`: field → text (static_value — переданный или прежний), barcode/qr остаются своим типом.
- Цикл link → unlink → link (и unlink со static_value) покрыт тестами для text, barcode, qr.

## Тесты
- Новый файл `tests/test_stage12.py` — 30 тестов (циклы link/unlink для text/barcode/qr, миграция v3→v4, ellipse + golden `ellipse_mixed.png`, default_value в рендере/snapshot/QR, поля и связи, delete_persons/clear_printed, query_persons включая попытки инъекций, backup/vacuum/compact/restore).
- Обновлены проверки версии схемы (3 → 4) в старых тестах.
- Полный прогон: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -v tests data_tools/tests` — **287 passed**.
- Golden `ellipse_mixed` без текста — от шрифтов не зависит, в Windows-deselect не добавлен.
