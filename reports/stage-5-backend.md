# Этап 5 — Backend: импорт и экспорт (нагрузочные и сквозные тесты)

## Описание
Новый файл `tests/test_stage5.py`.
- Генерируются 600 строк. В значениях есть кириллица, ё, «ёлочки», запятые, точки с запятой, двойные кавычки и №. Заголовки русские: Фамилия, Имя, Отчество, Должность, Отдел, E-mail, Телефон, Примечание.
- CSV проверяется в кодировках UTF-8 с BOM, UTF-8 без BOM и cp1251, с разделителями `;` и `,` (6 вариантов). То же для xlsx.
- Импорт идёт через `import_file`, который вызывает `data_tools.validate_import.validate_records`. Проверки: added = 600, skipped = 0, ошибок нет. Каждое поле каждой записи в БД совпадает с исходником. Повторный `validate_records` по данным из БД возвращает пустой список.
- Транзакция: на весь импорт приходится ровно один `COMMIT` (по trace_callback). При сбое на 300-й вставке откатывается всё: 0 записей в persons и person_fields.
- Автоопределение разделителя проверено на кавычках, внутри которых есть чужой разделитель.
- Экспорт PDF на 60 карточек × 2 стороны даёт 120 страниц, каждая 85.6×54 мм.

## Прогоны (импорт 600 строк, файловая SQLite)
| вариант | строк | добавлено | время |
|---|---|---|---|
| csv utf-8-sig ';' | 600 | 600 | 23 мс |
| csv utf-8-sig ',' | 600 | 600 | 24 мс |
| csv utf-8 ';' | 600 | 600 | 19 мс |
| csv utf-8 ',' | 600 | 600 | 20 мс |
| csv cp1251 ';' | 600 | 600 | 20 мс |
| csv cp1251 ',' | 600 | 600 | 22 мс |
| xlsx | 600 | 600 | 51 мс |
| pdf 60×2 | 60 | 120 | 1719 мс |

Импорт 600 строк занимает около 20–55 мс одной транзакцией. Последняя строка таблицы — экспорт PDF (карточек / страниц / время).

## Исправленные баги
1. **Потеря данных в доп. полях.** `_cell` схлопывал все пробельные символы, поэтому многострочные ячейки и двойные пробелы портились («строка 1\nстрока  2» превращалась в «строка 1 строка 2»). Теперь значение только обрезается по краям, а `\r\n` заменяется на `\n`. Канонические поля persons по-прежнему нормализует `data_tools.normalize_record`: это их правило, я его не менял.
2. **Даты из xlsx** попадали в базу как `2026-11-03 00:00:00`. Теперь пишется ISO-дата `2026-11-03`, а если время ненулевое — дата и время. bool сохраняется как 1/0.
Покрыто тестом `test_cells_preserved_extra_fields`. Других расхождений на 600 строках не нашлось.

## Независимость ядра от data_tools (дополнение)
Проверка: в `badge_backend/` нет импорта `data_tools` на уровне модулей. Единственное обращение — ленивый `from data_tools import validate_import` внутри `services/importer.py::_validate`, обёрнутый в `try/except ImportError`. Ядро уже было устроено так, исправлять структуру не пришлось.

Изменения в `services/importer.py`:
- если data_tools недоступен, кроме `logging.warning` теперь выдаётся `RuntimeWarning`, чтобы вызывающий код мог его поймать;
- добавлена константа `FALLBACK_VALIDATOR = "builtin-fallback"`, это значение `report.validator` при фолбэке (раньше было `"builtin"`); значение по умолчанию поля `ImportReport.validator` теперь пустое.

Новые тесты в `tests/test_no_data_tools.py` (4 шт.):
1. `test_no_module_level_data_tools_import` — AST-проверка верхнего уровня всех модулей ядра.
2. `test_import_core_does_not_load_data_tools` — в отдельном процессе после `import badge_backend, badge_backend.api` модуля `data_tools` нет в `sys.modules`.
3. `test_fallback_when_data_tools_blocked` — `monkeypatch` подставляет `sys.modules["data_tools"] = None`. Ожидается RuntimeWarning, `validator == "builtin-fallback"`, 50 из 50 строк импортированы. Фолбэк всё равно отсекает строки без фамилии или имени (REQUIRED_MISSING).
4. `test_fallback_subprocess_clean_sys_path` — копия одного `badge_backend` во временную папку, `sys.path` без корня проекта и без `PYTHONPATH`. `import data_tools` даёт ImportError. Импорт 600 строк CSV выдаёт warning и результат `builtin-fallback 600 0`.

## pytest -v (tests + data_tools/tests, QT_QPA_PLATFORM=offscreen)
```
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- /workspace/badge_generator/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /workspace/badge_generator
configfile: pytest.ini
collecting ... collected 103 items

tests/test_api.py::test_person_crud PASSED                               [  0%]
tests/test_api.py::test_update_photo_config PASSED                       [  1%]
tests/test_api.py::test_elements_crud PASSED                             [  2%]
tests/test_api.py::test_background_and_fields PASSED                     [  3%]
tests/test_import_export.py::test_map_headers_synonyms PASSED            [  4%]
tests/test_import_export.py::test_messy_headers_xlsx PASSED              [  5%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-sig-;] PASSED [  6%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-;] PASSED  [  7%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-,] PASSED   [  8%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-\t] PASSED [  9%]
tests/test_import_export.py::test_xlsx_photo_and_errors PASSED           [ 10%]
tests/test_import_export.py::test_unsupported_format PASSED              [ 11%]
tests/test_import_export.py::test_default_photo_config_on_import PASSED  [ 12%]
tests/test_import_export.py::test_export_png PASSED                      [ 13%]
tests/test_import_export.py::test_export_pdf_pages_cr80 PASSED           [ 14%]
tests/test_import_export.py::test_export_errors_and_mark PASSED          [ 15%]
tests/test_no_data_tools.py::test_no_module_level_data_tools_import PASSED [ 16%]
tests/test_no_data_tools.py::test_import_core_does_not_load_data_tools PASSED [ 17%]
tests/test_no_data_tools.py::test_fallback_when_data_tools_blocked PASSED [ 18%]
tests/test_no_data_tools.py::test_fallback_subprocess_clean_sys_path PASSED [ 19%]
tests/test_print.py::test_print_only_marked_each_side_own_page PASSED    [ 20%]
tests/test_print.py::test_print_front_only_and_ids_filter PASSED         [ 21%]
tests/test_print.py::test_print_nothing_marked PASSED                    [ 22%]
tests/test_render.py::test_size_and_mode_both_sides PASSED               [ 23%]
tests/test_render.py::test_empty_template_and_no_person PASSED           [ 24%]
tests/test_render.py::test_bad_side PASSED                               [ 25%]
tests/test_render.py::test_z_order_and_side_filter PASSED                [ 26%]
tests/test_render.py::test_background_color_and_image PASSED             [ 27%]
tests/test_render.py::test_field_and_cyrillic_font PASSED                [ 28%]
tests/test_render.py::test_align[left-l] PASSED                          [ 29%]
tests/test_render.py::test_align[right-r] PASSED                         [ 30%]
tests/test_render.py::test_text_autoshrink_stays_in_box PASSED           [ 31%]
tests/test_render.py::test_rect_border_radius PASSED                     [ 32%]
tests/test_render.py::test_photo_default_cover_fills_frame PASSED        [ 33%]
tests/test_render.py::test_photo_crop_xy_px PASSED                       [ 33%]
tests/test_render.py::test_photo_scale_zoom_center PASSED                [ 34%]
tests/test_render.py::test_photo_shift_xy PASSED                         [ 35%]
tests/test_render.py::test_photo_rotation_clockwise PASSED               [ 36%]
tests/test_render.py::test_photo_invalid_config_warns_and_defaults PASSED [ 37%]
tests/test_render.py::test_photo_in_card_and_missing_placeholder PASSED  [ 38%]
tests/test_render.py::test_qr_barcode_skipped_with_warning PASSED        [ 39%]
tests/test_render.py::test_preview PASSED                                [ 40%]
tests/test_render.py::test_golden[front_full] PASSED                     [ 41%]
tests/test_render.py::test_golden[front_no_photo] PASSED                 [ 42%]
tests/test_render.py::test_golden[back] PASSED                           [ 43%]
tests/test_schema.py::test_card_px PASSED                                [ 44%]
tests/test_schema.py::test_migration_from_scratch PASSED                 [ 45%]
tests/test_schema.py::test_defaults PASSED                               [ 46%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('field',0,0,1,1)] PASSED [ 47%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,side) VALUES ('text',0,0,1,1,'top')] PASSED [ 48%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('circle',0,0,1,1)] PASSED [ 49%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('rect',0,0,0,1)] PASSED [ 50%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,style_json) VALUES ('rect',0,0,1,1,'{bad')] PASSED [ 51%]
tests/test_schema.py::test_checks[INSERT INTO persons(print_mark) VALUES (2)] PASSED [ 52%]
tests/test_schema.py::test_checks[INSERT INTO persons(fields_json) VALUES ('not json')] PASSED [ 53%]
tests/test_schema.py::test_types_ok[qr] PASSED                           [ 54%]
tests/test_schema.py::test_types_ok[barcode] PASSED                      [ 55%]
tests/test_schema.py::test_types_ok[photo] PASSED                        [ 56%]
tests/test_schema.py::test_types_ok[image] PASSED                        [ 57%]
tests/test_schema.py::test_types_ok[text] PASSED                         [ 58%]
tests/test_schema.py::test_types_ok[rect] PASSED                         [ 59%]
tests/test_schema.py::test_roundtrip[0;0;1.0;0;0;0-exp0] PASSED          [ 60%]
tests/test_schema.py::test_roundtrip[10;-5;1.25;120;40;15.5-exp1] PASSED [ 61%]
tests/test_schema.py::test_roundtrip[3;4;2,5;0;0;-90-exp2] PASSED        [ 62%]
tests/test_schema.py::test_bad_gives_default_and_warning[1;2;3] PASSED   [ 63%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;0;0;0;0] PASSED [ 64%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;-1;0;0;0] PASSED [ 65%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0.5;0;0] PASSED [ 66%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0;1.5;0] PASSED [ 66%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;-3;0;0] PASSED [ 67%]
tests/test_schema.py::test_bad_gives_default_and_warning[a;0;1;0;0;0] PASSED [ 68%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;nan;0;0;0] PASSED [ 69%]
tests/test_schema.py::test_bad_gives_default_and_warning[1.5;0;1;0;0;0] PASSED [ 70%]
tests/test_schema.py::test_empty_is_default_silently PASSED              [ 71%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-sig-;] PASSED          [ 72%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-sig-,] PASSED          [ 73%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-;] PASSED              [ 74%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-,] PASSED              [ 75%]
tests/test_stage5.py::test_csv_600_lossless[cp1251-;] PASSED             [ 76%]
tests/test_stage5.py::test_csv_600_lossless[cp1251-,] PASSED             [ 77%]
tests/test_stage5.py::test_xlsx_600_lossless PASSED                      [ 78%]
tests/test_stage5.py::test_import_single_transaction PASSED              [ 79%]
tests/test_stage5.py::test_header_only_quotes_sniff PASSED               [ 80%]
tests/test_stage5.py::test_export_pdf_60_cards PASSED                    [ 81%]
tests/test_stage5.py::test_zz_write_timings PASSED                       [ 82%]
tests/test_stage5.py::test_cells_preserved_extra_fields PASSED           [ 83%]
data_tools/tests/test_clean_photos.py::test_clean_copies_and_reports PASSED [ 84%]
data_tools/tests/test_clean_photos.py::test_dry_run_writes_nothing PASSED [ 85%]
data_tools/tests/test_clean_photos.py::test_start_digits_and_report_dir PASSED [ 86%]
data_tools/tests/test_clean_photos.py::test_refuses_same_or_nested_out PASSED [ 87%]
data_tools/tests/test_clean_photos.py::test_refuses_nonempty_out PASSED  [ 88%]
data_tools/tests/test_clean_photos.py::test_natural_sort PASSED          [ 89%]
data_tools/tests/test_validate_import.py::test_validate_records_pure_ok PASSED [ 90%]
data_tools/tests/test_validate_import.py::test_validate_records_errors_and_rows PASSED [ 91%]
data_tools/tests/test_validate_import.py::test_check_columns PASSED      [ 92%]
data_tools/tests/test_validate_import.py::test_photo_config_format PASSED [ 93%]
data_tools/tests/test_validate_import.py::test_clean_set_cli PASSED      [ 94%]
data_tools/tests/test_validate_import.py::test_photo_errors PASSED       [ 95%]
data_tools/tests/test_validate_import.py::test_duplicates PASSED         [ 96%]
data_tools/tests/test_validate_import.py::test_missing_fields_cli PASSED [ 97%]
data_tools/tests/test_validate_import.py::test_large PASSED              [ 98%]
data_tools/tests/test_validate_import.py::test_cli_missing_column PASSED [ 99%]
data_tools/tests/test_validate_import.py::test_no_mapping_or_excel_in_module PASSED [100%]

============================= 103 passed in 2.89s ==============================
```
