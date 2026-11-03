# Этап 2 — Backend: рендер, импорт, экспорт, печать

Корень `/workspace/badge_generator`, весь код в `badge_backend/`. Подробное API в `README.md`.

## Что сделано
- **Рендер** `render_card(person, elements, side, background=None, base_dir=None)` возвращает PIL RGB ровно 1011×638. Порядок: фон (цвет, затем картинка cover), потом элементы по `z_order` (затем по id). Поддерживаются обе стороны. Типы: text, field, photo (трансформация по photo_config, без фото или с битым фото рисуется плейсхолдер), image, rect. Есть автоужатие и перенос текста, кириллица (DejaVu с фолбэками), скругления и рамки. Обёртки для БД: `render_card_db(con, id|row, side)` и `render_preview(..., scale)`.
- **qr/barcode**: схема их разрешает, но в v1 рендер их пропускает с `logging.warning` и `RuntimeWarning`. Библиотеки qrcode и python-barcode не подключены и удалены из venv. Это проверяет тест `test_qr_barcode_skipped_with_warning`.
- **Эталоны** лежат в `tests/golden/`: `front_full.png`, `front_no_photo.png`, `back.png`. Генерируются скриптом `tests/make_golden.py`. Тест допускает отличие не более 0.2% пикселей. Пример карточки: `examples/demo.png` и `examples/demo_back.png`.
- **Маппинг заголовков** (единый модуль) `badge_backend/services/headers.py`: `map_headers(headers, mapping=None)`, `header_key`, `slugify`, `split_fio`. Синонимы рус/англ, ФИО делится на три поля, неизвестные колонки получают транслит-slug, label = исходный заголовок. Модуль можно вызывать из data_tools.
- **Импорт** `import_file(con, path, mapping=None, photo_dir=None) -> ImportReport(added, skipped, errors, ids, validator)`. Поддерживаются .xlsx (openpyxl) и .csv (кодировки utf-8-sig и cp1251, разделитель `; , \t |` определяется автоматически). Пустые строки пропускаются. После маппинга вызывается **`data_tools.validate_import.validate_records(records, photos_dir, start_row=0)`**. Импорт мягкий: если модуля нет, работает встроенная проверка REQUIRED_MISSING с warning. Валидные записи нормализует `normalize_record`, дополнительные поля вроде employee_id сохраняются. Строки с ошибками не вставляются: они считаются в skipped и попадают в errors с номером строки Excel. Данные идут только в `fields_json`, а `photo_path` и `photo_config` пишутся в свои колонки. Проверено на `data_tools/testdata/sets/messy_headers/persons_raw.xlsx`: ФИО «Ёлкин Пётр Сергеевич» разбито на три поля, «ДОЛЖНОСТЬ», «Тел.», «E-mail» распознаны, «Лишняя колонка» стала `lishnyaya_kolonka`.
- **Экспорт** через Pillow: `export_png` сохраняет `<id>_<side>.png` 1011×638 с dpi 300, `export_pdf` делает по странице на сторону с MediaBox 242.64×153.07 pt = 85.6×54 мм. При `ids=None` берутся записи с `print_mark=1`. Есть `mark_printed(con, ids, value=True)`.
- **Печать** `services/print_service.py`: `print_cards(con, printer, sides, base_dir, ids=None)`. QPrinter приходит из Frontend после QPrintDialog. Печатаются только записи с `print_mark=1`. Размер страницы задаётся через `QPageSize` 85.6×54 мм (custom, ExactMatch), поля 0, `FullPage`. Рисование идёт через `QPainter.drawImage` на весь `paperRect`, каждая сторона на своей странице. Тест использует `OutputFormat.PdfFormat` при `QT_QPA_PLATFORM=offscreen`: 2 помеченных записи × 2 стороны = 4 страницы, каждая 85.6×54 мм (±0.3). Внешний PDF-просмотрщик не используется.
- **Фасад** `badge_backend/api.py` с CRUD persons и template_elements, а также `update_photo_config`, `set_background`/`get_background`, `list_fields`/`upsert_field` и реэкспортом рендера, импорта, экспорта и печати.

## Зависимости
`requirements.txt`: Pillow, openpyxl, PyQt6, pytest. **openpyxl — дополнительная зависимость.** Она указана в ТЗ пользователя, сначала ждала утверждения Архитектора, теперь утверждена. PyQt6 нужен только для `print_service` и импортируется лениво.

## Отличия от исходного ТЗ (по решениям Архитектора)
- Координаты задаются в px холста, а не в мм. photo_config v2: целые px для x/y/crop, angle по часовой.
- Печать перенесена в Backend через QPrinter.
- qr/barcode в v1 не реализованы.

## Общий прогон всех тестов (tests/ + data_tools/tests), pytest -v
```
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- /workspace/badge_generator/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /workspace/badge_generator
configfile: pytest.ini
testpaths: tests, data_tools/tests
collecting ... collected 87 items

tests/test_api.py::test_person_crud PASSED                               [  1%]
tests/test_api.py::test_update_photo_config PASSED                       [  2%]
tests/test_api.py::test_elements_crud PASSED                             [  3%]
tests/test_api.py::test_background_and_fields PASSED                     [  4%]
tests/test_import_export.py::test_map_headers_synonyms PASSED            [  5%]
tests/test_import_export.py::test_messy_headers_xlsx PASSED              [  6%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-sig-;] PASSED [  8%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-;] PASSED  [  9%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-,] PASSED   [ 10%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-\t] PASSED [ 11%]
tests/test_import_export.py::test_xlsx_photo_and_errors PASSED           [ 12%]
tests/test_import_export.py::test_unsupported_format PASSED              [ 13%]
tests/test_import_export.py::test_default_photo_config_on_import PASSED  [ 14%]
tests/test_import_export.py::test_export_png PASSED                      [ 16%]
tests/test_import_export.py::test_export_pdf_pages_cr80 PASSED           [ 17%]
tests/test_import_export.py::test_export_errors_and_mark PASSED          [ 18%]
tests/test_print.py::test_print_only_marked_each_side_own_page PASSED    [ 19%]
tests/test_print.py::test_print_front_only_and_ids_filter PASSED         [ 20%]
tests/test_print.py::test_print_nothing_marked PASSED                    [ 21%]
tests/test_render.py::test_size_and_mode_both_sides PASSED               [ 22%]
tests/test_render.py::test_empty_template_and_no_person PASSED           [ 24%]
tests/test_render.py::test_bad_side PASSED                               [ 25%]
tests/test_render.py::test_z_order_and_side_filter PASSED                [ 26%]
tests/test_render.py::test_background_color_and_image PASSED             [ 27%]
tests/test_render.py::test_field_and_cyrillic_font PASSED                [ 28%]
tests/test_render.py::test_align[left-l] PASSED                          [ 29%]
tests/test_render.py::test_align[right-r] PASSED                         [ 31%]
tests/test_render.py::test_text_autoshrink_stays_in_box PASSED           [ 32%]
tests/test_render.py::test_rect_border_radius PASSED                     [ 33%]
tests/test_render.py::test_photo_default_cover_fills_frame PASSED        [ 34%]
tests/test_render.py::test_photo_crop_xy_px PASSED                       [ 35%]
tests/test_render.py::test_photo_scale_zoom_center PASSED                [ 36%]
tests/test_render.py::test_photo_shift_xy PASSED                         [ 37%]
tests/test_render.py::test_photo_rotation_clockwise PASSED               [ 39%]
tests/test_render.py::test_photo_invalid_config_warns_and_defaults PASSED [ 40%]
tests/test_render.py::test_photo_in_card_and_missing_placeholder PASSED  [ 41%]
tests/test_render.py::test_qr_barcode_skipped_with_warning PASSED        [ 42%]
tests/test_render.py::test_preview PASSED                                [ 43%]
tests/test_render.py::test_golden[front_full] PASSED                     [ 44%]
tests/test_render.py::test_golden[front_no_photo] PASSED                 [ 45%]
tests/test_render.py::test_golden[back] PASSED                           [ 47%]
tests/test_schema.py::test_card_px PASSED                                [ 48%]
tests/test_schema.py::test_migration_from_scratch PASSED                 [ 49%]
tests/test_schema.py::test_defaults PASSED                               [ 50%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('field',0,0,1,1)] PASSED [ 51%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,side) VALUES ('text',0,0,1,1,'top')] PASSED [ 52%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('circle',0,0,1,1)] PASSED [ 54%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('rect',0,0,0,1)] PASSED [ 55%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,style_json) VALUES ('rect',0,0,1,1,'{bad')] PASSED [ 56%]
tests/test_schema.py::test_checks[INSERT INTO persons(print_mark) VALUES (2)] PASSED [ 57%]
tests/test_schema.py::test_checks[INSERT INTO persons(fields_json) VALUES ('not json')] PASSED [ 58%]
tests/test_schema.py::test_types_ok[qr] PASSED                           [ 59%]
tests/test_schema.py::test_types_ok[barcode] PASSED                      [ 60%]
tests/test_schema.py::test_types_ok[photo] PASSED                        [ 62%]
tests/test_schema.py::test_types_ok[image] PASSED                        [ 63%]
tests/test_schema.py::test_types_ok[text] PASSED                         [ 64%]
tests/test_schema.py::test_types_ok[rect] PASSED                         [ 65%]
tests/test_schema.py::test_roundtrip[0;0;1.0;0;0;0-exp0] PASSED          [ 66%]
tests/test_schema.py::test_roundtrip[10;-5;1.25;120;40;15.5-exp1] PASSED [ 67%]
tests/test_schema.py::test_roundtrip[3;4;2,5;0;0;-90-exp2] PASSED        [ 68%]
tests/test_schema.py::test_bad_gives_default_and_warning[1;2;3] PASSED   [ 70%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;0;0;0;0] PASSED [ 71%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;-1;0;0;0] PASSED [ 72%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0.5;0;0] PASSED [ 73%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0;1.5;0] PASSED [ 74%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;-3;0;0] PASSED [ 75%]
tests/test_schema.py::test_bad_gives_default_and_warning[a;0;1;0;0;0] PASSED [ 77%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;nan;0;0;0] PASSED [ 78%]
tests/test_schema.py::test_bad_gives_default_and_warning[1.5;0;1;0;0;0] PASSED [ 79%]
tests/test_schema.py::test_empty_is_default_silently PASSED              [ 80%]
data_tools/tests/test_clean_photos.py::test_clean_copies_and_reports PASSED [ 81%]
data_tools/tests/test_clean_photos.py::test_dry_run_writes_nothing PASSED [ 82%]
data_tools/tests/test_clean_photos.py::test_start_digits_and_report_dir PASSED [ 83%]
data_tools/tests/test_clean_photos.py::test_refuses_same_or_nested_out PASSED [ 85%]
data_tools/tests/test_clean_photos.py::test_refuses_nonempty_out PASSED  [ 86%]
data_tools/tests/test_clean_photos.py::test_natural_sort PASSED          [ 87%]
data_tools/tests/test_validate_import.py::test_validate_records_pure_ok PASSED [ 88%]
data_tools/tests/test_validate_import.py::test_validate_records_errors_and_rows PASSED [ 89%]
data_tools/tests/test_validate_import.py::test_check_columns PASSED      [ 90%]
data_tools/tests/test_validate_import.py::test_photo_config_format PASSED [ 91%]
data_tools/tests/test_validate_import.py::test_clean_set_cli PASSED      [ 93%]
data_tools/tests/test_validate_import.py::test_photo_errors PASSED       [ 94%]
data_tools/tests/test_validate_import.py::test_duplicates PASSED         [ 95%]
data_tools/tests/test_validate_import.py::test_missing_fields_cli PASSED [ 96%]
data_tools/tests/test_validate_import.py::test_large PASSED              [ 97%]
data_tools/tests/test_validate_import.py::test_cli_missing_column PASSED [ 98%]
data_tools/tests/test_validate_import.py::test_no_mapping_or_excel_in_module PASSED [100%]

============================== 87 passed in 0.81s ==============================
```
