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

## Доработки по проверке Контролёра (D40, D41)
- **D40** (59ce004): detect_face_crop считает запас от оценённой макушки: `head_top = haar_top − 0.30·fh`,
  голова (макушка..низ Haar, 1.3·fh) = 65 % высоты кадра (`FACE_HEIGHT`), над макушкой 40 % свободного места (`TOP_SHARE`).
  face_astronaut.jpg (200×200, Haar 70,26,37,37), aspect 0.75: было: запас 7 px от лба → стало (61, 5, 56, 74):
  от верха Haar 21 px, от оценённой макушки (y≈14.9) ≈10 px; голова/кадр = 48.1/74 = 0.65. Тест: tests/test_d40_headroom.py.
- **D41** (6be18c3): в DEFAULT_PHOTO_EDIT добавлен `"portrait": False` (bool; строки true/false/1/0/да/нет, иначе ValueError).
  Хранится в project_settings key `photo_edit_defaults` (JSON) через `set_photo_edit_defaults(con, {..., "portrait": True})`,
  читается `get_photo_edit_defaults(con)["portrait"]`; старые записи без ключа → False. На пиксели в apply_photo_edit
  не влияет (флаг UI: кадрировать через detect_face_crop). Тест: tests/test_d41_portrait.py.
- pytest 402 passed; e2e_stage13 67/67, e2e_stage13b 29/29 (e2e_stage14 в reports/qa не найден).

## D42 (заменяет правило D40 «60–70 %»): рамка из шаблона + новое кадрирование
Слова Ивана: «Рамка в редакторе не должна полностью брать лицо. Учитывается размер рамки в шаблоне обязательно».
- `get_photo_frame_spec(con, field=None) -> dict | None` (`badge_backend.services.photo_edit`, `api`):
  field — имя или rowid image-поля; None — фото записи (photo-элементы без field_name). Первый photo-элемент
  с этим полем: лицевая сторона, затем z_order, id. → `{aspect, width_mm, height_mm, width_px, height_px, element_id, side}`
  (мм = px·25.4/300, выход при 300 DPI). Нет элемента / поле не image → None (редактор без фикс. пропорций).
- `detect_face_crop(img, aspect)`: макушка = верх Haar − 0.25·fh, подбородок = низ Haar; голова 50 % высоты
  рамки, над макушкой 10 %, ниже подбородка ~40 % (шея, плечи), лицо по центру. За краем — сдвиг, если рамка
  больше фото — уменьшение с сохранением aspect.
- Фото для тестов: `tests/fixtures/portrait_biden.jpg` 640×800, public domain (см. .SOURCE.txt).
  aspect 0.778 (35×45): рамка (114,52,411,528), голова 50.2 %, запас 9.8 %; aspect 1.111: (26,52,587,528), то же.
- e2e_stage14 (Контролёра): проверка «лицо 60–70 %» теперь FAIL (0.402 по её мере) — правило отменено, нужна новая проверка 45–55 % голова / ~10 % запас.

## D43: отмена формы записи
- `discard_photo(con, paths, base_dir=None) -> list[str]` удаляет только файлы прямо в `<base>/photos/`,
  без ссылок (persons.photo_path, image-поля). Исходники и файлы со ссылками не трогаются.
- `PhotoSession(con, base_dir=None)`: `.save_photo(bytes, **kw)`, `.apply_and_save_photo(src, params, **kw)`,
  `.track(rel)`, `.discard()` (Отмена), `.commit(discard_unreferenced=False)` (Сохранить).
