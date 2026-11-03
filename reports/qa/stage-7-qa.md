# Этап 7 — QA: сквозная проверка импорт → рендер → экспорт → печать

**Проверял:** BG-Контролёр (в роли QA), 03.11.2026 (MSK). Продуктовый код и `.venv` не менялись.
**Скрипт:** `reports/qa/e2e_check.py` (публичный API `badge_backend.api`, временные БД в `/tmp/bgqa_*`).
**Вывод:** `reports/qa/e2e_output.txt`, `reports/qa/e2e_results.json`, pytest — `reports/qa/pytest_output.txt`.
Запуск: `QT_QPA_PLATFORM=offscreen .venv/bin/python reports/qa/e2e_check.py`

## Итог: **PASS** — e2e 26/26, pytest 137 passed / 0 failed. Блокирующих дефектов нет.

| # | Критерий | Результат | Доказательство |
|---|---|---|---|
| 1 | photo_config: формат, default `0;0;1.0;0;0;0`, crop целые, невалидное → default + warning | PASS | `'1;2;1,5;0.5;0;0'`→default (1 warning), `'abc'`→default (1 warning), `'5;-3;1.25;10;20;15.5'` сохраняется как есть |
| 2 | Схема persons (fields_json, photo_path, photo_config, print_mark) | PASS | PRAGMA table_info: id, fields_json, photo_path, photo_config, print_mark, created_at, updated_at; DEFAULT `'0;0;1.0;0;0;0'` |
| 3 | create_person с невалидным photo_config | PASS | сохранено `0;0;1.0;0;0;0`, warning=1 |
| 4 | Импорт 600 строк: CSV UTF-8 с BOM / без BOM / cp1251 × разделители `;` и `,` + xlsx | PASS | 7 вариантов × 600 добавлено, 0 пропущено, 600 строк в БД, **0 расхождений** при пополевом сравнении с исходником (источник: первые 600 строк из `sets/large`) |
| 5 | Набор large (1000 строк) | PASS | добавлено 1000, пропущено 0 |
| 6 | Транзакция: исключение на 300-й вставке → откат | PASS | RuntimeError('fail@300'), в persons 0 строк |
| 7 | Отмена импорта через progress → откат | PASS | cancelled=True, 0 строк |
| 8 | Набор clean | PASS | 5/5 добавлено |
| 9 | Набор duplicates | PASS | добавлено 2, пропущено 2 (DUPLICATE) |
| 10 | Набор missing_fields | PASS | добавлено 1, пропущено 4 (REQUIRED_MISSING, EMAIL_INVALID, PHONE_INVALID, PHOTO_CONFIG_INVALID) |
| 11 | Набор zero_byte_and_broken | PASS | добавлено 1, пропущено 3 (PHOTO_BROKEN, PHOTO_EMPTY, PHOTO_NOT_FOUND) |
| 12 | Набор messy_headers (xlsx, маппинг у Backend) | PASS | добавлено 2; ключи приведены к last_name/first_name/middle_name/…; лишняя колонка уходит в `lishnyaya_kolonka` |
| 13 | Импорт работает без data_tools | PASS | копия `badge_backend` в чистом sys.path: `builtin-fallback 600`, `data_tools` в sys.modules нет |
| 14 | Холст 1011×638 RGB | PASS | size=(1011, 638), mode=RGB |
| 15 | qr пропускается с warning | PASS | «элемент 13: тип 'qr' не поддерживается в v1, пропущен» |
| 16 | barcode (оборот) пропускается с warning | PASS | «элемент 14: тип 'barcode' …, пропущен» |
| 17 | Запись без фото не роняет рендер | PASS | плейсхолдер «нет фото», `card_no_photo.png`. Экспорт без `allow_missing_photo` даёт `MissingPhotosError ids=[6]` до записи файлов |
| 18 | Текст не выходит за рамку элемента | PASS | длинный текст в рамках 300×60 и 200×40: **0 пикселей вне рамок**, 2 warning об обрезке |
| 19 | Демо-макет: текст, поля, фото и картинки не пересекаются | PASS | пересечений нет |
| 20 | Экспорт PNG 1011×638 @300 DPI, ids=None → только print_mark=1 | PASS | 8 файлов (4 помеченные записи × 2 стороны из 7 в БД), у всех size (1011, 638) и dpi (300, 300) |
| 21 | Экспорт PDF, страницы 85.6×54 мм | PASS (допуск) | pdfinfo: 8 страниц, 242.64×153.12 pt = 85.60×54.02 мм (638 px / 300 DPI; допуск ±0.1 мм) |
| 22 | Печать: services/print → QPrinter → PDF (offscreen), только print_mark=1, страница CR80 | PASS (допуск) | print_cards=8, в PDF 8 страниц 243×153 pt = 85.725×53.975 мм; `reports/qa/print_output.pdf` |
| 23 | mark_printed; если ничего не помечено, 0 страниц | PASS | печать без меток → 0; mark_printed([1,2]) → 2; помечены [1, 2] |
| 24 | Один render_card | PASS | реализация только в `badge_backend/render/__init__.py:175`; `ui/backend_api.py:73` — обёртка, которая вызывает `_api.render_card_db` и переводит результат в QImage |
| 25 | Нет SQL в ui/ | PASS | grep `sqlite3`, `.execute(`, SELECT/INSERT/UPDATE/DELETE по ui/*.py ничего не нашёл. QPainter есть только в `ui/layout_editor.py` (редактор), это допускается |
| 26 | Нет маппинга заголовков и чтения Excel в data_tools | PASS | в продуктовом коде data_tools grep пусто. `check_columns` только проверяет наличие канонических колонок в CLI; openpyxl используется лишь в генераторе `testdata/make_testsets.py` |
| — | Полный pytest (tests + data_tools/tests) | PASS | **137 passed** за 3.70 с |
| — | Чистота корня и путей | PASS | PNG в корне нет; `/workspace/badge-generator` не существует |

## Дефекты и замечания (все неблокирующие)

| # | Исполнитель | Где | Описание | Важность |
|---|---|---|---|---|
| D1 | Backend | `badge_backend/services/print_service.py:22-31` (`setup_printer`) | PDF-драйвер Qt округляет страницу до целых pt: 243×153 pt = 85.725×53.975 мм, отклонение от 85.6 мм составляет +0.125 мм. Для физического принтера, скорее всего, неважно. Решить: принять допуск ±0.15 мм или задать размер в pt (242.65×153.07) и проверить | низкая |
| D2 | Backend | `badge_backend/render/__init__.py:101-110` (`_fit_text`/`_wrap`) | Длинное слово без пробелов (например, «Константинопольский-Водопьянов-Длиннофамильный») не переносится, в том числе по дефису, и обрезается по краю рамки с warning. По правилу Архитектора это допустимо, но на реальных двойных фамилиях текст будет обрезан. Пример: `card_long_text_rotated_photo.png` | низкая |
| D3 | Backend | там же, `_draw_text` | При обрезке по высоте нижняя строка может остаться частично видимой: обрезаются пиксели, а не целые строки (на примере виден обрывок глифа под 3-й строкой должности) | косметика |
| D4 | Data | `data_tools/testdata/sets/clean/photos/*.jpg`, `large/photos/default.jpg` | Тестовые фото однотонные 60×80 px (p1 залит одним цветом), поэтому сдвиг, кроп, масштаб и поворот из photo_config визуально проверить нельзя. Кроме того, 60×80 сильно меньше рамки фото 300×400 px. Нужны фото с узором не меньше 300×400 | низкая |
| — | Frontend | — | Дефектов не найдено | — |

## Примеры карточек (300 DPI)
- `reports/qa/card_clean_front.png` — запись из набора clean, лицевая сторона (qr пропущен с warning)
- `reports/qa/card_no_photo.png` — запись без фото, плейсхолдер
- `reports/qa/card_long_text_rotated_photo.png` — длинные поля (перенос, уменьшение шрифта, обрезка) и photo_config `40;-20;1.5;50;30;15`

Примечание к скрипту: в QA-рендере оборотной стороны `demo_logo.png` не находился, потому что `base_dir` указывал на папку фото. Это особенность тестовой обвязки, а не дефект продукта.
