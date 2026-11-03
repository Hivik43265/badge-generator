# Этап 8 — QA: регресс после API v2 (set_print_mark / mark_printed / printed_at, D2, D3, D5)

**Проверял:** BG-Контролёр (в роли QA), 03.11.2026, 16:43 (MSK). Продуктовый код и `.venv` не менялись.
**Скрипт:** `reports/qa/e2e_check.py` обновлён под API v2. Версия этапа 7 сохранена в `/tmp/e2e_check_stage7.py`.
**Выводы:** `e2e_output_stage8.txt`, `e2e_results_stage8.json`, `pytest_output_stage8.txt`, `ui_smoke_stage8.txt`, пример `card_hyphen_ellipsis.png`.

## Итог
- **e2e: 30 PASS / 1 FAIL** (31 проверка).
- **pytest** (tests + data_tools/tests): **205 passed**, 0 failed.
- **ui/smoke_test.py:** ALL OK, код возврата 0.

## Изменения в скрипте
- Строки 130 и 152: `mark_printed(..., True/False)` заменён на `set_print_mark(con, ids, value)`.
- Строка 155: проверка флага «к печати» переведена на `set_print_mark`.
- Добавлены проверки: `mark_printed` ставит print_mark=0 и printed_at в ISO 8601; `set_print_mark` не трогает printed_at; миграция v1→v2; перенос по дефису; отбрасывание неполных строк и «…».
- Допуск печати ±0.15 мм указан в названии проверки.

## Результаты
| # | Критерий | Результат | Доказательство |
|---|---|---|---|
| 1 | photo_config default/формат/невалидное→default+warning | PASS | default=0;0;1.0;0;0;0; '1;2;1,5;0.5;0;0'→0;0;1.0;0;0;0 warn=1; 'abc'→0;0;1.0;0;0;0 warn=1; valid→5;-3;1.25;10;20;15.5 |
| 2 | Схема persons | PASS | cols=['id', 'fields_json', 'photo_path', 'photo_config', 'print_mark', 'created_at', 'updated_at', 'printed_at']; photo_config DEFAULT=["'0;0;1.0;0;0;0'"] |
| 3 | create_person с невалидным photo_config | PASS | saved=0;0;1.0;0;0;0 warn=1 |
| 4 | Импорт 600 строк csv UTF-8±BOM/cp1251 (; ,) + xlsx без потерь | PASS | imp_utf-8-sig_sc.csv:600 added/0 skip/600 rows/0 mismatch/data_tools.validate_import.validate_records; imp_utf-8-sig_cm.csv:600 added/0 skip/600 rows/0 mismatch/data_tools.validate_import.validate_records; imp_utf-8_sc.csv:600 added/0 skip/600 rows/0 mismatch/ |
| 5 | Импорт large (1000 строк) | PASS | added=1000 skipped=0 errors=[] |
| 6 | Транзакция: сбой на 300-й → откат | PASS | exc=RuntimeError('fail@300'); persons=0 |
| 7 | Отмена импорта → откат | PASS | cancelled=True |
| 8 | Набор clean | PASS | rows=5 added=5 skipped=0 errors=[] warnings=[] |
| 9 | Набор duplicates | PASS | rows=4 added=2 skipped=2 errors=['DUPLICATE'] warnings=[] |
| 10 | Набор missing_fields | PASS | rows=5 added=1 skipped=4 errors=['EMAIL_INVALID', 'PHONE_INVALID', 'PHOTO_CONFIG_INVALID', 'REQUIRED_MISSING'] warnings=[] |
| 11 | Набор zero_byte_and_broken | PASS | rows=4 added=1 skipped=3 errors=['PHOTO_BROKEN', 'PHOTO_EMPTY', 'PHOTO_NOT_FOUND'] warnings=[] |
| 12 | Набор messy_headers (xlsx, маппинг Backend) | PASS | added=2 skipped=0 keys=['department', 'email', 'first_name', 'last_name', 'lishnyaya_kolonka', 'middle_name', 'phone', 'position'] |
| 13 | Импорт без data_tools | PASS | stdout='builtin-fallback 600 False' rc=0 data_tools.validate_import недоступен (No module named 'data_tools') — встроенная проверка (fallback) |
| 14 | Холст 1011×638 RGB | PASS | size=(1011, 638) mode=RGB |
| 15 | qr/barcode пропускаются с warning | PASS | warnings=["элемент 13: тип 'qr' не поддерживается в v1, пропущен"] |
| 16 | barcode (back) пропускается с warning | PASS | ["элемент 14: тип 'barcode' не поддерживается в v1, пропущен"] |
| 17 | Запись без фото не роняет рендер | PASS | плейсхолдер, без исключения; reports/qa/card_no_photo.png |
| 18 | Текст не выходит за рамку элемента (+warning при обрезке) | PASS | пикселей вне рамок=0; warnings=2 |
| 19 | Демо-макет: контентные элементы не пересекаются | PASS | пересечения=[] |
| 20 | Экспорт PNG 1011×638 @300 DPI (ids=None → print_mark=1) | PASS | 8 файлов (4 записи×2 стороны); {((1011, 638), (300, 300))}; без allow_missing_photo: MissingPhotosError ids=[6] |
| 21 | Экспорт PDF страницы 85.6×54 мм | PASS | pages=8; sizes pts={'242.64 x 153.12'} → мм={(85.6, 54.02)} (допуск ±0.1 мм; 638 px/300 DPI = 54.02 мм) |
| 22 | Печать QPrinter→PDF: только print_mark=1, страница CR80 ±0.15 мм | PASS | print_cards=8, pdf pages=8, size={'243 x 153'}→{(85.725, 53.975)} мм (помечено 4 из 7); reports/qa/print_output.pdf |
| 23 | set_print_mark / ничего не помечено → 0 страниц | PASS | print пусто=0; set_print_mark→2; marked=[1, 2] |
| 24 | mark_printed: print_mark=0 и printed_at в ISO 8601 (со смещением) | PASS | mark_printed→2; [(1, 0, '2026-11-03T16:43:52+03:00'), (2, 0, '2026-11-03T16:43:52+03:00')]; непечатанная id=3 printed_at=None |
| 25 | set_print_mark не трогает printed_at | PASS | print_mark=1 printed_at=2026-11-03T16:43:52+03:00 |
| 26 | Миграция user_version 1→2 без потери данных (идемпотентна) | PASS | user_version 1→2, повторно 2; persons до==после: True (2 строк); template_elements сохранены: True; printed_at=[None, None] |
| 27 | Перенос длинной двойной фамилии по дефису | PASS | рамка 600×300, 22pt (min 8pt): кегль 44px, строки=['Константинопольский-', 'Водопьянов-', 'Длиннофамильный']; notes=[] |
| 28 | Частично видимые строки не рисуются, последняя видимая строка заканчивается на «…» | PASS | строк видно=3, последняя='длинная должность Очень…', высота bbox=117.0≤125; ink-строки пикселей 7..113; warning=["элемент 9: текст 'Очень длинная должность Оче� |
| 29 | Один render_card | PASS | badge_backend/render/__init__.py:238:def render_card(person, elements, side: str = "front", background=None, base_dir=None) -> Image.Image: |
| 30 | Нет SQL в ui/ | FAIL | ui/backend_api.py:54:        return self.con.execute("PRAGMA user_version").fetchone()[0] |
| 31 | Нет маппинга заголовков/чтения Excel в data_tools | PASS | grep пусто |
| — | Полный pytest | PASS | 205 passed за 5.42 с |
| — | ui/smoke_test.py | PASS | ALL OK, в т.ч. «открытие v1-БД → миграция до v2» и «AST: нет вызовов mark_printed(..., value)» |

## Статус дефектов
| # | Исполнитель | Где | Статус |
|---|---|---|---|
| D1 | Backend | `services/print_service.py` `setup_printer` | **Принято допуском** ±0.15 мм: фактически 85.725×53.975 мм (+0.125 / −0.025 мм) |
| D2 | Backend | `render/__init__.py` `_wrap`/`_split_breaks` | **Закрыт:** «Константинопольский-Водопьянов-Длиннофамильный» → 3 строки по дефисам, без обрезки |
| D3 | Backend | `render/__init__.py` `_fit_text` | **Закрыт:** видно 3 строки, bbox 117 ≤ 125 px, последняя строка заканчивается на «…», warning «показано строк N из M» |
| D4 | Data | `testdata/sets/*/photos` | **Открыт** (не перепроверялся): однотонные фото 60×80 |
| D5 | Backend/Frontend | `exporter.py:135-153`, `ui/main_window.py:111` | **Закрыт на уровне API:** `mark_printed` → print_mark=0 + printed_at; `set_print_mark` отдельно. Диалог «Снять отметки с N записей?» на Windows проверяет Иван (чек-лист, п. 6.6) |
| D6 | Frontend | `ui/*` — вызов `mark_printed(..., False)` | **Ожидался открытым, но фактически исправлен:** grep по ui/ находит только `mark_printed(ids)` (`backend_api.py:73-75`, `main_window.py:111`); флаг ставится через `set_print_mark` (`records_table.py:88,159`); AST-проверка в smoke_test проходит |
| **D7 (новый)** | Frontend | `ui/backend_api.py:53-54` `schema_version()` | **Открыт:** прямой SQL в UI: `self.con.execute("PRAGMA user_version")` нарушает правило «UI без прямого SQL». Исправление: вызывать функцию Backend (например, `db.schema_version(con)` / `api.schema_version`, если Backend её добавит). Важность низкая (только чтение) |
