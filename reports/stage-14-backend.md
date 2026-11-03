# Этап 14 — бэкенд редактора фото (BG-Backend)

## D36 (отдельный коммит 3927181)
Колонка фото (синонимы `photo_path`/`photo`/«Фото»/«файл фото»/«путь к фото»/«фотография» или ручная цель)
→ первое поле `data_type='image'` проекта (по sort_order), если есть, иначе `persons.photo_path`.
Единый токен цели: `headers.PHOTO_TARGET = "photo_path"`; в ручном mapping принимаются псевдонимы
`headers.PHOTO_ALIASES = ("photo_path", "photo", "__photo__")`. UI показывает одну колонку фото с ключом `photo_path`.
Проектный .db-импорт не затрагивается (photo_path → photo_path). Встроенные картинки xlsx по-прежнему → photo_path.

## API (badge_backend.api)
```
DEFAULT_PHOTO_EDIT = {"brightness": 0, "contrast": 0, "scale": 100, "rotate": 0.0, "crop": None, "autoeffect": False}
def apply_photo_edit(img: Image.Image, params: dict | None) -> Image.Image
def detect_face_crop(img: Image.Image, aspect: float)   # -> (x, y, w, h) | None
def get_photo_edit_defaults(con) -> dict
def set_photo_edit_defaults(con, params: dict | None) -> dict
def apply_and_save_photo(con, source_path, params, *, person_id=None, field_name=None, base_dir=None) -> str
```
Модуль `badge_backend/services/photo_edit.py` (+ `normalize_params`, `cascade_path`).

### apply_photo_edit
- brightness int −50..50 (×(1+b/100)), contrast int −50..50 (×(1+c/100)), scale int 10..400 %, rotate float
  −180..180° **по часовой** (`PIL.rotate(-deg, expand=True)`, углы белые / прозрачные у RGBA),
  crop (x,y,w,h)|None — в пикселях **уже преобразованного** изображения, обрезается границами (пусто → ValueError),
  autoeffect — `autocontrast(cutoff=1)` + нормализация средней яркости к 128 (×0.6..1.6), ручные поверх.
- Порядок: autoeffect → brightness → contrast → scale → rotate → crop. Значения приводятся к типу и обрезаются в
  диапазон; нечисло → ValueError. Вход не изменяется; при параметрах по умолчанию — копия.
- Скорость: 800×800 со всеми параметрами ≈ 65 мс (Linux); превью — UI передаёт уменьшенную картинку.

### detect_face_crop
OpenCV Haar `haarcascade_frontalface_default.xml`, самое крупное лицо. Кадр: H = лицо/0.65 (лицо 65% высоты),
W = H·aspect, лицо по центру по горизонтали, верх кадра на 0.12·H выше верха лица. Без полей: кадр больше
изображения → уменьшается с сохранением aspect, затем сдвигается внутрь. Результат в пикселях переданного img,
w/h ≈ aspect (округление). Нет лица → None. 800×800 ≈ 22 мс.
Каскад: в exe — `<_MEIPASS>/cv2/data/`, иначе `cv2.data.haarcascades`.

### Умолчания проекта
Отдельного механизма настроек не было → миграция **v6**: `project_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)`,
ключ `photo_edit_defaults` (JSON). crop не сохраняется. Нет записи → DEFAULT_PHOTO_EDIT.

### apply_and_save_photo
Исходник (относительный — от base_dir/каталога проекта, EXIF-поворот) → apply_photo_edit → новый JPEG (q=92,
прозрачность на белом) через save_photo в `photos/`; исходник не перезаписывается. field_name (только image-поле,
нужен person_id) → значение поля, иначе person_id → photo_path. Ошибки → ValueError, новый файл удаляется.

## Сборка
- requirements.txt: `opencv-python-headless>=4.8,<5`, `numpy` (в колёсах opencv 5.0 нет cv2/data/*.xml — проверено).
- spec: каскад в datas (`cv2/data`), hiddenimports `cv2`, `numpy`; `opencv_videoio_ffmpeg*.dll` исключается;
  smoke-exe исключает cv2; в `dist/BadgeGenerator.bundle.txt` строка про каскад — CI-шаг падает при MISSING.
- Оценка роста exe: +35–45 МБ (cv2.pyd ≈ 60–70 МБ и numpy ≈ 20 МБ без сжатия, onefile сжимает ~2×). Не измерено (нужен Windows).

## Тесты
tests/test_photo_edit.py (14), tests/test_d36_photo_column.py (10); номера версии схемы в старых тестах → 6.
Фикстура лица: tests/fixtures/face_astronaut.jpg (NASA, public domain; источник — face_astronaut.SOURCE.txt).
