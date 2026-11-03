# Этап 8 — тестовые фото (BG-Data), дефект QA D4 + уточнение архитектора

## Что изменилось
- `data_tools/testdata/make_testsets.py`: однотонные 60×80 заменены **полностью асимметричным** шаблоном (`pattern()`), добавлены `make_fixtures()` и флаг `--fixtures`.
- Наборы `testdata/sets/` перегенерированы (clean, large — новые фото; zero_byte_and_broken — плохие файлы остались плохими).
- Новый фиксированный набор `testdata/fixtures/photo_config/`: `portrait_300x400.png`, `portrait_600x800.png`, `landscape_400x300.png`, `markers.json`, `README.md` (размеры и позиции элементов в пикселях).
- Тесты `tests/test_testsets.py`: размеры, маркеры, режим RGB/без метаданных, совпадение `markers.json` с пикселями, побайтная идентичность при повторной генерации, отсутствие зеркальной/поворотной симметрии.
- Превью: `/workspace/badge_generator/data_tools/testdata/preview_sample.png` (три фикстуры рядом).

**Рендер-тесты и эталонные (golden) PNG — зона Backend (`/workspace/badge_generator/tests/`).** BG-Data их не пишет, а поставляет только входные фикстуры.

## Размеры
| Набор | Файлы | Размеры |
|---|---|---|
| fixtures/photo_config | portrait_300x400.png, portrait_600x800.png, landscape_400x300.png | 300×400, 600×800, 400×300 |
| clean | p1–p5.jpg | 300×400, 300×400, 600×800, 400×300, 300×400 |
| large | base_1–base_5.jpg (1000 строк по кругу) | те же 5 размеров |
| zero_byte_and_broken | IMG_2.JPG, img_1.webp, img_10.png — валидные 300×400; empty.jpg, broken.jpg, notes.txt — намеренно плохие | — |

## Шаблон (асимметричный)
- Фон: R растёт слева направо, G — сверху вниз, B — по диагонали (максимум в TL) — у каждого пикселя уникальный цвет по положению.
- Сетка от левого верхнего угла, каждая 4-я линия чёрная.
- Уникальные угловые маркеры: **TL — красный квадрат, TR — зелёный круг, BL — синий треугольник, BR — жёлтый ромб**, с подписями.
- Перекрестие в центре; стрелка «UP» смещена влево (x=0.3w); номер `#N` и размер — вправо-вниз (0.68w, 0.62h); пурпурная якорная точка в (0.3w, 0.7h).
- Тест подтверждает: отражение по горизонтали/вертикали и поворот на 180° дают другое изображение.

## Фикстуры: формат
- PNG, режим RGB, без альфа-канала, без метаданных, `compress_level=0`; повторная генерация побайтно идентична (проверяется sha256 в тесте).
- `markers.json`: `{файл: [{name, x, y, color:[r,g,b]}]}` — 7 контрольных пикселей на файл (4 угловых маркера, центр перекрестия, якорная точка, остриё стрелки).
- Пример (portrait_300x400.png): TL (4,36)=(255,0,0); TR (279,34)=(0,200,0); BL (4,394)=(0,0,255); BR (279,368)=(255,210,0); центр (150,200)=(0,0,0); якорь (90,280)=(255,0,255); стрелка (90,64)=(0,0,0).

## Вывод pytest
```
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- /usr/bin/python3
rootdir: /workspace/badge_generator
configfile: pytest.ini
collecting ... collected 25 items

tests/test_clean_photos.py::test_clean_copies_and_reports PASSED         [  4%]
tests/test_clean_photos.py::test_dry_run_writes_nothing PASSED           [  8%]
tests/test_clean_photos.py::test_start_digits_and_report_dir PASSED      [ 12%]
tests/test_clean_photos.py::test_refuses_same_or_nested_out PASSED       [ 16%]
tests/test_clean_photos.py::test_refuses_nonempty_out PASSED             [ 20%]
tests/test_clean_photos.py::test_natural_sort PASSED                     [ 24%]
tests/test_testsets.py::test_photos_big_enough_and_varied PASSED         [ 28%]
tests/test_testsets.py::test_corner_markers_distinct PASSED              [ 32%]
tests/test_testsets.py::test_large_reuses_few_bases PASSED               [ 36%]
tests/test_testsets.py::test_bad_sets_still_bad PASSED                   [ 40%]
tests/test_testsets.py::test_fixtures_mode_size_no_metadata PASSED       [ 44%]
tests/test_testsets.py::test_markers_match_pixels PASSED                 [ 48%]
tests/test_testsets.py::test_regeneration_byte_identical PASSED          [ 52%]
tests/test_testsets.py::test_pattern_asymmetric PASSED                   [ 56%]
tests/test_validate_import.py::test_validate_records_pure_ok PASSED      [ 60%]
tests/test_validate_import.py::test_validate_records_errors_and_rows PASSED [ 64%]
tests/test_validate_import.py::test_check_columns PASSED                 [ 68%]
tests/test_validate_import.py::test_photo_config_format PASSED           [ 72%]
tests/test_validate_import.py::test_clean_set_cli PASSED                 [ 76%]
tests/test_validate_import.py::test_photo_errors PASSED                  [ 80%]
tests/test_validate_import.py::test_duplicates PASSED                    [ 84%]
tests/test_validate_import.py::test_missing_fields_cli PASSED            [ 88%]
tests/test_validate_import.py::test_large PASSED                         [ 92%]
tests/test_validate_import.py::test_cli_missing_column PASSED            [ 96%]
tests/test_validate_import.py::test_no_mapping_or_excel_in_module PASSED [100%]

============================== 25 passed in 0.95s ==============================
```
