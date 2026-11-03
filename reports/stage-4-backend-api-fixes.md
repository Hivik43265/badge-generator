# Этап 4 — Backend: исправления API по замечаниям Frontend (обратно совместимо)

Источник: `reports/stage-4-frontend.md`. Изменено только `badge_backend/`, `tests/`, `README.md`. В `ui/`, `data_tools/` и `.venv` ничего не менялось.

| # | Решение | Тесты |
|---|---|---|
| 1 | `badge_backend.db.DEFAULT_DB_PATH = "project.db"` (реэкспорт в `api`) и `db.default_db_path(project_dir=None) -> Path` (`<project_dir or cwd>/project.db`). Описано в README. `connect()` по умолчанию по-прежнему открывает `:memory:`. | `test_default_db_path` |
| 2 | В `mapping` добавлен формат `{"Заголовок": "field" \| None \| ""}`: None или `""` исключает колонку. Старый формат `{field: [синонимы]}` работает, форматы можно смешивать (`headers.split_mapping`). Действует в `map_headers`, `parse_file` и `import_file`. | `test_mapping_exclude_column` |
| 3 | `headers.column_labels`: при ручном назначении на каноническое поле label канонический (Комментарий→department даёт «Отдел»), для нового поля берётся заголовок. Новый параметр `labels={key: label}` в `parse_file` и `import_file` перезаписывает label (ON CONFLICT DO UPDATE). Автоматический маппинг не изменился. | `test_manual_canonical_label_and_labels_param` |
| 4 | Утверждено Архитектором. `import_file(..., require_photo=False)`: по умолчанию `PHOTO_MISSING` от data_tools переносится в `report.warnings`, запись импортируется с `photo_path=NULL` и photo_config по умолчанию, рендер рисует плейсхолдер. `True` включает строгий режим: строка пропускается с ошибкой (проверяется и без `photo_dir`). Фолбэк без data_tools тоже выдаёт PHOTO_MISSING. data_tools не изменён. | `test_import_photo_missing_default_is_warning`, `test_import_require_photo_strict`, `test_import_fallback_photo_missing` |
| 4+ | Фото при экспорте и печати: `missing_photos(con, ids=None, base_dir=None) -> [id]` для предпроверки (нет пути, нет файла, пустой или битый файл). Параметр `allow_missing_photo=False` в `export_png`, `export_pdf`, `print_cards`, `*_from_snapshot` и `print_snapshot`. При False выбрасывается `MissingPhotosError(.ids)` **до** записи файлов и печати. При True в результате есть `.missing_photo_ids`. Результаты остаются совместимыми: `ExportResult(list)`, `PdfResult(Path)`, `PrintResult(int)`. | `test_missing_photos_precheck`, `test_export_missing_photo_strict_and_allowed`, `test_print_missing_photo_strict_nothing_printed`, `test_print_missing_photo_allowed_reports_ids` |
| 5 | `progress=callable(done, total)` добавлен в `import_file`, `export_png`, `export_pdf`, `print_cards` и snapshot-версии. `False` означает отмену. Импорт откатывает транзакцию (`cancelled=True`, added=0). PNG оставляет уже сохранённые файлы (`.cancelled=True`). PDF не создаёт файл и возвращает `None`. Печать вызывает `printer.abort()` (`.cancelled=True`). | `test_import_progress_and_cancel`, `test_export_progress_and_cancel`, `test_print_progress_cancel_and_snapshot` |
| 6 | qr/barcode не менялись: в v1 они пропускаются с warning. | `test_qr_barcode_skipped_with_warning` |
| 7 | Формат person зафиксирован: dict или `sqlite3.Row` с `fields_json` (str или dict), `photo_path`, `photo_config`, а также краткая форма `{"fields": {...}}`. Если заданы оба, приоритет у `fields_json`. Описано в README и docstring `render_card`. | `test_person_formats[json_str,json_dict,fields,row]`, `test_render_preview_with_draft_dict` |
| 8 | `snapshot(con, ids=None, sides) -> [{"person","side","elements","background"}]` собирается в GUI-потоке. `export_png_from_snapshot`, `export_pdf_from_snapshot` и `print_snapshot` работают без соединения, поэтому подходит и `:memory:`. Старые функции стали обёртками, их сигнатуры не изменились (добавлены только keyword-параметры с умолчаниями). | `test_snapshot_export_in_thread_memory_db` (рабочий поток, `:memory:`) |

**Изменение поведения:** по умолчанию `allow_missing_photo=False`. Код, который раньше молча печатал плейсхолдеры, теперь получит `MissingPhotosError`. Это требование Архитектора («плейсхолдер не уходит в печать молча»). UI должен вызвать `missing_photos()`, показать предупреждение и передать `allow_missing_photo=True`, если пользователь подтвердил.

Что поменять во Frontend (`ui/` я не правил):
- фоновый экспорт: в GUI-потоке вызывать `api.snapshot(...)`, в QThread — `export_*_from_snapshot` (своё соединение больше не нужно);
- перед экспортом и печатью вызывать `api.missing_photos()` и показывать диалог, затем передавать `allow_missing_photo`;
- прогресс-бар подключить к `progress=`, кнопку «Отмена» — к возврату `False`;
- в ImportDialog для исключения колонки использовать `{"Заголовок": None}`, для назначения — `{"Заголовок": "field"}`, показывать `report.warnings`.

## pytest -v (tests + data_tools/tests, QT_QPA_PLATFORM=offscreen)
```
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- /workspace/badge_generator/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /workspace/badge_generator
configfile: pytest.ini
collecting ... collected 137 items

tests/test_api.py::test_person_crud PASSED                               [  0%]
tests/test_api.py::test_update_photo_config PASSED                       [  1%]
tests/test_api.py::test_elements_crud PASSED                             [  2%]
tests/test_api.py::test_background_and_fields PASSED                     [  2%]
tests/test_api_fixes.py::test_default_db_path PASSED                     [  3%]
tests/test_api_fixes.py::test_mapping_exclude_column PASSED              [  4%]
tests/test_api_fixes.py::test_manual_canonical_label_and_labels_param PASSED [  5%]
tests/test_api_fixes.py::test_import_photo_missing_default_is_warning PASSED [  5%]
tests/test_api_fixes.py::test_import_require_photo_strict PASSED         [  6%]
tests/test_api_fixes.py::test_import_fallback_photo_missing PASSED       [  7%]
tests/test_api_fixes.py::test_import_progress_and_cancel PASSED          [  8%]
tests/test_api_fixes.py::test_export_progress_and_cancel PASSED          [  8%]
tests/test_api_fixes.py::test_person_formats[json_str] PASSED            [  9%]
tests/test_api_fixes.py::test_person_formats[json_dict] PASSED           [ 10%]
tests/test_api_fixes.py::test_person_formats[fields] PASSED              [ 10%]
tests/test_api_fixes.py::test_person_formats[row] PASSED                 [ 11%]
tests/test_api_fixes.py::test_render_preview_with_draft_dict PASSED      [ 12%]
tests/test_api_fixes.py::test_snapshot_export_in_thread_memory_db PASSED [ 13%]
tests/test_api_fixes.py::test_missing_photos_precheck PASSED             [ 13%]
tests/test_api_fixes.py::test_export_missing_photo_strict_and_allowed PASSED [ 14%]
tests/test_import_export.py::test_map_headers_synonyms PASSED            [ 15%]
tests/test_import_export.py::test_messy_headers_xlsx PASSED              [ 16%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-sig-;] PASSED [ 16%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-;] PASSED  [ 17%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-,] PASSED   [ 18%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-\t] PASSED [ 18%]
tests/test_import_export.py::test_xlsx_photo_and_errors PASSED           [ 19%]
tests/test_import_export.py::test_unsupported_format PASSED              [ 20%]
tests/test_import_export.py::test_default_photo_config_on_import PASSED  [ 21%]
tests/test_import_export.py::test_export_png PASSED                      [ 21%]
tests/test_import_export.py::test_export_pdf_pages_cr80 PASSED           [ 22%]
tests/test_import_export.py::test_export_errors_and_mark PASSED          [ 23%]
tests/test_no_data_tools.py::test_no_module_level_data_tools_import PASSED [ 24%]
tests/test_no_data_tools.py::test_import_core_does_not_load_data_tools PASSED [ 24%]
tests/test_no_data_tools.py::test_fallback_when_data_tools_blocked PASSED [ 25%]
tests/test_no_data_tools.py::test_fallback_subprocess_clean_sys_path PASSED [ 26%]
tests/test_print.py::test_print_only_marked_each_side_own_page PASSED    [ 27%]
tests/test_print.py::test_print_front_only_and_ids_filter PASSED         [ 27%]
tests/test_print.py::test_print_nothing_marked PASSED                    [ 28%]
tests/test_print.py::test_print_missing_photo_strict_nothing_printed PASSED [ 29%]
tests/test_print.py::test_print_missing_photo_allowed_reports_ids PASSED [ 29%]
tests/test_print.py::test_print_progress_cancel_and_snapshot PASSED      [ 30%]
tests/test_render.py::test_size_and_mode_both_sides PASSED               [ 31%]
tests/test_render.py::test_empty_template_and_no_person PASSED           [ 32%]
tests/test_render.py::test_bad_side PASSED                               [ 32%]
tests/test_render.py::test_z_order_and_side_filter PASSED                [ 33%]
tests/test_render.py::test_background_color_and_image PASSED             [ 34%]
tests/test_render.py::test_field_and_cyrillic_font PASSED                [ 35%]
tests/test_render.py::test_align[left-l] PASSED                          [ 35%]
tests/test_render.py::test_align[right-r] PASSED                         [ 36%]
tests/test_render.py::test_text_autoshrink_stays_in_box PASSED           [ 37%]
tests/test_render.py::test_rect_border_radius PASSED                     [ 37%]
tests/test_render.py::test_photo_default_cover_fills_frame PASSED        [ 38%]
tests/test_render.py::test_photo_crop_xy_px PASSED                       [ 39%]
tests/test_render.py::test_photo_scale_zoom_center PASSED                [ 40%]
tests/test_render.py::test_photo_shift_xy PASSED                         [ 40%]
tests/test_render.py::test_photo_rotation_clockwise PASSED               [ 41%]
tests/test_render.py::test_photo_invalid_config_warns_and_defaults PASSED [ 42%]
tests/test_render.py::test_photo_in_card_and_missing_placeholder PASSED  [ 43%]
tests/test_render.py::test_qr_barcode_skipped_with_warning PASSED        [ 43%]
tests/test_render.py::test_preview PASSED                                [ 44%]
tests/test_render.py::test_golden[front_full] PASSED                     [ 45%]
tests/test_render.py::test_golden[front_no_photo] PASSED                 [ 45%]
tests/test_render.py::test_golden[back] PASSED                           [ 46%]
tests/test_schema.py::test_card_px PASSED                                [ 47%]
tests/test_schema.py::test_migration_from_scratch PASSED                 [ 48%]
tests/test_schema.py::test_defaults PASSED                               [ 48%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('field',0,0,1,1)] PASSED [ 49%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,side) VALUES ('text',0,0,1,1,'top')] PASSED [ 50%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('circle',0,0,1,1)] PASSED [ 51%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('rect',0,0,0,1)] PASSED [ 51%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,style_json) VALUES ('rect',0,0,1,1,'{bad')] PASSED [ 52%]
tests/test_schema.py::test_checks[INSERT INTO persons(print_mark) VALUES (2)] PASSED [ 53%]
tests/test_schema.py::test_checks[INSERT INTO persons(fields_json) VALUES ('not json')] PASSED [ 54%]
tests/test_schema.py::test_types_ok[qr] PASSED                           [ 54%]
tests/test_schema.py::test_types_ok[barcode] PASSED                      [ 55%]
tests/test_schema.py::test_types_ok[photo] PASSED                        [ 56%]
tests/test_schema.py::test_types_ok[image] PASSED                        [ 56%]
tests/test_schema.py::test_types_ok[text] PASSED                         [ 57%]
tests/test_schema.py::test_types_ok[rect] PASSED                         [ 58%]
tests/test_schema.py::test_roundtrip[0;0;1.0;0;0;0-exp0] PASSED          [ 59%]
tests/test_schema.py::test_roundtrip[10;-5;1.25;120;40;15.5-exp1] PASSED [ 59%]
tests/test_schema.py::test_roundtrip[3;4;2,5;0;0;-90-exp2] PASSED        [ 60%]
tests/test_schema.py::test_bad_gives_default_and_warning[1;2;3] PASSED   [ 61%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;0;0;0;0] PASSED [ 62%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;-1;0;0;0] PASSED [ 62%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0.5;0;0] PASSED [ 63%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0;1.5;0] PASSED [ 64%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;-3;0;0] PASSED [ 64%]
tests/test_schema.py::test_bad_gives_default_and_warning[a;0;1;0;0;0] PASSED [ 65%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;nan;0;0;0] PASSED [ 66%]
tests/test_schema.py::test_bad_gives_default_and_warning[1.5;0;1;0;0;0] PASSED [ 67%]
tests/test_schema.py::test_empty_is_default_silently PASSED              [ 67%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-sig-;] PASSED          [ 68%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-sig-,] PASSED          [ 69%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-;] PASSED              [ 70%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-,] PASSED              [ 70%]
tests/test_stage5.py::test_csv_600_lossless[cp1251-;] PASSED             [ 71%]
tests/test_stage5.py::test_csv_600_lossless[cp1251-,] PASSED             [ 72%]
tests/test_stage5.py::test_xlsx_600_lossless PASSED                      [ 72%]
tests/test_stage5.py::test_import_single_transaction PASSED              [ 73%]
tests/test_stage5.py::test_header_only_quotes_sniff PASSED               [ 74%]
tests/test_stage5.py::test_export_pdf_60_cards PASSED                    [ 75%]
tests/test_stage5.py::test_zz_write_timings PASSED                       [ 75%]
tests/test_stage5.py::test_cells_preserved_extra_fields PASSED           [ 76%]
tests/test_text_fit.py::test_text_inside_frame[\u0413\u043e\u0441\u0442\u044c-350-70-st0] PASSED [ 77%]
tests/test_text_fit.py::test_text_inside_frame[\u0413\u043e\u0441\u0442\u044c-120-40-st1] PASSED [ 78%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2] PASSED [ 78%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434 \u0401\u0436\u0438\u043a \u0449\u0443\u043a\u0443-200-120-st3] PASSED [ 79%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-400-100-st4] PASSED [ 80%]
tests/test_text_fit.py::test_text_inside_frame[\u0412\u0435\u0434\u0443\u0449\u0438\u0439 \u0438\u043d\u0436\u0435\u043d\u0435\u0440-\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0442\u043e\u0440 \u043e\u0442\u0434\u0435\u043b\u0430 \u043f\u0435\u0440\u0441\u043f\u0435\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043e\u043a-420-160-st5] PASSED [ 81%]
tests/test_text_fit.py::test_text_inside_frame[\u0401\u043b\u043a\u0430\n\u0419\u043e\u0434\n\u0449\u0443\u043a\u0430\n\u0414\u0443\u0431-260-220-st6] PASSED [ 81%]
tests/test_text_fit.py::test_text_inside_frame[\u0419-60-60-st7] PASSED  [ 82%]
tests/test_text_fit.py::test_short_text_keeps_size PASSED                [ 83%]
tests/test_text_fit.py::test_very_long_word_clipped_with_warning PASSED  [ 83%]
tests/test_text_fit.py::test_min_size_respected PASSED                   [ 84%]
tests/test_text_fit.py::test_frame_at_canvas_edge PASSED                 [ 85%]
tests/test_text_fit.py::test_demo_layout_no_overlaps[front] PASSED       [ 86%]
tests/test_text_fit.py::test_demo_layout_no_overlaps[back] PASSED        [ 86%]
tests/test_text_fit.py::test_demo_texts_fit_without_clipping PASSED      [ 87%]
data_tools/tests/test_clean_photos.py::test_clean_copies_and_reports PASSED [ 88%]
data_tools/tests/test_clean_photos.py::test_dry_run_writes_nothing PASSED [ 89%]
data_tools/tests/test_clean_photos.py::test_start_digits_and_report_dir PASSED [ 89%]
data_tools/tests/test_clean_photos.py::test_refuses_same_or_nested_out PASSED [ 90%]
data_tools/tests/test_clean_photos.py::test_refuses_nonempty_out PASSED  [ 91%]
data_tools/tests/test_clean_photos.py::test_natural_sort PASSED          [ 91%]
data_tools/tests/test_validate_import.py::test_validate_records_pure_ok PASSED [ 92%]
data_tools/tests/test_validate_import.py::test_validate_records_errors_and_rows PASSED [ 93%]
data_tools/tests/test_validate_import.py::test_check_columns PASSED      [ 94%]
data_tools/tests/test_validate_import.py::test_photo_config_format PASSED [ 94%]
data_tools/tests/test_validate_import.py::test_clean_set_cli PASSED      [ 95%]
data_tools/tests/test_validate_import.py::test_photo_errors PASSED       [ 96%]
data_tools/tests/test_validate_import.py::test_duplicates PASSED         [ 97%]
data_tools/tests/test_validate_import.py::test_missing_fields_cli PASSED [ 97%]
data_tools/tests/test_validate_import.py::test_large PASSED              [ 98%]
data_tools/tests/test_validate_import.py::test_cli_missing_column PASSED [ 99%]
data_tools/tests/test_validate_import.py::test_no_mapping_or_excel_in_module PASSED [100%]

============================= 137 passed in 3.96s ==============================
```
