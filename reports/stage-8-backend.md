# Этап 8 — Backend: исправления по QA (reports/qa/stage-7-qa.md)

Изменены: `badge_backend/render/__init__.py` (D2, D3), `badge_backend/db.py` (D5, миграция v2), `badge_backend/services/exporter.py` и `api.py` (D5: `mark_printed` / `set_print_mark`), README. Новые тесты: `tests/test_stage8.py` (13), `tests/test_d5_printed_at.py` (10), `tests/test_photo_transform.py` (37), эталоны `tests/golden/photo_*.png` (4 шт.). Обновлены `tests/test_schema.py` (LATEST=2) и `tests/test_import_export.py` (вызовы переведены на `set_print_mark`). Код печати, `ui/`, `data_tools/` и `.venv` не менялись. Существующие golden PNG перегенерировать не понадобилось: демо отрисовывается без обрезки, побайтное сравнение проходит.

**Итог: 205 passed, 0 failed** (180 в tests/, 25 в data_tools/tests).
Примечание: во время одного из промежуточных прогонов BG-Data перегенерировал testdata (около 16:37 MSK), и два теста упали на недописанных файлах. Повторный прогон зелёный.

## D2 — перенос длинных слов (решение Архитектора, порядок строгий)
1. Перенос по пробелам. Слово, которое не влезает в строку целиком, переносится по дефису, тире (`- ‐ ‑ ‒ – — ―`) или слэшу `/`. Знак остаётся в конце строки: «Римский-» / «Корсаков». Если слово целиком влезает на новую строку, оно переносится по пробелу, а дефис не трогается.
2. Шрифт уменьшается до `style.min_size` (по умолчанию 8 pt).
3. Только при min_size кусок, который всё ещё шире рамки, режется по символам, и выдаётся warning «слово разрезано по символам». До уменьшения шрифта посимвольный перенос не применяется.
4. Обрезка (D3).
Код: `_split_breaks`, `_wrap(d, text, font, width, force=False) -> (lines, cut)`, `_fit_text(...) -> (..., notes)`.

## D3 — без частично видимых строк
Если строки не помещаются по высоте при min_size, рисуются только строки, которые целиком входят в рамку по реальному bbox глифов. В конец последней видимой строки ставится «…»: при нехватке места символы удаляются, пока «…» не влезет. Частично видимая строка не рисуется вообще. Если в рамку не входит ни одна строка, ничего не рисуется. Warning остаётся, в нём указано «показано строк N из M». Слой w×h по-прежнему страхует от выхода за рамку.

## D1 — страница +0.125 мм
Решение Архитектора: принят допуск ±0.15 мм, код печати не менялся. Тесты используют `page_size_ok(w, h, tol=0.15)`: проверку реального PDF из QPrinter (получается 85.725×53.975 мм) и границу допуска (0.15 принимается, 0.16 отклоняется).
Вариант исправления на будущее: задать `QPageSize(QSizeF(85.6, 54.0), QPageSize.Unit.Millimeter, "CR80", QPageSize.SizeMatchPolicy.ExactMatch)`. Qt PDF-движок всё равно хранит размер в целых pt, поэтому нужен MediaBox в точных единицах: `QPageSize(QSizeF(242.65, 153.07), Unit.Point)` с последующей проверкой pdfinfo, либо PDF-экспорт через Pillow (уже даёт 85.60×54.02 мм). Для физического принтера разница не важна.

## Тесты (`tests/test_stage8.py`, 13 шт.)
- D1: `test_page_tolerance_boundary`, `test_qprinter_pdf_page_within_tolerance`.
- D2: `test_wrap_on_hyphen_keeps_hyphen`, `test_wrap_on_dashes_and_slash[/ — –]`, `test_spaces_before_hyphens`, `test_order_shrink_before_char_split` (слово уменьшается, а не режется), `test_double_surname_no_warning_in_frame`, `test_char_split_only_at_min_size_with_warning`.
- D3: `test_truncate_whole_lines_with_ellipsis` (bbox видимых строк ≤ h, «…» в конце), `test_no_partial_line_pixels` (обрезанный рендер побайтно равен рендеру только видимых строк, т. е. обрывков глифов нет, а bbox пикселей внутри рамки), `test_no_line_fits_draws_nothing`.

## D4 — проверка трансформации фото на фикстурах BG-Data
Фикстуры `data_tools/testdata/fixtures/photo_config/` (три PNG и `markers.json`) только читаются.
- `test_markers_land_where_expected` (3 файла × 10 конфигов): позиция каждого маркера в рамке считается аналитически по порядку crop → cover×scale → поворот по часовой (в координатах с осью y вниз: `x' = x·cos − y·sin`, `y' = x·sin + y·cos`) → центр рамки + (x, y). Цвет проверяется в окрестности ±2 px с допуском 60. Маркеры, отрезанные crop или вышедшие за рамку, пропускаются, но в каждом случае проверяется не меньше 2 маркеров. Конфиги: default, scale 1.5 и 0.8, сдвиг (20, −15), crop (40, 30), angle 90, −90, 30, 180 и комбинированный `15;10;1.3;20;40;15`. Рамка 300×400 для портретов и 400×300 для ландшафта.
- `test_rotation_is_clockwise_arrow_up` (3): при angle=90 остриё стрелки UP оказывается правее центра (стрелка смотрит вправо), а красный TL-квадрат уходит в правый верхний квадрант. Значит, поворот идёт по часовой.
- `test_photo_golden` (4): эталоны `tests/golden/photo_*.png`, допускается не больше 0.2% пикселей с отличием больше 24. Перегенерация: `PYTHONPATH=. python tests/test_photo_transform.py`.
Багов трансформации не найдено, код `transform_photo` не менялся.

## D5 — printed_at и разделение «к печати» / «напечатано» (решение Архитектора)
- Миграция v2 (`db.py`): `MIGRATIONS = [SCHEMA, _v2_printed_at]`, шаг `ALTER TABLE persons ADD COLUMN printed_at TEXT NULL`. Шаг выполняется только если столбца нет (идемпотентно), в отдельной транзакции с откатом при ошибке. `schema.sql` остаётся v1, `user_version=2`.
- Формат `printed_at`: `NULL` или ISO 8601, локальное время со смещением, точность до секунд, например `"2026-11-03T16:40:12+03:00"` (`db.now_iso()` = `datetime.now().astimezone().isoformat(timespec="seconds")`). Возвращается в `api.get_person` и `api.list_persons` (строка или `None`).
- `set_print_mark(con, ids, value: bool) -> int`: флаг «к печати» (1/0), `printed_at` не трогает. Экспортируется через `api`.
- `mark_printed(con, ids) -> int`: «напечатано», одной транзакцией `print_mark=0` и `printed_at=now`, при ошибке откат. Параметра `value` нет («одна функция — один смысл»), лишний аргумент даёт `TypeError`.
- **Frontend:** `mark_printed(ids, value)` в `ui/backend_api.py:61`, `ui/records_table.py:123` и `ui/smoke_test.py:146,156` нужно заменить на `set_print_mark(con, ids, value)`. После успешной печати вызывать `mark_printed(con, напечатанные_ids)`. Сейчас UI передаёт `value` всегда, поэтому до правки получит `TypeError`. QA-скрипт `reports/qa/e2e_check.py:130,152,155` тоже нужно перевести на `set_print_mark`.
- Тесты (`tests/test_d5_printed_at.py`, 10): миграция старой v1-БД с данными (данные целы, столбец есть, `user_version=2`, `printed_at=None`), повторная миграция и миграция при уже существующем столбце, новая БД, `mark_printed` ставит 0 и ISO-время и не трогает другие записи, `set_print_mark(True/False)` сохраняет `printed_at`, лишний аргумент (позиционный и `value=`) даёт `TypeError` без изменений в БД, откат транзакции при ошибке на второй записи.

## pytest -v (tests + data_tools/tests, QT_QPA_PLATFORM=offscreen)
```
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- /workspace/badge_generator/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /workspace/badge_generator
configfile: pytest.ini
collecting ... collected 205 items

tests/test_api.py::test_person_crud PASSED                               [  0%]
tests/test_api.py::test_update_photo_config PASSED                       [  0%]
tests/test_api.py::test_elements_crud PASSED                             [  1%]
tests/test_api.py::test_background_and_fields PASSED                     [  1%]
tests/test_api_fixes.py::test_default_db_path PASSED                     [  2%]
tests/test_api_fixes.py::test_mapping_exclude_column PASSED              [  2%]
tests/test_api_fixes.py::test_manual_canonical_label_and_labels_param PASSED [  3%]
tests/test_api_fixes.py::test_import_photo_missing_default_is_warning PASSED [  3%]
tests/test_api_fixes.py::test_import_require_photo_strict PASSED         [  4%]
tests/test_api_fixes.py::test_import_fallback_photo_missing PASSED       [  4%]
tests/test_api_fixes.py::test_import_progress_and_cancel PASSED          [  5%]
tests/test_api_fixes.py::test_export_progress_and_cancel PASSED          [  5%]
tests/test_api_fixes.py::test_person_formats[json_str] PASSED            [  6%]
tests/test_api_fixes.py::test_person_formats[json_dict] PASSED           [  6%]
tests/test_api_fixes.py::test_person_formats[fields] PASSED              [  7%]
tests/test_api_fixes.py::test_person_formats[row] PASSED                 [  7%]
tests/test_api_fixes.py::test_render_preview_with_draft_dict PASSED      [  8%]
tests/test_api_fixes.py::test_snapshot_export_in_thread_memory_db PASSED [  8%]
tests/test_api_fixes.py::test_missing_photos_precheck PASSED             [  9%]
tests/test_api_fixes.py::test_export_missing_photo_strict_and_allowed PASSED [  9%]
tests/test_d5_printed_at.py::test_migrate_old_v1_db PASSED               [ 10%]
tests/test_d5_printed_at.py::test_migrate_repeat_idempotent PASSED       [ 10%]
tests/test_d5_printed_at.py::test_new_db_has_printed_at PASSED           [ 11%]
tests/test_d5_printed_at.py::test_mark_printed_sets_time_and_clears_mark PASSED [ 11%]
tests/test_d5_printed_at.py::test_set_print_mark_keeps_printed_at PASSED [ 12%]
tests/test_d5_printed_at.py::test_mark_printed_has_no_value_param[args0] PASSED [ 12%]
tests/test_d5_printed_at.py::test_mark_printed_has_no_value_param[args1] PASSED [ 13%]
tests/test_d5_printed_at.py::test_mark_printed_has_no_value_param[args2] PASSED [ 13%]
tests/test_d5_printed_at.py::test_mark_printed_no_value_no_warning PASSED [ 14%]
tests/test_d5_printed_at.py::test_mark_printed_rollback PASSED           [ 14%]
tests/test_import_export.py::test_map_headers_synonyms PASSED            [ 15%]
tests/test_import_export.py::test_messy_headers_xlsx PASSED              [ 15%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-sig-;] PASSED [ 16%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-;] PASSED  [ 16%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-,] PASSED   [ 17%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-\t] PASSED [ 17%]
tests/test_import_export.py::test_xlsx_photo_and_errors PASSED           [ 18%]
tests/test_import_export.py::test_unsupported_format PASSED              [ 18%]
tests/test_import_export.py::test_default_photo_config_on_import PASSED  [ 19%]
tests/test_import_export.py::test_export_png PASSED                      [ 19%]
tests/test_import_export.py::test_export_pdf_pages_cr80 PASSED           [ 20%]
tests/test_import_export.py::test_export_errors_and_mark PASSED          [ 20%]
tests/test_no_data_tools.py::test_no_module_level_data_tools_import PASSED [ 20%]
tests/test_no_data_tools.py::test_import_core_does_not_load_data_tools PASSED [ 21%]
tests/test_no_data_tools.py::test_fallback_when_data_tools_blocked PASSED [ 21%]
tests/test_no_data_tools.py::test_fallback_subprocess_clean_sys_path PASSED [ 22%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;0-portrait_300x400.png] PASSED [ 22%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;0-portrait_600x800.png] PASSED [ 23%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;0-landscape_400x300.png] PASSED [ 23%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.5;0;0;0-portrait_300x400.png] PASSED [ 24%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.5;0;0;0-portrait_600x800.png] PASSED [ 24%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.5;0;0;0-landscape_400x300.png] PASSED [ 25%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;0.8;0;0;0-portrait_300x400.png] PASSED [ 25%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;0.8;0;0;0-portrait_600x800.png] PASSED [ 26%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;0.8;0;0;0-landscape_400x300.png] PASSED [ 26%]
tests/test_photo_transform.py::test_markers_land_where_expected[20;-15;1.0;0;0;0-portrait_300x400.png] PASSED [ 27%]
tests/test_photo_transform.py::test_markers_land_where_expected[20;-15;1.0;0;0;0-portrait_600x800.png] PASSED [ 27%]
tests/test_photo_transform.py::test_markers_land_where_expected[20;-15;1.0;0;0;0-landscape_400x300.png] PASSED [ 28%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;40;30;0-portrait_300x400.png] PASSED [ 28%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;40;30;0-portrait_600x800.png] PASSED [ 29%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;40;30;0-landscape_400x300.png] PASSED [ 29%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;90-portrait_300x400.png] PASSED [ 30%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;90-portrait_600x800.png] PASSED [ 30%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;90-landscape_400x300.png] PASSED [ 31%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;-90-portrait_300x400.png] PASSED [ 31%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;-90-portrait_600x800.png] PASSED [ 32%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;-90-landscape_400x300.png] PASSED [ 32%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;30-portrait_300x400.png] PASSED [ 33%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;30-portrait_600x800.png] PASSED [ 33%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;30-landscape_400x300.png] PASSED [ 34%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;180-portrait_300x400.png] PASSED [ 34%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;180-portrait_600x800.png] PASSED [ 35%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;180-landscape_400x300.png] PASSED [ 35%]
tests/test_photo_transform.py::test_markers_land_where_expected[15;10;1.3;20;40;15-portrait_300x400.png] PASSED [ 36%]
tests/test_photo_transform.py::test_markers_land_where_expected[15;10;1.3;20;40;15-portrait_600x800.png] PASSED [ 36%]
tests/test_photo_transform.py::test_markers_land_where_expected[15;10;1.3;20;40;15-landscape_400x300.png] PASSED [ 37%]
tests/test_photo_transform.py::test_rotation_is_clockwise_arrow_up[portrait_300x400.png] PASSED [ 37%]
tests/test_photo_transform.py::test_rotation_is_clockwise_arrow_up[portrait_600x800.png] PASSED [ 38%]
tests/test_photo_transform.py::test_rotation_is_clockwise_arrow_up[landscape_400x300.png] PASSED [ 38%]
tests/test_photo_transform.py::test_photo_golden[portrait_300x400.png-0;0;1.0;0;0;0] PASSED [ 39%]
tests/test_photo_transform.py::test_photo_golden[portrait_600x800.png-15;10;1.3;20;40;15] PASSED [ 39%]
tests/test_photo_transform.py::test_photo_golden[landscape_400x300.png-0;0;1.0;0;0;90] PASSED [ 40%]
tests/test_photo_transform.py::test_photo_golden[landscape_400x300.png--20;0;1.2;60;0;-30] PASSED [ 40%]
tests/test_print.py::test_print_only_marked_each_side_own_page PASSED    [ 40%]
tests/test_print.py::test_print_front_only_and_ids_filter PASSED         [ 41%]
tests/test_print.py::test_print_nothing_marked PASSED                    [ 41%]
tests/test_print.py::test_print_missing_photo_strict_nothing_printed PASSED [ 42%]
tests/test_print.py::test_print_missing_photo_allowed_reports_ids PASSED [ 42%]
tests/test_print.py::test_print_progress_cancel_and_snapshot PASSED      [ 43%]
tests/test_render.py::test_size_and_mode_both_sides PASSED               [ 43%]
tests/test_render.py::test_empty_template_and_no_person PASSED           [ 44%]
tests/test_render.py::test_bad_side PASSED                               [ 44%]
tests/test_render.py::test_z_order_and_side_filter PASSED                [ 45%]
tests/test_render.py::test_background_color_and_image PASSED             [ 45%]
tests/test_render.py::test_field_and_cyrillic_font PASSED                [ 46%]
tests/test_render.py::test_align[left-l] PASSED                          [ 46%]
tests/test_render.py::test_align[right-r] PASSED                         [ 47%]
tests/test_render.py::test_text_autoshrink_stays_in_box PASSED           [ 47%]
tests/test_render.py::test_rect_border_radius PASSED                     [ 48%]
tests/test_render.py::test_photo_default_cover_fills_frame PASSED        [ 48%]
tests/test_render.py::test_photo_crop_xy_px PASSED                       [ 49%]
tests/test_render.py::test_photo_scale_zoom_center PASSED                [ 49%]
tests/test_render.py::test_photo_shift_xy PASSED                         [ 50%]
tests/test_render.py::test_photo_rotation_clockwise PASSED               [ 50%]
tests/test_render.py::test_photo_invalid_config_warns_and_defaults PASSED [ 51%]
tests/test_render.py::test_photo_in_card_and_missing_placeholder PASSED  [ 51%]
tests/test_render.py::test_qr_barcode_skipped_with_warning PASSED        [ 52%]
tests/test_render.py::test_preview PASSED                                [ 52%]
tests/test_render.py::test_golden[front_full] PASSED                     [ 53%]
tests/test_render.py::test_golden[front_no_photo] PASSED                 [ 53%]
tests/test_render.py::test_golden[back] PASSED                           [ 54%]
tests/test_schema.py::test_card_px PASSED                                [ 54%]
tests/test_schema.py::test_migration_from_scratch PASSED                 [ 55%]
tests/test_schema.py::test_defaults PASSED                               [ 55%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('field',0,0,1,1)] PASSED [ 56%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,side) VALUES ('text',0,0,1,1,'top')] PASSED [ 56%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('circle',0,0,1,1)] PASSED [ 57%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('rect',0,0,0,1)] PASSED [ 57%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,style_json) VALUES ('rect',0,0,1,1,'{bad')] PASSED [ 58%]
tests/test_schema.py::test_checks[INSERT INTO persons(print_mark) VALUES (2)] PASSED [ 58%]
tests/test_schema.py::test_checks[INSERT INTO persons(fields_json) VALUES ('not json')] PASSED [ 59%]
tests/test_schema.py::test_types_ok[qr] PASSED                           [ 59%]
tests/test_schema.py::test_types_ok[barcode] PASSED                      [ 60%]
tests/test_schema.py::test_types_ok[photo] PASSED                        [ 60%]
tests/test_schema.py::test_types_ok[image] PASSED                        [ 60%]
tests/test_schema.py::test_types_ok[text] PASSED                         [ 61%]
tests/test_schema.py::test_types_ok[rect] PASSED                         [ 61%]
tests/test_schema.py::test_roundtrip[0;0;1.0;0;0;0-exp0] PASSED          [ 62%]
tests/test_schema.py::test_roundtrip[10;-5;1.25;120;40;15.5-exp1] PASSED [ 62%]
tests/test_schema.py::test_roundtrip[3;4;2,5;0;0;-90-exp2] PASSED        [ 63%]
tests/test_schema.py::test_bad_gives_default_and_warning[1;2;3] PASSED   [ 63%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;0;0;0;0] PASSED [ 64%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;-1;0;0;0] PASSED [ 64%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0.5;0;0] PASSED [ 65%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0;1.5;0] PASSED [ 65%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;-3;0;0] PASSED [ 66%]
tests/test_schema.py::test_bad_gives_default_and_warning[a;0;1;0;0;0] PASSED [ 66%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;nan;0;0;0] PASSED [ 67%]
tests/test_schema.py::test_bad_gives_default_and_warning[1.5;0;1;0;0;0] PASSED [ 67%]
tests/test_schema.py::test_empty_is_default_silently PASSED              [ 68%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-sig-;] PASSED          [ 68%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-sig-,] PASSED          [ 69%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-;] PASSED              [ 69%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-,] PASSED              [ 70%]
tests/test_stage5.py::test_csv_600_lossless[cp1251-;] PASSED             [ 70%]
tests/test_stage5.py::test_csv_600_lossless[cp1251-,] PASSED             [ 71%]
tests/test_stage5.py::test_xlsx_600_lossless PASSED                      [ 71%]
tests/test_stage5.py::test_import_single_transaction PASSED              [ 72%]
tests/test_stage5.py::test_header_only_quotes_sniff PASSED               [ 72%]
tests/test_stage5.py::test_export_pdf_60_cards PASSED                    [ 73%]
tests/test_stage5.py::test_zz_write_timings PASSED                       [ 73%]
tests/test_stage5.py::test_cells_preserved_extra_fields PASSED           [ 74%]
tests/test_stage8.py::test_page_tolerance_boundary PASSED                [ 74%]
tests/test_stage8.py::test_qprinter_pdf_page_within_tolerance PASSED     [ 75%]
tests/test_stage8.py::test_wrap_on_hyphen_keeps_hyphen PASSED            [ 75%]
tests/test_stage8.py::test_wrap_on_dashes_and_slash[\u041e\u041e\u041e/\u0420\u043e\u043c\u0430\u0448\u043a\u0430-\u041e\u041e\u041e/] PASSED [ 76%]
tests/test_stage8.py::test_wrap_on_dashes_and_slash[\u0410\u043b\u044c\u0444\u0430\u2014\u0411\u0435\u0442\u0430\u0433\u0430\u043c\u043c\u0430-\u0410\u043b\u044c\u0444\u0430\u2014] PASSED [ 76%]
tests/test_stage8.py::test_wrap_on_dashes_and_slash[\u0410\u043b\u044c\u0444\u0430\u2013\u0411\u0435\u0442\u0430\u0433\u0430\u043c\u043c\u0430-\u0410\u043b\u044c\u0444\u0430\u2013] PASSED [ 77%]
tests/test_stage8.py::test_spaces_before_hyphens PASSED                  [ 77%]
tests/test_stage8.py::test_order_shrink_before_char_split PASSED         [ 78%]
tests/test_stage8.py::test_double_surname_no_warning_in_frame PASSED     [ 78%]
tests/test_stage8.py::test_char_split_only_at_min_size_with_warning PASSED [ 79%]
tests/test_stage8.py::test_truncate_whole_lines_with_ellipsis PASSED     [ 79%]
tests/test_stage8.py::test_no_partial_line_pixels PASSED                 [ 80%]
tests/test_stage8.py::test_no_line_fits_draws_nothing PASSED             [ 80%]
tests/test_text_fit.py::test_text_inside_frame[\u0413\u043e\u0441\u0442\u044c-350-70-st0] PASSED [ 80%]
tests/test_text_fit.py::test_text_inside_frame[\u0413\u043e\u0441\u0442\u044c-120-40-st1] PASSED [ 81%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2] PASSED [ 81%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434 \u0401\u0436\u0438\u043a \u0449\u0443\u043a\u0443-200-120-st3] PASSED [ 82%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-400-100-st4] PASSED [ 82%]
tests/test_text_fit.py::test_text_inside_frame[\u0412\u0435\u0434\u0443\u0449\u0438\u0439 \u0438\u043d\u0436\u0435\u043d\u0435\u0440-\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0442\u043e\u0440 \u043e\u0442\u0434\u0435\u043b\u0430 \u043f\u0435\u0440\u0441\u043f\u0435\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043e\u043a-420-160-st5] PASSED [ 83%]
tests/test_text_fit.py::test_text_inside_frame[\u0401\u043b\u043a\u0430\n\u0419\u043e\u0434\n\u0449\u0443\u043a\u0430\n\u0414\u0443\u0431-260-220-st6] PASSED [ 83%]
tests/test_text_fit.py::test_text_inside_frame[\u0419-60-60-st7] PASSED  [ 84%]
tests/test_text_fit.py::test_short_text_keeps_size PASSED                [ 84%]
tests/test_text_fit.py::test_very_long_word_clipped_with_warning PASSED  [ 85%]
tests/test_text_fit.py::test_min_size_respected PASSED                   [ 85%]
tests/test_text_fit.py::test_frame_at_canvas_edge PASSED                 [ 86%]
tests/test_text_fit.py::test_demo_layout_no_overlaps[front] PASSED       [ 86%]
tests/test_text_fit.py::test_demo_layout_no_overlaps[back] PASSED        [ 87%]
tests/test_text_fit.py::test_demo_texts_fit_without_clipping PASSED      [ 87%]
data_tools/tests/test_clean_photos.py::test_clean_copies_and_reports PASSED [ 88%]
data_tools/tests/test_clean_photos.py::test_dry_run_writes_nothing PASSED [ 88%]
data_tools/tests/test_clean_photos.py::test_start_digits_and_report_dir PASSED [ 89%]
data_tools/tests/test_clean_photos.py::test_refuses_same_or_nested_out PASSED [ 89%]
data_tools/tests/test_clean_photos.py::test_refuses_nonempty_out PASSED  [ 90%]
data_tools/tests/test_clean_photos.py::test_natural_sort PASSED          [ 90%]
data_tools/tests/test_testsets.py::test_photos_big_enough_and_varied PASSED [ 91%]
data_tools/tests/test_testsets.py::test_corner_markers_distinct PASSED   [ 91%]
data_tools/tests/test_testsets.py::test_large_reuses_few_bases PASSED    [ 92%]
data_tools/tests/test_testsets.py::test_bad_sets_still_bad PASSED        [ 92%]
data_tools/tests/test_testsets.py::test_fixtures_mode_size_no_metadata PASSED [ 93%]
data_tools/tests/test_testsets.py::test_markers_match_pixels PASSED      [ 93%]
data_tools/tests/test_testsets.py::test_regeneration_byte_identical PASSED [ 94%]
data_tools/tests/test_testsets.py::test_pattern_asymmetric PASSED        [ 94%]
data_tools/tests/test_validate_import.py::test_validate_records_pure_ok PASSED [ 95%]
data_tools/tests/test_validate_import.py::test_validate_records_errors_and_rows PASSED [ 95%]
data_tools/tests/test_validate_import.py::test_check_columns PASSED      [ 96%]
data_tools/tests/test_validate_import.py::test_photo_config_format PASSED [ 96%]
data_tools/tests/test_validate_import.py::test_clean_set_cli PASSED      [ 97%]
data_tools/tests/test_validate_import.py::test_photo_errors PASSED       [ 97%]
data_tools/tests/test_validate_import.py::test_duplicates PASSED         [ 98%]
data_tools/tests/test_validate_import.py::test_missing_fields_cli PASSED [ 98%]
data_tools/tests/test_validate_import.py::test_large PASSED              [ 99%]
data_tools/tests/test_validate_import.py::test_cli_missing_column PASSED [ 99%]
data_tools/tests/test_validate_import.py::test_no_mapping_or_excel_in_module PASSED [100%]

============================= 205 passed in 5.20s ==============================
```
