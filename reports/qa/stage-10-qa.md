# Этап 10 — QA: пустой шаблон, barcode / QR / line, миграция v3

**Проверял:** BG-Контролёр (QA), 03.11.2026, около 16:58 MSK. Продуктовый код и `.venv` не менялись. zxing-cpp 3.1.1 уже стоял в `.venv` (requirements-dev), ничего не ставил.
**Скрипт:** `reports/qa/e2e_stage10.py`.
**Выводы:** `e2e_stage10_output.txt`, `e2e_stage10_results.json`, `pytest_stage10.txt`, `ui_smoke_stage10.txt`, `e2e_output_stage10_regress.txt`.
**Картинки:** `s10_code128.png`, `s10_ean13.png`, `s10_qr_H.png`, `s10_lines.png`, `s10_all_types.png`.

> Во время проверки Frontend менял `ui/layout_editor.py`: стиль линии `width` заменён на `stroke_width`, ключ штрихкода `symbology` на `format`. Результаты — снимок на момент прогона.

## Итог
- **e2e этапа 10: 19 PASS / 1 FAIL.**
- **pytest: 254 passed**, 0 failed.
- **ui/smoke_test.py: FAIL**, код возврата 1: 32 шага OK, затем падение на строке 320.
- **Старые проверки e2e_check.py: 31/31 PASS** после перевода трёх устаревших проверок на v3 (обновлено 03.11.2026, около 17:00 MSK).

## e2e этапа 10
| Проверка | Результат | Доказательство |
|---|---|---|
| 1a Свежая БД: 0 template_elements, user_version=3 | PASS | elements=0, backgrounds=0, user_version=3 |
| 1b Нет seed-макетов в badge_backend/ и миграциях | PASS | вызовы вне определений: нет |
| 1c «Гость»/«ООО Пример» только в tests/ и reports/ | FAIL | вне tests/reports: ['./ui/smoke_test.py']; всего файлов 12 |
| 2a Пустой шаблон → белое 1011×638 | PASS | size=(1011, 638), extrema(L)=(255, 255) |
| 2b Экспорт PNG/PDF и печать пустого шаблона: warning, без исключения | PASS | PNG: 2 файлов, empty_template=True, warnings=['шаблон пуст: нет элементов ни на одной экспортируемой стороне']; PDF: True; печать: 2 стр., True; RuntimeWarning: 1/1/1 |
| 3 code128: модуль целый px, декодируется в исходное | PASS | модуль=4px, все полосы кратны модулю=True, decode=[('Code 128', 'BG-000123')], ожидалось 'BG-000123' |
| 3 ean13: модуль целый px, декодируется в исходное | PASS | модуль=5px, все полосы кратны модулю=True, decode=[('EAN-13', '4601234567893')], ожидалось '4601234567893' |
| 3c Невалидный EAN-13 (контрольная цифра) → warning без исключения | PASS | warnings=["элемент 1: штрихкод ean13 '4601234567890' не отрисован — EAN-13: неверная контрольная цифра в '4601234567890' (ожидалась 3)"] |
| 3d UI-ключ style['symbology'] принимается (ean13 + не цифры → warning) | PASS | warnings=["элемент 1: штрихкод ean13 'BG-1' не отрисован — EAN-13: нужно 12 или 13 цифр, получено 'BG-1'"] |
| 4 QR L/M/Q/H: квадрат в min(w,h), модуль целый, декодируется | PASS | L: 198×198 px = 33 мод×6px, decode=['https://example.com/badge/42'], ec=['L']; M: 185×185 px = 37 мод×5px, decode=['https://example.com/badge/42'], ec=['M']; Q: 185×185 px = 37 мод×5px, decode=['https://example.com/badge/42'], ec=['Q']; H: 205×205 px = 41 мод×5px, decode=['https: |
| 5a line: горизонтальная, вертикальная, диагональ с отрицательными w/h | PASS | (250,100)=(255, 0, 0) (600,200)=(0, 170, 0) (800,500)=(0, 0, 255) |
| 5b line w=h=0 отклоняется (отрицательные w/h разрешены) | PASS | IntegrityError: CHECK constraint failed: (type <> 'line' AND w > 0 AND h > 0) OR (type = 'line' AND NOT (w = 0 AND h = 0)); w=-50,h=-20 принято |
| 5c Линия со стилем UI по умолчанию рисуется заданной толщиной | PASS | UI DEFAULT_STYLE['line']={'stroke': '#1F4E8C', 'stroke_width': 3}; толщина по факту=3px, ожидалось 3 |
| 6 Миграция v2→v3: persons/template_elements и id сохранены | PASS | user_version 2→3 (повторно 3); persons ids=[3, 7, 10], elements ids=[5, 9, 12, 20]; данные совпали=True; индекс=[('idx_te_side_z',)]; integrity=ok |
| 6 Миграция v1→v3: persons/template_elements и id сохранены | PASS | user_version 1→3 (повторно 3); persons ids=[3, 7, 10], elements ids=[5, 9, 12, 20]; данные совпали=True; индекс=[('idx_te_side_z',)]; integrity=ok |
| 7 Фон template_backgrounds рисуется под элементами | PASS | вне элемента=(200, 0, 0) (картинка фона), внутри rect=(0, 0, 255) (элемент поверх) |
| 7b Фон-цвет без картинки | PASS | (0, 255, 0) |
| 8 Все типы CHECK рендерятся без warning «reserved/пропущен» | PASS | types=['text', 'field', 'photo', 'image', 'rect', 'qr', 'barcode', 'line']; warnings=['unclosed database in <sqlite3.Connection object at 0x7f10fd371300>', 'unclosed database in <sqlite3.Connection object at 0x7f10fd372f20>', 'unclosed database in <sqlite3.Connection object at 0x7f10fd3717b0>'] |
| 9a Нет SQL в ui/ (кроме smoke_test) | PASS | grep пусто |
| 9b UI: кнопка добавления для каждого типа + удалить + z_order | PASS | TOOLS→types=['barcode', 'field', 'image', 'line', 'photo', 'qr', 'rect', 'text']; нет кнопки для —; act_delete/«Выше»/«Ниже» есть |
| 10a Полный pytest | PASS | 254 passed, 7 warnings за 6.44 с |
| 10b ui/smoke_test.py | **FAIL** | `ui/smoke_test.py:320` KeyError: 'symbology' |
| 10c Старые проверки e2e_check.py | PASS (31/31) | Переведены на v3: «qr рисуется» (декодируется в 'BG-QR-1', без warning), «barcode (back) рисуется» (без warning), «Миграция 1→LATEST=3» (user_version 1→3, повторно 3, данные сохранены). Импорт, рендер, экспорт, печать ±0.15 мм, mark_printed, D2/D3 — PASS |

Примечание к п. 8: единственные warnings — ResourceWarning «unclosed database» от тестовых соединений QA-скрипта. Предупреждений «reserved» или «пропущен» нет ни для одного из 8 типов: text, field, photo, image, rect, qr, barcode, line.

## Дефекты
| # | Исполнитель | Файл:строка | Описание | Важность |
|---|---|---|---|---|
| D8 | Frontend | `ui/smoke_test.py:320` | Smoke проверяет `style["symbology"] == "code128"`, а `ui/layout_editor.py:30,390` теперь пишет `style["format"]` и удаляет `symbology`. Smoke устарел и падает (KeyError). Нужно проверять `format` | средняя (smoke красный) |
| D9 | Frontend | `ui/smoke_test.py:100,105,106,116` | Строка «Гость» есть вне tests/ и reports/: тестовый текст лежит в ui/. Нужно перенести smoke в tests/ или заменить текст | низкая |
| — | Backend | — | Новых дефектов нет. D7 (SQL в UI) закрыт: `ui/backend_api.py:53-54` вызывает `api.get_schema_version` | — |
| D4 | Data | `testdata/sets/*/photos` | Не перепроверялся (у Backend свои фото в tests/ для test_photo_transform) | низкая |

## Изменения QA-скрипта
`e2e_check.py`: три устаревшие проверки v1/v2 (qr пропускается, barcode пропускается, миграция 1→2) заменены на ожидания v3. Выполнено, 31/31 PASS. Повторный прогон `e2e_stage10.py`: 19/20 — тот же FAIL 1c (D9).
