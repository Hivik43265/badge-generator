# Этап 12, шаг 0 — реестр действий ленты

Статус: план. Код не менялся.

Основа: утверждённый макет `ui/mockup/` и Backend в его текущем виде. Колонка «Backend» сверена с `dir(badge_backend.api)` на 03.11.2026.

## Правила
- Одно действие — один `QAction` (objectName `act_*`) — одно место в ленте.
- Кроме ленты, допустимы только горячая клавиша и пункт контекстного меню на **тот же** `QAction`.
- Строки меню, тулбара и дублирующих вкладок/окон нет.
- Свойства объекта меняются только через модель панели свойств: `PropertyModel.set(key, value)` → `update_element`. Лента («Стиль», «Положение», «Выровнять») пишет в ту же модель.
- Сторона — один переключатель `act_side` (checkable). Лицевая — off, Оборот — on, горячая клавиша Ctrl+Tab.
- «Напечатано»:
  - Дисплей — только фильтр отображения;
  - Метка — только установка статуса;
  - в группе Поиск остаются «По данным» и «Перейти к положению».

Сокращения в колонке Backend:
- «UI» — чистое действие интерфейса, Backend не нужен.
- **НУЖНО** — функции в `badge_backend.api` пока нет (сигнатуры в §3).
- Если в ячейке горячей клавиши/контекстного меню нет пометки «КМ: …», действие есть только в ленте.

## 1. Таблица действий

### Файл
| # | Действие (`objectName`) | Единственное место | Горячая клавиша / контекстное меню | Backend |
|---|---|---|---|---|
| 1 | Новый проект `act_new` | Файл / Проект | Ctrl+N | `connect` (новый файл) + `migrate` внутри; пустой шаблон |
| 2 | Открыть проект `act_open` | Файл / Проект | Ctrl+O | `connect`, `get_schema_version` |
| 3 | Сохранить как… (копия БД) `act_save_as` | Файл / Проект | Ctrl+Shift+S | **НУЖНО** `backup_db` |
| 4 | Импорт записей `act_import` | Файл / Данные | Ctrl+I | `import_file`, `map_headers` (`read_table` из services.importer) |
| 5 | Экспорт PNG/PDF `act_export` | Файл / Данные | Ctrl+E | `snapshot`, `export_png_from_snapshot`, `export_pdf_from_snapshot`, `missing_photos` |
| 6 | Настройки `act_settings` | Файл / Параметры | Ctrl+, | UI (QSettings: base_dir, шаг сетки) |
| 7 | Выход `act_exit` | Файл / Параметры | Ctrl+Q | UI |

На Файле нет «Сохранить»: данные пишутся в БД сразу, расположение окна сохраняется автоматически.

### Главная
| # | Действие | Единственное место | Горячая клавиша / контекстное меню | Backend |
|---|---|---|---|---|
| 8 | Вырезать `act_cut` | Главная / Буфер | Ctrl+X; КМ: холст | `list_elements` → буфер UI, `delete_element` |
| 9 | Копировать `act_copy` | Главная / Буфер | Ctrl+C; КМ: холст | `list_elements` (UI-буфер) |
| 10 | Вставить `act_paste` | Главная / Буфер | Ctrl+V; КМ: холст | `create_element` |
| 11 | Дублировать `act_duplicate` | Главная / Буфер | Ctrl+D; КМ: холст | `create_element` |
| 12 | Сторона: Лицевая ⇄ Оборот `act_side` | Главная / Сторона | Ctrl+Tab | `list_elements(side)`, `render_preview` |
| 13 | Фон стороны `act_background` | Главная / Сторона | КМ: пустой холст | `get_background`, `set_background` |

### Рисование
| # | Действие | Единственное место | Горячая клавиша / контекстное меню | Backend |
|---|---|---|---|---|
| 14 | Поле БД `act_tool_field` | Рисование / Данные | F | `create_element(type="field")` |
| 15 | Фото `act_tool_photo` | Рисование / Данные | P | `create_element(type="photo")` |
| 16 | Штрихкод `act_tool_barcode` | Рисование / Данные | B | `create_element(type="barcode")` |
| 17 | QR `act_tool_qr` | Рисование / Данные | Q | `create_element(type="qr")` |
| 18 | Текст `act_tool_text` | Рисование / Фигуры | T | `create_element(type="text")` |
| 19 | Рамка `act_tool_rect` | Рисование / Фигуры | R | `create_element(type="rect")` |
| 20 | Эллипс `act_tool_ellipse` | Рисование / Фигуры | E | **НУЖНО** тип `ellipse` в CHECK и рендер |
| 21 | Линия `act_tool_line` | Рисование / Фигуры | L | `create_element(type="line")` |
| 22 | Изображение `act_tool_image` | Рисование / Фигуры | I | `create_element(type="image")` |
| 23 | Цвет заливки `act_style_fill` | Рисование / Стиль | — | `update_element(style=…)` через PropertyModel |
| 24 | Цвет границы `act_style_stroke` | Рисование / Стиль | — | `update_element(style=…)` через PropertyModel |
| 25 | Толщина границы `act_style_stroke_w` (QWidgetAction) | Рисование / Стиль | — | `update_element(style=…)` через PropertyModel |
| 26 | Выровнять ▾ `act_align` (меню из 6 подпунктов: лево/центр/право/верх/середина/низ) | Рисование / Стиль | КМ: объект | `update_element(x,y)` через PropertyModel |

### Редактировать
| # | Действие | Единственное место | Горячая клавиша / контекстное меню | Backend |
|---|---|---|---|---|
| 27 | Отменить `act_undo` | Редактировать / История | Ctrl+Z | UI (QUndoStack) поверх `update/create/delete_element` |
| 28 | Повторить `act_redo` | Редактировать / История | Ctrl+Y | то же |
| 29 | Удалить объект `act_delete_element` | Редактировать / Объект | Del; КМ: объект | `delete_element` |
| 30 | Положение… `act_position` | Редактировать / Объект | Ctrl+K; КМ: объект | `update_element` через PropertyModel |
| 31 | Захват изображения `act_capture` | Редактировать / Объект | КМ: фото-объект | `update_person(photo_path=…)` |
| 32 | Выше `act_z_up` | Редактировать / Порядок | Ctrl+]; КМ: объект | `update_element(z_order)` |
| 33 | Ниже `act_z_down` | Редактировать / Порядок | Ctrl+[; КМ: объект | `update_element(z_order)` |

«Группа» из макета убрана: группировки в схеме нет и пока не нужна.

### Просмотр
| # | Действие | Единственное место | Горячая клавиша / контекстное меню | Backend |
|---|---|---|---|---|
| 34 | Увеличить `act_zoom_in` | Просмотр / Масштаб | Ctrl++ | UI |
| 35 | Уменьшить `act_zoom_out` | Просмотр / Масштаб | Ctrl+- | UI |
| 36 | По размеру `act_zoom_fit` | Просмотр / Масштаб | Ctrl+0 | UI |
| 37 | Сетка `act_grid` (checkable) | Просмотр / Показать | Ctrl+' | UI |
| 38 | Линейки `act_rulers` (checkable) | Просмотр / Показать | — | UI |
| 39 | Рендер под рамками `act_show_render` (checkable) | Просмотр / Показать | — | `render_card` |
| 40 | Сбросить расположение `act_reset_layout` | Просмотр / Окно | — | UI |

### База данных
| # | Действие | Единственное место | Горячая клавиша / контекстное меню | Backend |
|---|---|---|---|---|
| 41 | Подключить БД `act_connect` | БД / Подключение | — | `connect`, `get_schema_version` |
| 42 | Отключить `act_disconnect` | БД / Подключение | — | `connect(":memory:")` |
| 43 | Настр. поля (Менеджер полей) `act_field_manager` | БД / Установки | — | `list_fields`, `upsert_field`, `list_elements`; **НУЖНО** `delete_field`, `set_field_default`, `link_field`, `unlink_field`, `list_field_links` |
| 44 | Сжать и восстановить `act_compact` | БД / Установки | — | **НУЖНО** `backup_db`, `vacuum_db`, `restore_db` |
| 45 | Печать `act_print` | БД / Печать | Ctrl+P; КМ: таблица | `snapshot`, `print_snapshot`, `missing_photos`, затем `mark_printed` |
| 46 | Очередь печати `act_queue` | БД / Печать | — | `list_persons(only_marked=True)`, `set_print_mark(…, False)` |
| 47 | В очередь / из очереди `act_queue_toggle` | БД / Печать | Пробел; КМ: таблица | `set_print_mark` |
| 48 | Напечатано `act_mark_printed` | БД / Метка | КМ: таблица | `mark_printed` |
| 49 | Не напечатано `act_mark_unprinted` | БД / Метка | КМ: таблица | **НУЖНО** `clear_printed` |
| 50 | Дисплей: Все / Напечатанные / Ненапечатанные `act_display_*` (QActionGroup, 3 QAction, считаются как одно действие) | БД / Дисплей | — | `list_persons` + фильтр; по готовности — `query_persons(printed=…)` |
| 51 | Поиск по данным `act_find` | БД / Поиск | Ctrl+F | **НУЖНО** `query_persons(where=…)` (пока клиентский прокси) |
| 52 | Перейти к положению `act_goto` | БД / Поиск | Ctrl+G | UI (номер строки / ID) |
| 53 | Добавить карту `act_card_add` | БД / Карта | Ins; КМ: таблица | `create_person` |
| 54 | Изменить карту `act_card_edit` | БД / Карта | Enter, двойной клик; КМ: таблица | `get_person`, `update_person`, `update_photo_config` |
| 55 | Удалить карту `act_card_delete` | БД / Карта | Shift+Del; КМ: таблица | `delete_person` (для нескольких **НУЖНО** `delete_persons`) |
| 56 | Применить фильтр `act_filter_apply` (кнопка блока фильтра) | БД / блок фильтра под лентой | Enter в строке значения | **НУЖНО** `query_persons(where=…)` |

«Добавить условие» в блоке фильтра — это локальная правка выражения, а не отдельный QAction.

### Помощь
| # | Действие | Единственное место | Горячая клавиша / контекстное меню | Backend |
|---|---|---|---|---|
| 57 | Справка `act_help` | Помощь / Справка | F1 | UI |
| 58 | О программе `act_about` | Помощь / Справка | — | `get_schema_version` |

**Итого 58 действий.** Из них 12 требуют новых функций Backend: #3, 20, 43, 44, 49, 50 (опционально), 51, 55 (пакетно), 56. Номер 43 сам по себе требует 5 функций.

## 2. Дубли, удаляемые из текущего UI
| # | Файл | Что удаляется | Чем заменяется |
|---|---|---|---|
| 1 | ui/main_window.py | `QMenuBar`: `MENUS`, `_build_menus`, `self.menus` (8 меню) | Лента, 7 вкладок |
| 2 | ui/main_window.py | `QToolBar` `toolbar`/`tb_elements` (14 кнопок), стили `QToolBar` в `STYLE` | Лента |
| 3 | ui/main_window.py | `act_save` («Сохранить» = сохранение окна) | Авто-сохранение в `closeEvent` |
| 4 | ui/main_window.py | `act_front` + `act_back` + `QActionGroup` | Один `act_side` |
| 5 | ui/main_window.py | `act_printed_filter` / `toggle_printed_filter` (цикл фильтра «Напечатано») | БД / Дисплей |
| 6 | ui/main_window.py | `act_add_element` + `add_menu` (выпадающее «Добавить элемент») | Рисование / Данные и Фигуры |
| 7 | ui/main_window.py | `act_text` (повторяет tool_text) | `act_tool_text` |
| 8 | ui/main_window.py | `act_editor`, `act_main`, `act_full_preview` и центральные вкладки «Главная / Редактор макета / Предпросмотр» | Режим определяется вкладкой ленты: БД → таблица+превью, остальные → редактор |
| 9 | ui/main_window.py | `act_mark_all`, `act_unmark_all` | Выделить всё (Ctrl+A) + `act_queue_toggle` |
| 10 | ui/main_window.py | `act_rec_add/edit/del` | `act_card_*` |
| 11 | ui/layout_editor.py | `tool_actions` (9 QAction) и их ряд QToolButton над холстом | `act_tool_*` ленты; редактор получает их извне |
| 12 | ui/layout_editor.py | `act_delete`, `act_up`, `act_down` и кнопки «Порядок» | `act_delete_element`, `act_z_up/down` |
| 13 | ui/layout_editor.py | `act_side` («Сторона: лицевая») | `act_side` ленты |
| 14 | ui/layout_editor.py | Чекбокс «Показывать рендер под рамками» | `act_show_render` |
| 15 | ui/layout_editor.py | Список «Элементы стороны» (`el_list`) как способ выбора/удаления | Только холст и КМ (список убрать или оставить только для чтения; на решение Архитектора) |
| 16 | ui/layout_editor.py | Кнопка «Применить» в панели свойств | Живая запись через PropertyModel (валидация остаётся) |
| 17 | ui/records_table.py | Кнопки «Добавить / Изменить / Удалить / Отметить все / Снять отметки» | `act_card_*`, `act_queue_toggle` |
| 18 | ui/records_table.py | `printed_box` в строке фильтра | БД / Дисплей |
| 19 | ui/records_table.py | Строка поиска + `col_box` / `col_value` | Блок фильтра (поле / условие / И-ИЛИ / значение / Применить) |
| 20 | ui/main_view.py | `make_icon` (иконки тулбара) | Иконки ленты (`glyph`), одна функция |
| 21 | ui/main_view.py | `PreviewPanel` с вкладками «Поля макета / Поля БД» | Панель «Предпросмотр / Поля» (Сторона 1/2 + «Поле шаблона \| Значение из БД») |
| 22 | ui/main_view.py | `SettingsDialog` под «Опции» | `act_settings` на Файл / Параметры (диалог тот же) |
| 23 | ui/preview.py | Отдельная вкладка «Предпросмотр» с кнопкой «Обновить» | Превью в панели БД, обновление по выбору строки |
| 24 | ui/record_form.py | Чекбокс «Отметить для печати» | `act_queue_toggle` (в форме не дублировать) |

**Итого 24 дубля.** Диалоги Импорт, Экспорт, Положение, Камера, Очередь печати и Запись остаются: каждый вызывается ровно одним QAction.

## 3. Новые функции Backend (предложение, сигнатуры)
Все функции — в `badge_backend.api`, первым аргументом идёт `con`. В UI нет SQL: условия передаются как данные.

```python
# --- фильтр по выражению ---
Condition = TypedDict("Condition", {"field": str,          # имя поля person_fields | "printed_at" | "print_mark" | "id"
                                    "op": Literal["eq","ne","contains","startswith","empty","not_empty"],
                                    "value": str | None})
Where = TypedDict("Where", {"join": Literal["and","or"], "terms": list["Condition | Where"]})   # вложенность = скобки
def query_persons(con, where: Where | None = None, printed: bool | None = None,
                  only_marked: bool = False, order_by: str = "id") -> list[dict]
    # Валидирует имена полей по list_fields и op по белому списку; ValueError при ошибке.

# --- статус печати ---
def clear_printed(con, ids) -> int                       # printed_at=NULL; print_mark не трогает

# --- бэкап / сжатие / восстановление ---
def backup_db(con, dest_path: str | Path) -> Path        # sqlite backup API, атомарно
def vacuum_db(con) -> dict                               # {"size_before": int, "size_after": int}
def compact_and_backup(con, backup_dir: str | Path) -> dict   # backup_db + integrity_check + VACUUM → {"backup": path, "size_before", "size_after", "integrity": "ok"}
def restore_db(target_path: str | Path, backup_path: str | Path) -> None   # проверка schema_version + integrity

# --- поля: default_value (миграция v4: person_fields.default_value TEXT NULL) ---
def upsert_field(con, name: str, label: str, sort_order: int = 0, default_value: str | None = ...) -> None
def set_field_default(con, name: str, default_value: str | None) -> None
def delete_field(con, name: str, *, unlink: bool = True) -> bool   # без unlink → ValueError, если поле используется
#   render: пустое значение поля → default_value

# --- связь поля и объектов шаблона ---
def list_field_links(con) -> dict[str, list[dict]]       # field_name → элементы шаблона (id, type, side)
def link_field(con, element_id: int, field_name: str) -> bool     # тип field|barcode|qr; поле должно существовать
def unlink_field(con, element_id: int, static_value: str | None = None) -> bool
#   field → text (static_value), barcode/qr → static_value; CHECK v3 на field_name сохраняется

# --- тип ellipse (миграция v4: CHECK типов + render) ---
#   create_element(con, "ellipse", x, y, w, h, style={"stroke","stroke_width","fill"}) — сигнатура прежняя

# --- карты (записи) ---
#   create_person / update_person / delete_person / get_person — уже есть
def delete_persons(con, ids) -> int                      # пакетно, одной транзакцией
```

Миграцию v4 предлагается сделать одну: `person_fields.default_value`, `ellipse` в CHECK, `LATEST = 4`.

## 4. Ширина окна ≤ 1024 px и русские названия типов

### Ширина
Цель: `minimumSizeHint().width() <= 1024`. Проверка в smoke-тесте при `QT_QPA_PLATFORM=offscreen`: окно 1024×700, у кнопок ленты нет обрезанного текста.

Как этого добиться:
1. Подписи кнопок ограничены двумя строками, ширина кнопки — ≤ 72 px (перенос по словам, без многоточий). Короткие подписи: «Напечат.», «Ненапечат.», «Подключить», «Сжать / восст.».
2. Адаптивная лента: если ширина вкладки больше доступной, группы по приоритету справа налево сворачиваются в одну кнопку-группу с выпадающим меню из тех же QAction. Это не дубль, а то же место.
3. Дисплей — 3 маленькие радиокнопки в столбик. Стиль — компактный ряд (2×2): цвет, цвет, толщина, «Выровнять ▾».
4. Блок фильтра:
   - при ширине < 1100 px переносится в 2 строки;
   - комбобоксы с `setMinimumContentsLength(8)`, `AdjustToMinimumContentsLengthWithIcon`.
5. Сплиттеры:
   - вкладка БД: таблица ≥ 520 px, панель «Предпросмотр / Поля» ≥ 300 px;
   - редактор: холст ≥ 560 px, панель свойств ≥ 260 px, при 1024 px панель можно свернуть.
6. Статус-бар: сокращённые тексты («X 12,4 Y 20,5 мм»), тултипы с полными подписями.
7. Тест проверяет 7 вкладок по `w.grab()` при 1024 px: у каждой `QToolButton` `sizeHint` ≤ фактическая ширина.

### Русские названия типов
- Один словарь `TYPE_NAMES` в `ui/` (backend_api или captions). Источник правды — `ELEMENT_TYPES`:
  - field → «Поле»
  - text → «Текст»
  - photo → «Фото»
  - image → «Изображение»
  - rect → «Рамка»
  - ellipse → «Эллипс»
  - line → «Линия»
  - barcode → «Штрихкод»
  - qr → «QR-код»
- Сторона: «Лицевая» / «Оборот». Короткая форма («Лиц.» / «Об.») — только там, где нужна компактность.
- Используется везде:
  - подписи D8 (`element_caption`);
  - «Поле шаблона | Значение из БД» (вместо «(qr, Об.)» → «QR-код · оборот»);
  - Менеджер полей, «Положение», статус-бар, тултипы.
- В smoke-тесте добавить проверки:
  - для каждого `ELEMENT_TYPES` есть ключ в `TYPE_NAMES`;
  - ни одна видимая подпись не содержит латинского имени типа из `ELEMENT_TYPES`.
