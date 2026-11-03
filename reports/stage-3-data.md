# Этап 3 — данные (BG-Data)

## Скрипты (`/workspace/badge_generator/data_tools/`)
| Скрипт | Вход | Выход |
|---|---|---|
| `clean_photos.py <src> <out>` | папка с фото (не изменяется) | копии `0001.ext…` в `<out>`, `mapping.csv` (old,new), `rejected.csv` (file,reason: zero_byte/broken/unsupported) |
| `validate_import.py` (API) | `list[dict]` с каноническими полями persons | `validate_records(...) -> list[Error]`, `valid_records(...)`, `check_columns(...)` |
| `validate_import.py <file.csv>` (CLI) | CSV с каноническими заголовками, опц. `--photos` | `reports/report.csv` (row,field,code,details), `reports/valid.csv`, код выхода 1 при ошибках |
| `testdata/make_testsets.py [out]` | — | наборы в `testdata/sets/` |

Маппинг заголовков, разбор ФИО и чтение Excel удалены — это зона Backend.
Проверки: обязательные last_name/first_name (MISSING_COLUMN/REQUIRED_MISSING), дубли, email, телефон, photo_path (есть, не пуст, открывается Pillow), формат photo_config (`x;y;scale;crop_x;crop_y;angle`, по умолчанию `0;0;1.0;0;0;0`). Трансформаций изображений нет.

## Тестовые наборы
Канонические `persons.csv`: clean (5 записей + фото), zero_byte_and_broken (пустое, битое, txt, разные регистры расширений), duplicates, missing_fields (пустые поля, плохие email/телефон/photo_config), large (1000 записей).
`messy_headers/persons_raw.xlsx` — сырые данные для Backend, нашими тестами не используется.

## Вывод pytest
```
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- /usr/bin/python3
rootdir: /workspace/badge_generator
configfile: pytest.ini
collecting ... collected 17 items

tests/test_clean_photos.py::test_clean_copies_and_reports PASSED         [  5%]
tests/test_clean_photos.py::test_dry_run_writes_nothing PASSED           [ 11%]
tests/test_clean_photos.py::test_start_digits_and_report_dir PASSED      [ 17%]
tests/test_clean_photos.py::test_refuses_same_or_nested_out PASSED       [ 23%]
tests/test_clean_photos.py::test_refuses_nonempty_out PASSED             [ 29%]
tests/test_clean_photos.py::test_natural_sort PASSED                     [ 35%]
tests/test_validate_import.py::test_validate_records_pure_ok PASSED      [ 41%]
tests/test_validate_import.py::test_validate_records_errors_and_rows PASSED [ 47%]
tests/test_validate_import.py::test_check_columns PASSED                 [ 52%]
tests/test_validate_import.py::test_photo_config_format PASSED           [ 58%]
tests/test_validate_import.py::test_clean_set_cli PASSED                 [ 64%]
tests/test_validate_import.py::test_photo_errors PASSED                  [ 70%]
tests/test_validate_import.py::test_duplicates PASSED                    [ 76%]
tests/test_validate_import.py::test_missing_fields_cli PASSED            [ 82%]
tests/test_validate_import.py::test_large PASSED                         [ 88%]
tests/test_validate_import.py::test_cli_missing_column PASSED            [ 94%]
tests/test_validate_import.py::test_no_mapping_or_excel_in_module PASSED [100%]

============================== 17 passed in 0.27s ==============================
```
