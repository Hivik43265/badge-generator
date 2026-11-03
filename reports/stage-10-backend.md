# Этап 10 — Backend

## Сделано
1. **Пустой шаблон.** Новая БД без template_elements; seed-макет `demo.build_demo` вынесен в данные `tests/fixtures/demo_layout.json` (код — только загрузчик `demo.apply_layout`). Экспорт PNG/PDF и печать пустого шаблона: `.empty_template=True`, `.warnings=[...]`, RuntimeWarning + log.warning, без исключения. Частично пустая сторона — `.warnings=["сторона 'back' шаблона пуста"]`, `empty_template=False`.
2. **barcode** (`render/barcode.py`): python-barcode (модули) + своя растеризация. Code128/EAN-13, целое число px на модуль (максимум), центрирование, show_text, quiet_zone; невалидное → пустая рамка + warning.
3. **qr** (`render/qr.py`): qrcode[pil], L/M/Q/H, border, квадрат в min(w,h), целые модули, центр; пусто/переполнение/не влезает → пустая рамка + warning.
4. **line** + миграция **v3** (`db._v3_line`): пересборка template_elements в одной транзакции, id/данные/индекс сохранены, идемпотентно. CHECK: не-line — `w>0 AND h>0`; line — любые w,h, кроме (0,0).
5. **rect**: `stroke, stroke_width, fill, radius` (border_* — синонимы).
6. Фон — только template_backgrounds.
7. Golden: `tests/golden/barcode_{code128,ean13,invalid}.png`, `qr_{m,h_border2}.png`, `line_mixed.png` (генерация в `tests/make_golden.py`, кейсы в `tests/tests_golden_cases.py`).
8. Декодер: **zxing-cpp** только в `requirements-dev.txt`; тесты декодирования (Code128, EAN-13, QR L/M/Q/H) — skipif без него. В .venv установлен, тесты выполнены.
9. Обновлены тесты под LATEST=3 (test_schema, test_schema_version, test_d5_printed_at, test_testing_helpers); `test_qr_barcode_skipped_with_warning` заменён на `test_qr_barcode_now_rendered`.

## Совместимость
- `user_version` 3; старые БД мигрируют при `connect`.
- qr/barcode больше не пропускаются — рисуются.
- `ui/smoke_test.py` (не тронут) проходит: ALL OK. UI пишет `style['symbology']`; бэкенд принимает его как синоним `format` (приоритет у `format`).

## pytest -v
```
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- /workspace/badge_generator/.venv/bin/python
cachedir: .pytest_cache
rootdir: /workspace/badge_generator
configfile: pytest.ini
collecting ... collected 254 items

tests/test_api.py::test_person_crud PASSED                               [  0%]
tests/test_api.py::test_update_photo_config PASSED                       [  0%]
tests/test_api.py::test_elements_crud PASSED                             [  1%]
tests/test_api.py::test_background_and_fields PASSED                     [  1%]
tests/test_api_fixes.py::test_default_db_path PASSED                     [  1%]
tests/test_api_fixes.py::test_mapping_exclude_column PASSED              [  2%]
tests/test_api_fixes.py::test_manual_canonical_label_and_labels_param PASSED [  2%]
tests/test_api_fixes.py::test_import_photo_missing_default_is_warning PASSED [  3%]
tests/test_api_fixes.py::test_import_require_photo_strict PASSED         [  3%]
tests/test_api_fixes.py::test_import_fallback_photo_missing PASSED       [  3%]
tests/test_api_fixes.py::test_import_progress_and_cancel PASSED          [  4%]
tests/test_api_fixes.py::test_export_progress_and_cancel PASSED          [  4%]
tests/test_api_fixes.py::test_person_formats[json_str] PASSED            [  5%]
tests/test_api_fixes.py::test_person_formats[json_dict] PASSED           [  5%]
tests/test_api_fixes.py::test_person_formats[fields] PASSED              [  5%]
tests/test_api_fixes.py::test_person_formats[row] PASSED                 [  6%]
tests/test_api_fixes.py::test_render_preview_with_draft_dict PASSED      [  6%]
tests/test_api_fixes.py::test_snapshot_export_in_thread_memory_db PASSED [  7%]
tests/test_api_fixes.py::test_missing_photos_precheck PASSED             [  7%]
tests/test_api_fixes.py::test_export_missing_photo_strict_and_allowed PASSED [  7%]
tests/test_d5_printed_at.py::test_migrate_old_v1_db PASSED               [  8%]
tests/test_d5_printed_at.py::test_migrate_repeat_idempotent PASSED       [  8%]
tests/test_d5_printed_at.py::test_new_db_has_printed_at PASSED           [  9%]
tests/test_d5_printed_at.py::test_mark_printed_sets_time_and_clears_mark PASSED [  9%]
tests/test_d5_printed_at.py::test_set_print_mark_keeps_printed_at PASSED [  9%]
tests/test_d5_printed_at.py::test_mark_printed_has_no_value_param[args0] PASSED [ 10%]
tests/test_d5_printed_at.py::test_mark_printed_has_no_value_param[args1] PASSED [ 10%]
tests/test_d5_printed_at.py::test_mark_printed_has_no_value_param[args2] PASSED [ 11%]
tests/test_d5_printed_at.py::test_mark_printed_no_value_no_warning PASSED [ 11%]
tests/test_d5_printed_at.py::test_mark_printed_rollback PASSED           [ 11%]
tests/test_empty_template.py::test_new_project_has_empty_template PASSED [ 12%]
tests/test_empty_template.py::test_render_empty_template_with_and_without_person PASSED [ 12%]
tests/test_empty_template.py::test_element_crud_and_render PASSED        [ 12%]
tests/test_import_export.py::test_map_headers_synonyms PASSED            [ 13%]
tests/test_import_export.py::test_messy_headers_xlsx PASSED              [ 13%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-sig-;] PASSED [ 14%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-;] PASSED  [ 14%]
tests/test_import_export.py::test_csv_encodings_delims[utf-8-,] PASSED   [ 14%]
tests/test_import_export.py::test_csv_encodings_delims[cp1251-\t] PASSED [ 15%]
tests/test_import_export.py::test_xlsx_photo_and_errors PASSED           [ 15%]
tests/test_import_export.py::test_unsupported_format PASSED              [ 16%]
tests/test_import_export.py::test_default_photo_config_on_import PASSED  [ 16%]
tests/test_import_export.py::test_export_png PASSED                      [ 16%]
tests/test_import_export.py::test_export_pdf_pages_cr80 PASSED           [ 17%]
tests/test_import_export.py::test_export_errors_and_mark PASSED          [ 17%]
tests/test_no_data_tools.py::test_no_module_level_data_tools_import PASSED [ 18%]
tests/test_no_data_tools.py::test_import_core_does_not_load_data_tools PASSED [ 18%]
tests/test_no_data_tools.py::test_fallback_when_data_tools_blocked PASSED [ 18%]
tests/test_no_data_tools.py::test_fallback_subprocess_clean_sys_path PASSED [ 19%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;0-portrait_300x400.png] PASSED [ 19%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;0-portrait_600x800.png] PASSED [ 20%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;0-landscape_400x300.png] PASSED [ 20%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.5;0;0;0-portrait_300x400.png] PASSED [ 20%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.5;0;0;0-portrait_600x800.png] PASSED [ 21%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.5;0;0;0-landscape_400x300.png] PASSED [ 21%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;0.8;0;0;0-portrait_300x400.png] PASSED [ 22%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;0.8;0;0;0-portrait_600x800.png] PASSED [ 22%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;0.8;0;0;0-landscape_400x300.png] PASSED [ 22%]
tests/test_photo_transform.py::test_markers_land_where_expected[20;-15;1.0;0;0;0-portrait_300x400.png] PASSED [ 23%]
tests/test_photo_transform.py::test_markers_land_where_expected[20;-15;1.0;0;0;0-portrait_600x800.png] PASSED [ 23%]
tests/test_photo_transform.py::test_markers_land_where_expected[20;-15;1.0;0;0;0-landscape_400x300.png] PASSED [ 24%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;40;30;0-portrait_300x400.png] PASSED [ 24%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;40;30;0-portrait_600x800.png] PASSED [ 24%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;40;30;0-landscape_400x300.png] PASSED [ 25%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;90-portrait_300x400.png] PASSED [ 25%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;90-portrait_600x800.png] PASSED [ 25%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;90-landscape_400x300.png] PASSED [ 26%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;-90-portrait_300x400.png] PASSED [ 26%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;-90-portrait_600x800.png] PASSED [ 27%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;-90-landscape_400x300.png] PASSED [ 27%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;30-portrait_300x400.png] PASSED [ 27%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;30-portrait_600x800.png] PASSED [ 28%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;30-landscape_400x300.png] PASSED [ 28%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;180-portrait_300x400.png] PASSED [ 29%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;180-portrait_600x800.png] PASSED [ 29%]
tests/test_photo_transform.py::test_markers_land_where_expected[0;0;1.0;0;0;180-landscape_400x300.png] PASSED [ 29%]
tests/test_photo_transform.py::test_markers_land_where_expected[15;10;1.3;20;40;15-portrait_300x400.png] PASSED [ 30%]
tests/test_photo_transform.py::test_markers_land_where_expected[15;10;1.3;20;40;15-portrait_600x800.png] PASSED [ 30%]
tests/test_photo_transform.py::test_markers_land_where_expected[15;10;1.3;20;40;15-landscape_400x300.png] PASSED [ 31%]
tests/test_photo_transform.py::test_rotation_is_clockwise_arrow_up[portrait_300x400.png] PASSED [ 31%]
tests/test_photo_transform.py::test_rotation_is_clockwise_arrow_up[portrait_600x800.png] PASSED [ 31%]
tests/test_photo_transform.py::test_rotation_is_clockwise_arrow_up[landscape_400x300.png] PASSED [ 32%]
tests/test_photo_transform.py::test_photo_golden[portrait_300x400.png-0;0;1.0;0;0;0] PASSED [ 32%]
tests/test_photo_transform.py::test_photo_golden[portrait_600x800.png-15;10;1.3;20;40;15] PASSED [ 33%]
tests/test_photo_transform.py::test_photo_golden[landscape_400x300.png-0;0;1.0;0;0;90] PASSED [ 33%]
tests/test_photo_transform.py::test_photo_golden[landscape_400x300.png--20;0;1.2;60;0;-30] PASSED [ 33%]
tests/test_print.py::test_print_only_marked_each_side_own_page PASSED    [ 34%]
tests/test_print.py::test_print_front_only_and_ids_filter PASSED         [ 34%]
tests/test_print.py::test_print_nothing_marked PASSED                    [ 35%]
tests/test_print.py::test_print_missing_photo_strict_nothing_printed PASSED [ 35%]
tests/test_print.py::test_print_missing_photo_allowed_reports_ids PASSED [ 35%]
tests/test_print.py::test_print_progress_cancel_and_snapshot PASSED      [ 36%]
tests/test_render.py::test_size_and_mode_both_sides PASSED               [ 36%]
tests/test_render.py::test_empty_template_and_no_person PASSED           [ 37%]
tests/test_render.py::test_bad_side PASSED                               [ 37%]
tests/test_render.py::test_z_order_and_side_filter PASSED                [ 37%]
tests/test_render.py::test_background_color_and_image PASSED             [ 38%]
tests/test_render.py::test_field_and_cyrillic_font PASSED                [ 38%]
tests/test_render.py::test_align[left-l] PASSED                          [ 38%]
tests/test_render.py::test_align[right-r] PASSED                         [ 39%]
tests/test_render.py::test_text_autoshrink_stays_in_box PASSED           [ 39%]
tests/test_render.py::test_rect_border_radius PASSED                     [ 40%]
tests/test_render.py::test_photo_default_cover_fills_frame PASSED        [ 40%]
tests/test_render.py::test_photo_crop_xy_px PASSED                       [ 40%]
tests/test_render.py::test_photo_scale_zoom_center PASSED                [ 41%]
tests/test_render.py::test_photo_shift_xy PASSED                         [ 41%]
tests/test_render.py::test_photo_rotation_clockwise PASSED               [ 42%]
tests/test_render.py::test_photo_invalid_config_warns_and_defaults PASSED [ 42%]
tests/test_render.py::test_photo_in_card_and_missing_placeholder PASSED  [ 42%]
tests/test_render.py::test_qr_barcode_now_rendered PASSED                [ 43%]
tests/test_render.py::test_preview PASSED                                [ 43%]
tests/test_render.py::test_golden[front_full] PASSED                     [ 44%]
tests/test_render.py::test_golden[front_no_photo] PASSED                 [ 44%]
tests/test_render.py::test_golden[back] PASSED                           [ 44%]
tests/test_schema.py::test_card_px PASSED                                [ 45%]
tests/test_schema.py::test_migration_from_scratch PASSED                 [ 45%]
tests/test_schema.py::test_defaults PASSED                               [ 46%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('field',0,0,1,1)] PASSED [ 46%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,side) VALUES ('text',0,0,1,1,'top')] PASSED [ 46%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('circle',0,0,1,1)] PASSED [ 47%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h) VALUES ('rect',0,0,0,1)] PASSED [ 47%]
tests/test_schema.py::test_checks[INSERT INTO template_elements(type,x,y,w,h,style_json) VALUES ('rect',0,0,1,1,'{bad')] PASSED [ 48%]
tests/test_schema.py::test_checks[INSERT INTO persons(print_mark) VALUES (2)] PASSED [ 48%]
tests/test_schema.py::test_checks[INSERT INTO persons(fields_json) VALUES ('not json')] PASSED [ 48%]
tests/test_schema.py::test_types_ok[qr] PASSED                           [ 49%]
tests/test_schema.py::test_types_ok[barcode] PASSED                      [ 49%]
tests/test_schema.py::test_types_ok[photo] PASSED                        [ 50%]
tests/test_schema.py::test_types_ok[image] PASSED                        [ 50%]
tests/test_schema.py::test_types_ok[text] PASSED                         [ 50%]
tests/test_schema.py::test_types_ok[rect] PASSED                         [ 51%]
tests/test_schema.py::test_roundtrip[0;0;1.0;0;0;0-exp0] PASSED          [ 51%]
tests/test_schema.py::test_roundtrip[10;-5;1.25;120;40;15.5-exp1] PASSED [ 51%]
tests/test_schema.py::test_roundtrip[3;4;2,5;0;0;-90-exp2] PASSED        [ 52%]
tests/test_schema.py::test_bad_gives_default_and_warning[1;2;3] PASSED   [ 52%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;0;0;0;0] PASSED [ 53%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;-1;0;0;0] PASSED [ 53%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0.5;0;0] PASSED [ 53%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;0;1.5;0] PASSED [ 54%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;1.0;-3;0;0] PASSED [ 54%]
tests/test_schema.py::test_bad_gives_default_and_warning[a;0;1;0;0;0] PASSED [ 55%]
tests/test_schema.py::test_bad_gives_default_and_warning[0;0;nan;0;0;0] PASSED [ 55%]
tests/test_schema.py::test_bad_gives_default_and_warning[1.5;0;1;0;0;0] PASSED [ 55%]
tests/test_schema.py::test_empty_is_default_silently PASSED              [ 56%]
tests/test_schema_version.py::test_get_schema_version_fresh_and_migrated PASSED [ 56%]
tests/test_schema_version.py::test_get_schema_version_connect PASSED     [ 57%]
tests/test_stage10.py::test_new_db_no_elements_no_seed PASSED            [ 57%]
tests/test_stage10.py::test_export_png_empty_template_warns PASSED       [ 57%]
tests/test_stage10.py::test_export_pdf_empty_template_warns PASSED       [ 58%]
tests/test_stage10.py::test_export_one_empty_side_partial_warning PASSED [ 58%]
tests/test_stage10.py::test_export_nonempty_no_warnings PASSED           [ 59%]
tests/test_stage10.py::test_print_empty_template_warns PASSED            [ 59%]
tests/test_stage10.py::test_ean13_validation PASSED                      [ 59%]
tests/test_stage10.py::test_ean13_invalid_empty_frame[] PASSED           [ 60%]
tests/test_stage10.py::test_ean13_invalid_empty_frame[None] PASSED       [ 60%]
tests/test_stage10.py::test_ean13_invalid_empty_frame[12345] PASSED      [ 61%]
tests/test_stage10.py::test_ean13_invalid_empty_frame[59012341234578] PASSED [ 61%]
tests/test_stage10.py::test_ean13_invalid_empty_frame[5901234123458] PASSED [ 61%]
tests/test_stage10.py::test_ean13_invalid_empty_frame[abcdefghijkl] PASSED [ 62%]
tests/test_stage10.py::test_code128_invalid_and_too_narrow PASSED        [ 62%]
tests/test_stage10.py::test_integer_module_width_and_centering[code128-EMP-000123-700] PASSED [ 62%]
tests/test_stage10.py::test_integer_module_width_and_centering[code128-A1-333] PASSED [ 63%]
tests/test_stage10.py::test_integer_module_width_and_centering[ean13-5901234123457-500] PASSED [ 63%]
tests/test_stage10.py::test_integer_module_width_and_centering[ean13-400638133393-211] PASSED [ 64%]
tests/test_stage10.py::test_show_text_reserves_area PASSED               [ 64%]
tests/test_stage10.py::test_barcode_value_from_field_and_static PASSED   [ 64%]
tests/test_stage10.py::test_barcode_decodes[code128-EMP-000123] PASSED   [ 65%]
tests/test_stage10.py::test_barcode_decodes[ean13-5901234123457] PASSED  [ 65%]
tests/test_stage10.py::test_qr_square_integer_modules_center PASSED      [ 66%]
tests/test_stage10.py::test_qr_ec_levels_and_invalid PASSED              [ 66%]
tests/test_stage10.py::test_qr_value_from_field_and_static PASSED        [ 66%]
tests/test_stage10.py::test_qr_decodes[L] PASSED                         [ 67%]
tests/test_stage10.py::test_qr_decodes[M] PASSED                         [ 67%]
tests/test_stage10.py::test_qr_decodes[Q] PASSED                         [ 68%]
tests/test_stage10.py::test_qr_decodes[H] PASSED                         [ 68%]
tests/test_stage10.py::test_line_negative_and_zero_extent PASSED         [ 68%]
tests/test_stage10.py::test_line_diagonal PASSED                         [ 69%]
tests/test_stage10.py::test_migration_v2_to_v3_with_data PASSED          [ 69%]
tests/test_stage10.py::test_legacy_v2_helper PASSED                      [ 70%]
tests/test_stage10.py::test_rect_all_four_keys PASSED                    [ 70%]
tests/test_stage10.py::test_rect_stroke_only_and_legacy_keys PASSED      [ 70%]
tests/test_stage10.py::test_stage10_golden[barcode_code128] PASSED       [ 71%]
tests/test_stage10.py::test_stage10_golden[barcode_ean13] PASSED         [ 71%]
tests/test_stage10.py::test_stage10_golden[barcode_invalid] PASSED       [ 72%]
tests/test_stage10.py::test_stage10_golden[line_mixed] PASSED            [ 72%]
tests/test_stage10.py::test_stage10_golden[qr_h_border2] PASSED          [ 72%]
tests/test_stage10.py::test_stage10_golden[qr_m] PASSED                  [ 73%]
tests/test_stage10.py::test_symbology_alias PASSED                       [ 73%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-sig-;] PASSED          [ 74%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-sig-,] PASSED          [ 74%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-;] PASSED              [ 74%]
tests/test_stage5.py::test_csv_600_lossless[utf-8-,] PASSED              [ 75%]
tests/test_stage5.py::test_csv_600_lossless[cp1251-;] PASSED             [ 75%]
tests/test_stage5.py::test_csv_600_lossless[cp1251-,] PASSED             [ 75%]
tests/test_stage5.py::test_xlsx_600_lossless PASSED                      [ 76%]
tests/test_stage5.py::test_import_single_transaction PASSED              [ 76%]
tests/test_stage5.py::test_header_only_quotes_sniff PASSED               [ 77%]
tests/test_stage5.py::test_export_pdf_60_cards PASSED                    [ 77%]
tests/test_stage5.py::test_zz_write_timings PASSED                       [ 77%]
tests/test_stage5.py::test_cells_preserved_extra_fields PASSED           [ 78%]
tests/test_stage8.py::test_page_tolerance_boundary PASSED                [ 78%]
tests/test_stage8.py::test_qprinter_pdf_page_within_tolerance PASSED     [ 79%]
tests/test_stage8.py::test_wrap_on_hyphen_keeps_hyphen PASSED            [ 79%]
tests/test_stage8.py::test_wrap_on_dashes_and_slash[\u041e\u041e\u041e/\u0420\u043e\u043c\u0430\u0448\u043a\u0430-\u041e\u041e\u041e/] PASSED [ 79%]
tests/test_stage8.py::test_wrap_on_dashes_and_slash[\u0410\u043b\u044c\u0444\u0430\u2014\u0411\u0435\u0442\u0430\u0433\u0430\u043c\u043c\u0430-\u0410\u043b\u044c\u0444\u0430\u2014] PASSED [ 80%]
tests/test_stage8.py::test_wrap_on_dashes_and_slash[\u0410\u043b\u044c\u0444\u0430\u2013\u0411\u0435\u0442\u0430\u0433\u0430\u043c\u043c\u0430-\u0410\u043b\u044c\u0444\u0430\u2013] PASSED [ 80%]
tests/test_stage8.py::test_spaces_before_hyphens PASSED                  [ 81%]
tests/test_stage8.py::test_order_shrink_before_char_split PASSED         [ 81%]
tests/test_stage8.py::test_double_surname_no_warning_in_frame PASSED     [ 81%]
tests/test_stage8.py::test_char_split_only_at_min_size_with_warning PASSED [ 82%]
tests/test_stage8.py::test_truncate_whole_lines_with_ellipsis PASSED     [ 82%]
tests/test_stage8.py::test_no_partial_line_pixels PASSED                 [ 83%]
tests/test_stage8.py::test_no_line_fits_draws_nothing PASSED             [ 83%]
tests/test_testing_helpers.py::test_legacy_v1_then_migrate PASSED        [ 83%]
tests/test_testing_helpers.py::test_legacy_errors PASSED                 [ 84%]
tests/test_text_fit.py::test_text_inside_frame[\u0413\u043e\u0441\u0442\u044c-350-70-st0] PASSED [ 84%]
tests/test_text_fit.py::test_text_inside_frame[\u0413\u043e\u0441\u0442\u044c-120-40-st1] PASSED [ 85%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2] PASSED [ 85%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434 \u0401\u0436\u0438\u043a \u0449\u0443\u043a\u0443-200-120-st3] PASSED [ 85%]
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-400-100-st4] PASSED [ 86%]
tests/test_text_fit.py::test_text_inside_frame[\u0412\u0435\u0434\u0443\u0449\u0438\u0439 \u0438\u043d\u0436\u0435\u043d\u0435\u0440-\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0442\u043e\u0440 \u043e\u0442\u0434\u0435\u043b\u0430 \u043f\u0435\u0440\u0441\u043f\u0435\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043e\u043a-420-160-st5] PASSED [ 86%]
tests/test_text_fit.py::test_text_inside_frame[\u0401\u043b\u043a\u0430\n\u0419\u043e\u0434\n\u0449\u0443\u043a\u0430\n\u0414\u0443\u0431-260-220-st6] PASSED [ 87%]
tests/test_text_fit.py::test_text_inside_frame[\u0419-60-60-st7] PASSED  [ 87%]
tests/test_text_fit.py::test_short_text_keeps_size PASSED                [ 87%]
tests/test_text_fit.py::test_very_long_word_clipped_with_warning PASSED  [ 88%]
tests/test_text_fit.py::test_min_size_respected PASSED                   [ 88%]
tests/test_text_fit.py::test_frame_at_canvas_edge PASSED                 [ 88%]
tests/test_text_fit.py::test_demo_layout_no_overlaps[front] PASSED       [ 89%]
tests/test_text_fit.py::test_demo_layout_no_overlaps[back] PASSED        [ 89%]
tests/test_text_fit.py::test_demo_texts_fit_without_clipping PASSED      [ 90%]
data_tools/tests/test_clean_photos.py::test_clean_copies_and_reports PASSED [ 90%]
data_tools/tests/test_clean_photos.py::test_dry_run_writes_nothing PASSED [ 90%]
data_tools/tests/test_clean_photos.py::test_start_digits_and_report_dir PASSED [ 91%]
data_tools/tests/test_clean_photos.py::test_refuses_same_or_nested_out PASSED [ 91%]
data_tools/tests/test_clean_photos.py::test_refuses_nonempty_out PASSED  [ 92%]
data_tools/tests/test_clean_photos.py::test_natural_sort PASSED          [ 92%]
data_tools/tests/test_testsets.py::test_photos_big_enough_and_varied PASSED [ 92%]
data_tools/tests/test_testsets.py::test_corner_markers_distinct PASSED   [ 93%]
data_tools/tests/test_testsets.py::test_large_reuses_few_bases PASSED    [ 93%]
data_tools/tests/test_testsets.py::test_bad_sets_still_bad PASSED        [ 94%]
data_tools/tests/test_testsets.py::test_fixtures_mode_size_no_metadata PASSED [ 94%]
data_tools/tests/test_testsets.py::test_markers_match_pixels PASSED      [ 94%]
data_tools/tests/test_testsets.py::test_regeneration_byte_identical PASSED [ 95%]
data_tools/tests/test_testsets.py::test_pattern_asymmetric PASSED        [ 95%]
data_tools/tests/test_validate_import.py::test_validate_records_pure_ok PASSED [ 96%]
data_tools/tests/test_validate_import.py::test_validate_records_errors_and_rows PASSED [ 96%]
data_tools/tests/test_validate_import.py::test_check_columns PASSED      [ 96%]
data_tools/tests/test_validate_import.py::test_photo_config_format PASSED [ 97%]
data_tools/tests/test_validate_import.py::test_clean_set_cli PASSED      [ 97%]
data_tools/tests/test_validate_import.py::test_photo_errors PASSED       [ 98%]
data_tools/tests/test_validate_import.py::test_duplicates PASSED         [ 98%]
data_tools/tests/test_validate_import.py::test_missing_fields_cli PASSED [ 98%]
data_tools/tests/test_validate_import.py::test_large PASSED              [ 99%]
data_tools/tests/test_validate_import.py::test_cli_missing_column PASSED [ 99%]
data_tools/tests/test_validate_import.py::test_no_mapping_or_excel_in_module PASSED [100%]

=============================== warnings summary ===============================
tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2]
  /workspace/badge_generator/.venv/lib/python3.13/site-packages/_pytest/unraisableexception.py:63: PytestUnraisableExceptionWarning: Exception ignored in: <sqlite3.Connection object at 0x7f35497484f0>
  
  Traceback (most recent call last):
    File "/workspace/badge_generator/.venv/lib/python3.13/site-packages/PIL/ImageFont.py", line 249, in __init__
      def __init__(
      
  ResourceWarning: unclosed database in <sqlite3.Connection object at 0x7f35497484f0>
  
  Enable tracemalloc to get traceback where the object was allocated.
  See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
    warnings.warn(pytest.PytestUnraisableExceptionWarning(msg))

tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2]
  /workspace/badge_generator/.venv/lib/python3.13/site-packages/_pytest/unraisableexception.py:63: PytestUnraisableExceptionWarning: Exception ignored in: <sqlite3.Connection object at 0x7f35496017b0>
  
  Traceback (most recent call last):
    File "/workspace/badge_generator/.venv/lib/python3.13/site-packages/PIL/ImageFont.py", line 249, in __init__
      def __init__(
      
  ResourceWarning: unclosed database in <sqlite3.Connection object at 0x7f35496017b0>
  
  Enable tracemalloc to get traceback where the object was allocated.
  See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
    warnings.warn(pytest.PytestUnraisableExceptionWarning(msg))

tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2]
  /workspace/badge_generator/.venv/lib/python3.13/site-packages/_pytest/unraisableexception.py:63: PytestUnraisableExceptionWarning: Exception ignored in: <sqlite3.Connection object at 0x7f35498f6e30>
  
  Traceback (most recent call last):
    File "/workspace/badge_generator/.venv/lib/python3.13/site-packages/PIL/ImageFont.py", line 249, in __init__
      def __init__(
      
  ResourceWarning: unclosed database in <sqlite3.Connection object at 0x7f35498f6e30>
  
  Enable tracemalloc to get traceback where the object was allocated.
  See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
    warnings.warn(pytest.PytestUnraisableExceptionWarning(msg))

tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2]
  /workspace/badge_generator/.venv/lib/python3.13/site-packages/_pytest/unraisableexception.py:63: PytestUnraisableExceptionWarning: Exception ignored in: <sqlite3.Connection object at 0x7f35498f71f0>
  
  Traceback (most recent call last):
    File "/workspace/badge_generator/.venv/lib/python3.13/site-packages/PIL/ImageFont.py", line 249, in __init__
      def __init__(
      
  ResourceWarning: unclosed database in <sqlite3.Connection object at 0x7f35498f71f0>
  
  Enable tracemalloc to get traceback where the object was allocated.
  See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
    warnings.warn(pytest.PytestUnraisableExceptionWarning(msg))

tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2]
  /workspace/badge_generator/.venv/lib/python3.13/site-packages/_pytest/unraisableexception.py:63: PytestUnraisableExceptionWarning: Exception ignored in: <sqlite3.Connection object at 0x7f35498f7970>
  
  Traceback (most recent call last):
    File "/workspace/badge_generator/.venv/lib/python3.13/site-packages/PIL/ImageFont.py", line 249, in __init__
      def __init__(
      
  ResourceWarning: unclosed database in <sqlite3.Connection object at 0x7f35498f7970>
  
  Enable tracemalloc to get traceback where the object was allocated.
  See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
    warnings.warn(pytest.PytestUnraisableExceptionWarning(msg))

tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2]
  /workspace/badge_generator/.venv/lib/python3.13/site-packages/_pytest/unraisableexception.py:63: PytestUnraisableExceptionWarning: Exception ignored in: <sqlite3.Connection object at 0x7f35498f7880>
  
  Traceback (most recent call last):
    File "/workspace/badge_generator/.venv/lib/python3.13/site-packages/PIL/ImageFont.py", line 249, in __init__
      def __init__(
      
  ResourceWarning: unclosed database in <sqlite3.Connection object at 0x7f35498f7880>
  
  Enable tracemalloc to get traceback where the object was allocated.
  See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
    warnings.warn(pytest.PytestUnraisableExceptionWarning(msg))

tests/test_text_fit.py::test_text_inside_frame[\u0419\u0443\u0440\u0434-300-80-st2]
  /workspace/badge_generator/.venv/lib/python3.13/site-packages/_pytest/unraisableexception.py:63: PytestUnraisableExceptionWarning: Exception ignored in: <sqlite3.Connection object at 0x7f35498f7f10>
  
  Traceback (most recent call last):
    File "/workspace/badge_generator/.venv/lib/python3.13/site-packages/PIL/ImageFont.py", line 249, in __init__
      def __init__(
      
  ResourceWarning: unclosed database in <sqlite3.Connection object at 0x7f35498f7f10>
  
  Enable tracemalloc to get traceback where the object was allocated.
  See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
    warnings.warn(pytest.PytestUnraisableExceptionWarning(msg))

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 254 passed, 7 warnings in 5.96s ========================
```
