# Этап 13 — Backend: импорт/экспорт .xlsx/.xls/.csv/.db

`ui/` и `data_tools/` не затронуты. Зависимости: `xlrd>=2.0` (чтение .xls), `xlwt>=1.3` (запись .xls) добавлены
в `requirements.txt`; CI ставит их через `pip install -r requirements.txt` (workflow не менялся).

## Без дублей
- Сопоставление заголовков уже было централизовано в `services/headers.py` (`map_headers`); `auto_match` — тонкая обёртка над ним.
- `importer.py` переиспользован: `parse_file` разделён на `read_table` + новый `parse_rows`, ядро `import_file` вынесено в
  `import_records` (валидация, person_fields, вставка одной транзакцией, прогресс/отмена). `import_file` и `import_rows`
  используют одно ядро. `read_table`/`import_file` теперь понимают и `.xls`.
- Экспорта таблиц раньше не было (только PNG/PDF) — новый модуль `services/table_export.py`.

## API (`badge_backend.api`)
```python
open_source(path) -> list[Sheet]
read_rows(sheet: Sheet, header: bool = True, limit: int | None = None) -> tuple[list[str], list[list[str]]]
auto_match(columns, mapping: dict | None = None) -> list            # str | None для каждой колонки
import_rows(con, sheet: Sheet, mapping: dict | None = None, *, header: bool = True, photo_dir=None,
            validate: bool = True, labels: dict | None = None, require_photo: bool = False,
            progress=None, cancel=None, extract_images: bool = True) -> ImportReport
save_mapping(path, mapping: dict, *, columns=None) -> Path
load_mapping(path) -> dict
export_persons(con, path, format: str | None = None, ids=None, *, photo_dir=None,
               csv_encoding: str = "utf-8-sig") -> dict
XLS_MAX_ROWS = 65535

class Sheet:   # dataclass
    path: Path; name: str; kind: str        # 'xlsx' | 'xls' | 'csv' | 'project' | 'sqlite'
    index: int; work_path: Path | None; schema_version: int | None; meta: dict
    def close(self) -> None                 # удалить временную копию 'project'
    def as_dict(self) -> dict
```

### Поведение
- **open_source**: xlsx/xlsm и xls — все листы; csv/txt — один лист (имя = имя файла); `.db/.sqlite/.sqlite3`:
  - проектная БД (есть `persons` и `person_fields`) любой user_version → один лист `persons`, kind `project`:
    исходник открывается `mode=ro`, копируется backup API во временный файл, копия мигрируется до LATEST;
    `schema_version` — версия исходника. Исходный файл не меняется (проверено хешем и mtime).
    Временную копию удаляет `Sheet.close()`.
  - произвольная SQLite → по листу на таблицу/представление, kind `sqlite`, чтение только через URI `mode=ro`.
  - другое расширение / не SQLite → `ValueError`; нет файла → `FileNotFoundError`.
- **read_rows**: значения — строки, как при импорте (strip, `123.0`→`123`, даты ISO). `header=False` → колонки
  «Колонка 1..N», все строки — данные. Пустые строки в начале листа пропускаются. Для `project`/`sqlite` заголовки из схемы.
- **import_rows**: `mapping` — формат `headers.map_headers` (`{заголовок: 'field' | None}`, `{field: [синонимы]}`).
  `progress(done, total)` вернул False, или `cancel()` → True / `cancel.is_set()` (threading.Event) → откат всей транзакции,
  `report.cancelled=True`, `added=0`. Для `project` переносятся поля, photo_path/photo_config, print_mark/printed_at,
  label и default_value полей (только если у текущего проекта их нет).
- **CSV**: чтение utf-8-sig → cp1251 (+ автоопределение разделителя), как раньше; запись `;`, `utf-8-sig` (по умолчанию) или `cp1251`.
- **export_persons**: `ids=None` — все записи (не только помеченные); иначе в заданном порядке. Заголовки —
  label полей + «Фото», «Настройки фото» (распознаются синонимами при обратном импорте).
  `.xls`: > 65535 строк данных → `ValueError` до создания файла. `.db`: новая проектная БД (LATEST) с выбранными
  записями, полями, элементами шаблона и фонами; фото и картинки шаблона копируются в `<имя>_photos/`, в БД — имена
  файлов; отсутствующие файлы → `warnings`; существующий путь → `FileExistsError`.
  Результат: `{"path", "format", "rows", "warnings"}` (+ для db: `"photo_dir", "files_copied"`).
- **mapping JSON**: `{"format": "badge-generator/mapping", "version": 1, "mapping": {...}, "columns": [...]}`, UTF-8; чужой/битый файл → `ValueError`.

## Фото
- Колонка с путём («Фото», «Путь к фото», photo_path …) используется как есть (относительно `photo_dir`).
- **Встроенные картинки xlsx — реализовано**: `ws._images` (openpyxl), по якорю `anchor._from` (OneCell/TwoCell)
  картинка сохраняется в `photo_dir` как `<файл>_<лист>_r<строка>_c<колонка>.<ext>` и становится photo_path строки якоря,
  если у строки нет пути в колонке. Ограничения: `AbsoluteAnchor` (не привязан к ячейке) пропускается; на строку берётся
  первая картинка; `ws._images` — внутренний атрибут openpyxl (проверено на 3.1.5); без `photo_dir` картинки не
  извлекаются (RuntimeWarning). Встроенные картинки .xls не поддерживаются (xlrd их не читает).

## Решения Архитектора (этап 13)
1. `export_persons` принимает `con` первым аргументом, доп. параметры `photo_dir`, `csv_encoding`; возвращает dict.
2. `ids=None` в `export_persons` — **все записи** (по id), а не только помеченные (в отличие от `snapshot`, где None = print_mark=1).
3. `.xls` > 65535 строк данных → `ValueError` на русском с советом: «Слишком много записей для формата .xls: выбрано N,
   максимум 65535. Выберите формат .xlsx (Excel 2007+) — в нём ограничения нет.» Файл не создаётся.
4. Round-trip ключей: заголовки экспорта — label полей. Стандартные поля (Фамилия, Имя, Должность…) при обратном импорте
   получают те же ключи (синонимы headers.py); пользовательское поле в новой БД получает ключ из label (slugify), исходный
   ключ не сохраняется. Ключи полностью сохраняются только в формате `.db`.
5. Фото: при `require_photo=False` строка, у которой файл фото не найден (`PHOTO_NOT_FOUND` валидатора), **импортируется**
   с предупреждением `PHOTO_MISSING` (details: «файл фото не найден: … (PHOTO_NOT_FOUND)»), photo_path сохраняется как указан.
   Обрабатывается в backend (`importer.import_records`), `data_tools/` не менялся. Повреждённый/пустой файл
   (`PHOTO_BROKEN`/`PHOTO_EMPTY`) — по-прежнему ошибка. При `require_photo=True` такие строки пропускаются.
   Касается и `import_file`, и `import_rows`.

## Замечания
- Валидатор `data_tools.validate_import` (как и раньше) нормализует пробелы/переносы в текстовых полях — это поведение существующего импорта, не менялось (решение Архитектора: допустимо); `validate=False` отключает.

## Тесты
- `tests/test_stage13.py` — 25 тестов: round-trip экспорт→импорт для xlsx/xls/csv/db с кириллицей, лимит .xls,
  прогресс, отмена (callable / Event / progress→False), save/load mapping, импорт проектных БД v1–v4 (исходник не меняется),
  произвольная SQLite read-only, колонка фото, встроенные картинки xlsx, cp1251, листы/limit/header=False.
- `tests/test_stage13.py` +2 (ненайденное фото → импорт + PHOTO_MISSING; require_photo=True → пропуск), русский текст ошибки .xls;
  `tests/test_d19_keys.py` — 3 регрессионных теста D19.
- Полный прогон `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -v tests data_tools/tests` — **317 passed**.

## D19 (пустые превью/значения после добавления записи)
Backend проверен: `create_person`/`update_person` сохраняют ключи как есть, `list_fields` отдаёт `name`, рендер ищет
`field_name` точным совпадением (без label/регистра) — для стандартных и пользовательских полей работает
(тесты `test_d19_keys.py`). Причина — в UI (до коммита Frontend D19): форма записи при пустом `person_fields` подставляла
стандартные ключи (`last_name`, `first_name`… из LABELS), а поля шаблона с другими `field_name` (напр. `familiya`)
в форме не показывались; таблица/очередь брали захардкоженные ключи ФИО/position. Значения писались под ключи,
которых нет в шаблоне → пустое превью. Исправлено Frontend (record_form/records_table/main_view: набор полей только из
`list_fields()` + поля шаблона без person_fields регистрируются `upsert_field`). Изменений backend не требуется.
