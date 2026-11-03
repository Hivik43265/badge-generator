# Badge Generator — backend (`badge_backend/`)

Генерация пропусков CR80 (85.6×54 мм, 300 DPI = **1011×638 px**). Python 3.10+, SQLite, Pillow, openpyxl, PyQt6 (только печать).
UI здесь нет: Frontend вызывает `badge_backend.api`.

```
pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen python -m pytest -v      # tests/ + data_tools/tests
python tests/make_golden.py                         # перегенерировать эталоны (осознанно)
```

## Структура
| файл | назначение |
|---|---|
| `schema.sql` | **единственная** схема (= миграция v1) |
| `db.py` | `connect()`, `migrate()` через `PRAGMA user_version` |
| `photo_config.py` | парсер/сериализатор `x;y;scale;crop_x;crop_y;angle` |
| `render/` | `render_card()` на Pillow, шрифты с кириллицей (DejaVu → Liberation → Noto → любой TTF → встроенный) |
| `services/headers.py` | единый маппинг заголовков Excel/CSV (синонимы, ФИО, транслит) |
| `services/importer.py` | импорт .xlsx/.csv + вызов `data_tools.validate_import.validate_records` |
| `services/exporter.py` | PNG 300 DPI, PDF CR80 (Pillow), `set_print_mark`, `mark_printed` |
| `services/print_service.py` | печать на `QPrinter` (QPainter, страница 85.6×54 мм, поля 0) |
| `api.py` | фасад для Frontend |
| `demo.py` | демо-шаблон; пример: `examples/demo.png` |

## Модель данных
- Координаты элементов — **целые px холста 1011×638**, (0,0) — левый верхний угол.
- Данные записи — только `persons.fields_json`. `person_fields` хранит метаданные колонок (ключ, label = исходный заголовок, порядок). `template_backgrounds` хранит фон стороны (`color`, `image_path` растягивается cover).
- `photo_path` — относительный путь (база `base_dir` при рендере/экспорте/печати).

## photo_config
`x;y;scale;crop_x;crop_y;angle`, default `0;0;1.0;0;0;0`.
x, y — int px, сдвиг центра фото от центра рамки. scale — float>0, зум относительно cover-fit.
crop_x, crop_y — int px исходника, левый верхний угол обрезки. angle — градусы **по часовой**.
Порядок: crop → cover × scale → поворот → центр в центр рамки + (x,y) → обрезка рамкой.
Невалидная строка → default + `logging.warning` + `RuntimeWarning` (без исключения).

## style_json
`font_family` (`DejaVu Sans`…), `font_path`, `font_size` (pt; px = pt·300/72), `color`, `bold`,
`align` left|center|right, `valign` top|middle|bottom, `wrap` (true), `line_spacing`, `padding` (px),
`fill`, `border_color`, `border_width` (px) или `border_width_mm`, `radius` (px) или `radius_mm`, `fit` (image: contain|cover).
Текст переносится по словам и ужимается, пока не влезет в рамку (минимум 6 px).

## Типы элементов
`text` (static_value), `field` (fields_json[field_name]), `photo` (photo_path + photo_config; без фото или с битым фото рисуется плейсхолдер «нет фото»),
`image` (static_value — путь), `rect`, `barcode`, `qr`, `line`. style: `min_size` (pt, по умолчанию 8) — нижний предел автоуменьшения.

Шаблон нового проекта **пуст** (0 элементов, seed-макетов в коде нет). Демо-макет для тестов — `tests/fixtures/demo_layout.json`
(`demo.build_demo(con)` / `demo.apply_layout(con, dict|path)`). Фон — только через `template_backgrounds` (`set_background`).

- **rect (рамка)**: `{stroke, stroke_width, fill, radius}` (старые `border_color`/`border_width` — синонимы; `stroke` без `stroke_width` → 1 px; `radius` через rounded_rectangle).
- **barcode**: значение из `field_name` (поле записи; если пусто — `static_value`) или `static_value`.
  style `{format (синоним symbology): "code128"|"ean13" (code128), show_text: bool (true), quiet_zone: модулей (10), color, background ("#FFFFFF"|null), font_size (pt, 8)}`.
  Целое число px на модуль = `w // (модулей + 2·quiet_zone)`, по центру рамки; подпись под полосами, если влезает (<60% h).
  EAN-13: 12 цифр (контрольная досчитывается) или 13 с верной контрольной. Невалидно/пусто/не влезает → пустая рамка (фон) + RuntimeWarning.
- **qr**: значение как у barcode. style `{error_correction: "L"|"M"|"Q"|"H" ("M"), border: модулей (4), color, background}`.
  Квадрат в `min(w,h)`, целое число px на модуль, по центру. Пусто/не влезает → пустая рамка + RuntimeWarning.
- **line**: отрезок (x,y)→(x+w,y+h); w,h могут быть 0 или <0, но не оба 0 (CHECK). style `{stroke ("#000"), stroke_width (px, 1)}`.

Экспорт/печать: `ExportResult`, `PdfResult`, `PrintResult` имеют `.empty_template: bool` и `.warnings: list[str]`
(«шаблон пуст…» или «сторона 'back' шаблона пуста»), плюс `warnings.warn(RuntimeWarning)` и log.warning; исключения нет.

Зависимости: `python-barcode`, `qrcode[pil]`; для тестов-декодеров — `requirements-dev.txt` (zxing-cpp, тесты skipif без него).

## База данных по умолчанию
`badge_backend.db.DEFAULT_DB_PATH = "project.db"`: имя файла БД проекта. Относительный путь считается от каталога проекта (по умолчанию от cwd). `db.default_db_path(project_dir=None)` возвращает `<project_dir|cwd>/project.db`. `connect()` без аргумента по-прежнему открывает `:memory:`. Относительные `photo_path` разрешаются от `base_dir`; Frontend передаёт каталог БД.

## Схема v2: printed_at и отметки печати
- Миграции: `user_version` 1 = `schema.sql`, 2 = `ALTER TABLE persons ADD COLUMN printed_at TEXT NULL` (шаг `_v2_printed_at` в `db.py`, идемпотентный; старые БД доводятся автоматически при `connect`).
- 3 = `_v3_line`: пересборка `template_elements` (тип `line` в CHECK; для line w/h — вектор), одна транзакция, id/данные/индекс `idx_te_side_z` сохраняются, идемпотентно. `get_schema_version(con)` → 3. `testing.create_legacy_db(path, version=1|2|3)`.
- `printed_at`: `NULL` (не печаталось) или ISO 8601, локальное время со смещением, точность до секунд: `"2026-11-03T16:40:12+03:00"` (`datetime.now().astimezone().isoformat(timespec="seconds")`, `db.now_iso()`). Возвращается в `api.get_person` и `api.list_persons` как строка или `None`.
- `print_mark` = «к печати». `set_print_mark(con, ids, value: bool) -> int` ставит или снимает отметку, `printed_at` не трогает.
- `mark_printed(con, ids) -> int` = «напечатано»: одной транзакцией `print_mark=0` и `printed_at=now`; при ошибке всё откатывается. Параметра `value` больше нет: `mark_printed(con, ids, False)` даёт `TypeError`, вместо этого вызывайте `set_print_mark(con, ids, False)`.

## Формат person (render_card / render_preview)
Принимается `dict` или `sqlite3.Row`:
- `fields_json`: строка JSON **или** dict; `photo_path` (относительный/абсолютный/None); `photo_config` (строка/None → default);
- краткая форма: `{"fields": {...}, "photo_path": ..., "photo_config": ...}`. Если заданы оба, приоритет у `fields_json`;
- `None` даёт пустой шаблон; для `render_card_db`/`render_preview` также принимается `id` (int).

## Импорт: mapping, labels, фото, прогресс
- `mapping` (форматы можно смешивать): `{field: [синонимы]}` (старый формат), `{"Заголовок": "field"}` (ручное назначение), `{"Заголовок": None | ""}` (исключить колонку).
- label в `person_fields`: при ручном назначении на каноническое поле берётся канонический label («Фамилия», «Отдел»…), для нового поля — исходный заголовок. `labels={key: label}` задаёт label явно и перезаписывает существующий.
- `require_photo=False` (по умолчанию): записи без фото импортируются (`photo_path=NULL`, photo_config по умолчанию), `PHOTO_MISSING` попадает в `report.warnings`, рендер рисует плейсхолдер. `require_photo=True` включает строгий режим: такая строка пропускается с ошибкой `PHOTO_MISSING`.
- `progress=callable(done, total)`: если вернул `False`, импорт отменяется, транзакция откатывается, `report.cancelled=True`.

## Экспорт и печать: фото, прогресс, фоновые потоки
- Предпроверка для UI: `missing_photos(con, ids=None, base_dir=None) -> [id]` (нет `photo_path`, нет файла, пустой или битый файл; `ids=None` → print_mark=1).
- `export_png`, `export_pdf`, `print_cards` (и `*_from_snapshot`, `print_snapshot`) принимают `allow_missing_photo=False`. Если параметр False и есть такие записи, **до** записи файлов и до печати выбрасывается `MissingPhotosError` (`.ids`). При True результат содержит `.missing_photo_ids`.
- Типы результатов обратно совместимы: `ExportResult` — это `list[Path]`, `PdfResult` — это `Path`, `PrintResult` — это `int`. Дополнительные поля: `.missing_photo_ids` и `.cancelled`.
- `progress=callable(done, total)` считает по страницам (запись×сторона). `False` означает отмену: PNG оставляет уже сохранённые файлы, PDF не создаётся (возвращается `None`), печать вызывает `printer.abort()`.
- Фоновая работа: `snap = snapshot(con, ids=None, sides)` собирается в GUI-потоке. Затем в рабочем потоке без соединения вызываются `export_png_from_snapshot(snap, out_dir, base_dir)`, `export_pdf_from_snapshot(snap, out_path, base_dir)` и `print_snapshot(snap, printer, base_dir)`. Так работает и `:memory:`.

## Текст в рамке
Текст всегда помещается в рамку `w×h` по реальному bbox глифов (асцендеры, десцендеры, межстрочный интервал). Порядок: 1) перенос по пробелам, затем длинных слов по дефису, тире или `/` (знак остаётся в конце строки); 2) уменьшение шрифта до `style.min_size` (pt, по умолчанию 8); 3) только при min_size слово шире рамки режется по символам; 4) строки, не помещающиеся по высоте, отбрасываются целиком, последняя видимая строка заканчивается «…». В случаях 3 и 4 выдаётся `RuntimeWarning`.

## API (`from badge_backend import api`)

**badge_backend.db**
- `default_db_path(project_dir=None) -> pathlib._local.Path`
- `migrate(con) -> int`
- `connect(path=:memory:) -> sqlite3.Connection`

**badge_backend.photo_config**
- `PhotoConfig(x:int, y:int, scale:float, crop_x:int, crop_y:int, angle:float)`; `.parse(s)`, `.dump()`
- `normalize(s) -> str`

**badge_backend.render**
- `transform_photo(src: Image.Image, w: int, h: int, cfg: PhotoConfig | str | None) -> Image.Image`
- `render_card(person, elements, side: str = front, background=None, base_dir=None) -> Image.Image`
- `load_elements(con, side=None)`
- `load_background(con, side)`
- `render_card_db(con, person, side=front, base_dir=None) -> Image.Image`
- `render_preview(con, person, side=front, scale: float = 0.5, base_dir=None) -> Image.Image`

**badge_backend.services.headers**
- `header_key(s) -> str`
- `slugify(s) -> str`
- `split_mapping(mapping)`
- `map_headers(headers, mapping: dict | None = None) -> list`
- `column_labels(headers, keys, mapping=None, labels=None) -> dict`
- `split_fio(value)`

**badge_backend.services.importer**
- `ImportReport(added: int = 0, skipped: int = 0, errors: list = <factory>, ids: list = <factory>, validator: str = , warnings: list = <factory>, cancelled: bool = False) -> None`
- `read_table(path) -> tuple[list, list]`
- `parse_file(path, mapping=None, labels=None)`
- `import_file(con, path, mapping=None, photo_dir=None, validate=True, *, labels=None, require_photo=False, progress=None) -> ImportReport`

**badge_backend.services.exporter**
- `MissingPhotosError` — Среди записей есть без фото или с недоступным файлом; .ids — их id. Выбрасывается ДО экспорта/печати.
- `ExportResult` — list[Path] (как раньше) + .missing_photo_ids + .cancelled.
- `PdfResult` — Path к PDF (как раньше) + .missing_photo_ids.
- `missing_photos_in_snapshot(snap, base_dir=None) -> list[int]`
- `missing_photos(con, ids=None, base_dir=None) -> list[int]`
- `check_photos(snap, base_dir, allow_missing_photo)`
- `snapshot(con, ids=None, sides=(front, back)) -> list[dict]`
- `render_job(job, base_dir=None)`
- `export_png_from_snapshot(snap, out_dir=., base_dir=None, progress=None, allow_missing_photo=False) -> ExportResult`
- `export_pdf_from_snapshot(snap, out_path=cards.pdf, base_dir=None, progress=None, allow_missing_photo=False) -> PdfResult | None`
- `export_png(con, ids=None, out_dir=., sides=(front, back), base_dir=None, progress=None, allow_missing_photo=False) -> ExportResult`
- `export_pdf(con, ids=None, out_path=cards.pdf, sides=(front, back), base_dir=None, progress=None, allow_missing_photo=False)`
- `set_print_mark(con, ids, value: bool = True) -> int`
- `mark_printed(con, ids) -> int`

**badge_backend.services.print_service**
- `setup_printer(printer) -> None`
- `marked_ids(con, ids=None) -> list[int]`
- `PrintResult` — int (число напечатанных страниц, как раньше) + .missing_photo_ids + .cancelled.
- `print_snapshot(snap, printer, base_dir=None, progress=None, allow_missing_photo=False) -> PrintResult`
- `print_cards(con, printer, sides=(front, back), base_dir=None, ids=None, progress=None, allow_missing_photo=False) -> PrintResult`

**badge_backend.api**
- `list_persons(con, only_marked: bool = False) -> list[dict]`
- `get_person(con, person_id: int) -> dict | None`
- `create_person(con, fields: dict, photo_path: str | None = None, photo_config: str | None = None, print_mark: int = 0) -> int`
- `update_person(con, person_id: int, fields: dict | None = None, photo_path=Ellipsis, print_mark=None, merge: bool = True) -> bool`
- `delete_person(con, person_id: int) -> bool`
- `update_photo_config(con, person_id: int, config: str | PhotoConfig) -> str`
- `list_fields(con) -> list[dict]`
- `upsert_field(con, name: str, label: str, sort_order: int = 0) -> None`
- `list_elements(con, side: str | None = None) -> list[dict]`
- `create_element(con, type: str, x: int, y: int, w: int, h: int, side: str = front, z_order: int = 0, field_name: str | None = None, static_value: str | None = None, style: dict | None = None) -> int`
- `update_element(con, element_id: int, **changes) -> bool`
- `delete_element(con, element_id: int) -> bool`
- `set_background(con, side: str, color: str = #FFFFFF, image_path: str | None = None) -> None`
- `get_background(con, side: str) -> dict | None`

### Пример
```python
from badge_backend import api, db
con = api.connect(db.default_db_path(project_dir))
rep = api.import_file(con, "people.xlsx", photo_dir="photos")    # added/skipped/errors/warnings
api.set_print_mark(con, rep.ids, True)                         # «к печати»
img = api.render_card_db(con, rep.ids[0], "front", base_dir="photos")
miss = api.missing_photos(con, base_dir="photos")                 # предупредить пользователя
snap = api.snapshot(con, None, ("front", "back"))                 # GUI-поток
api.export_pdf_from_snapshot(snap, "out/cards.pdf", "photos", progress=cb, allow_missing_photo=bool(miss))  # worker
# печать: QPrintDialog(printer).exec() → api.print_cards(con, printer, base_dir="photos", allow_missing_photo=...)
```

## Сборка Windows .exe (этап 11)

- `pyinstaller --noconfirm --clean packaging/badge_generator.spec` → `dist/BadgeGenerator.exe` (onefile, windowed, иконка `packaging/icon.ico`) и `dist/BadgeSmoke.exe` (консольный смоук backend: migrate → рендер → PNG/PDF, код 0 = OK).
- В собранном exe БД по умолчанию: `%APPDATA%\BadgeGenerator\project.db` (не внутри `_MEIPASS`); `schema.sql` вшит в exe.
- CI: `.github/workflows/build-windows.yml` — push тега `v*` или вручную (Actions → build-windows → Run workflow); артефакт `BadgeGenerator`.
