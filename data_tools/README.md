# data_tools — подготовка данных Badge Generator

Python 3.10+, зависимости: `pip install pillow pytest` (openpyxl нужен только генератору сырого xlsx).
Здесь нет UI, рендера и обработки изображений (crop/scale/rotate делает backend через `photo_config`).

## clean_photos.py
```
python clean_photos.py <src> <out> [--dry-run] [--start 1] [--digits 4] [--report-dir DIR]
```
- Исходная папка **не изменяется**: валидные фото копируются в `<out>` (байт-в-байт).
- Отбраковка: `zero_byte` (0 байт), `broken` (Pillow не открывает), `unsupported` (не jpg/jpeg/png/webp).
- Имена: `0001.jpg`, `0002.png`… в натуральном порядке исходных имён, расширение в нижнем регистре.
- Отчёты: `mapping.csv` (old,new) и `rejected.csv` (file,reason) в `<out>` или `--report-dir`.
- `<out>` должна быть пустой/новой и не совпадать с `<src>` и не лежать внутри неё.

## validate_import.py
Маппинг заголовков и чтение Excel — зона Backend. Модуль работает с записями-словарями
с каноническими полями `persons`: last_name, first_name, middle_name, position, department,
photo_path, email, phone, photo_config.

API (чистые функции):
```python
from validate_import import validate_records, valid_records, check_columns, Error
errors = validate_records(records, photos_dir=None, start_row=1)  # -> list[Error(row, field, code, details)]
ok = valid_records(records, errors, start_row=1)                  # нормализованные валидные записи
```
CLI (только CSV UTF-8 с каноническими заголовками):
```
python validate_import.py <file.csv> [--photos DIR] [--report ../reports/report.csv] [--valid valid.csv]
```
- Коды: `MISSING_COLUMN` (нет колонки last_name/first_name), `REQUIRED_MISSING`, `DUPLICATE`
  (фамилия+имя+отчество+email, без учёта регистра и ё/е), `EMAIL_INVALID`, `PHONE_INVALID` (10–15 цифр),
  `PHOTO_CONFIG_INVALID`, `PHOTO_NOT_FOUND` / `PHOTO_EMPTY` / `PHOTO_BROKEN`, `PHOTO_MISSING` (при `--photos` фото не указано).
- `photo_config`: `x;y;scale;crop_x;crop_y;angle`, 6 частей, crop_x/crop_y — целые, остальные — числа (через точку); пусто → `0;0;1.0;0;0;0`. Только проверка формата.
- `photo_path` относительно `--photos` (или абсолютный); проверяется: существует, не пуст, открывается Pillow.
- Отчёт CSV `row,field,code,details` (заголовок CSV = строка 1), валидные → `valid.csv`. Код выхода 1 при ошибках.

## Тестовые наборы
`python testdata/make_testsets.py [out]` (по умолчанию `testdata/sets/`): `clean`, `zero_byte_and_broken`,
`duplicates`, `missing_fields`, `large` (1000 строк) — `persons.csv` с каноническими заголовками; фото генерируются.
`messy_headers/persons_raw.xlsx` — сырые данные (ФИО, кривые заголовки) для тестов маппинга у Backend; нашими тестами не используется.

## Тесты
`python -m pytest tests -v` — включая проверку, что исходники не меняются (sha256 до/после).

## Фикстуры photo_config
`python testdata/make_testsets.py --fixtures` → `testdata/fixtures/photo_config/`: `portrait_300x400.png`,
`portrait_600x800.png`, `landscape_400x300.png` (RGB, без альфы и метаданных, compress_level=0, побайтно детерминированы),
`markers.json` (контрольные пиксели {name, x, y, color}) и `README.md` с координатами. Шаблон асимметричный.
Рендер-тесты и эталонные PNG — зона Backend (`/workspace/badge_generator/tests/`).
