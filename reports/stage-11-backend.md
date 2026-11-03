# Этап 11 — Backend: сборка Windows .exe (PyInstaller + GitHub Actions)

## Файлы
- `packaging/badge_generator.spec` — два onefile-exe: `BadgeGenerator` (main.py, windowed, иконка) и `BadgeSmoke` (packaging/smoke_entry.py, console, без PyQt6). Включены `badge_backend/schema.sql`, data-файлы `barcode` (шрифт ImageWriter) и `qrcode`; hiddenimports badge_backend/barcode/qrcode.image.pil; исключены data_tools (опционален, есть builtin-fallback), pytest, tkinter.
- `packaging/icon.ico` — сгенерирован Pillow (бейдж), размеры 16/24/32/48/64/128/256.
- `packaging/smoke_entry.py` — migrate в tmp, рендер пустого шаблона (1011×638), элементы rect/field/barcode/qr/line, экспорт PNG+PDF, выход 0.
- `.github/workflows/build-windows.yml` — windows-latest, Python 3.11, pip install requirements(+dev)+pyinstaller, pytest (QT_QPA_PLATFORM=offscreen), сборка, смоук BadgeSmoke.exe, проверка что GUI-exe стартует и живёт 15 с и создаёт БД в %APPDATA%, upload-artifact `BadgeGenerator` (dist/BadgeGenerator.exe). Триггеры: push тегов `v*`, workflow_dispatch.
- `badge_backend/db.py` — минимальная разрешённая правка (см. ниже); `tests/test_frozen_paths.py` — 2 теста.
- `README.md` — раздел о сборке.

## Почему правка db.py
UI считает `ROOT = Path(ui/backend_api.py).parent.parent` и вызывает `default_db_path(ROOT)`. В onefile это `_MEIPASS` (временная папка, удаляется при выходе) → БД терялась бы. Теперь в frozen-режиме, если каталог не задан или лежит внутри `_MEIPASS`, возвращается `%APPDATA%\BadgeGenerator\project.db` (каталог создаётся; без APPDATA — `~/.BadgeGenerator`). Явный каталог вне _MEIPASS и всё поведение вне frozen не изменены. `schema.sql` ищется рядом с db.py, иначе в `_MEIPASS/badge_backend/`.

## Почему отдельный смоук-exe, а не флаг --smoke
У main.py флага --smoke нет, а правка точки входа/ui/ — зона Frontend и код заморожен. Отдельный BadgeSmoke.exe собирается тем же spec из тех же модулей backend, поэтому проверяет упаковку schema.sql/barcode/qrcode/Pillow без правок UI. Запуск самого GUI-exe проверяется отдельным шагом (стартует, не падает 15 с, создаёт БД в %APPDATA%). Если Архитектор захочет --smoke в main.py — это задача Frontend.

## Локальная проверка (Linux, 2026-11-03 19:17 MSK)
- `.venv/bin/python -m pytest -q` → **256 passed** (было 254 + 2 новых).
- `python packaging/smoke_entry.py` → `SMOKE OK: schema v3, 2 png, pdf 48172 bytes`.
- PyInstaller 6.x, Python 3.11 в отдельном venv /tmp/pyi (общий .venv не тронут), тот же spec → rc=0: BadgeGenerator (~96 МБ), BadgeSmoke (~20 МБ).
- `BadgeSmoke` (frozen) → `SMOKE OK`, код 0.
- `BadgeGenerator` (frozen, QT_QPA_PLATFORM=offscreen) работал 15 с до timeout, создал `$APPDATA/BadgeGenerator/project.db`.
- YAML: `actionlint` — без замечаний; `yaml.safe_load` ок.

## Не проверено
- **Зелёный workflow на windows-latest и скачивание артефакта не проверены**: git-репозитория и remote нет, gh не авторизован, push не делался.
- Сборка под Windows проверена только по аналогии с Linux. Шрифты: на Windows DejaVu нет, fonts.py берёт Arial из C:/Windows/Fonts (кириллица есть); шрифты в exe не вшиты, т.к. fonts.py ищет только системные каталоги (менять код нельзя).

## GitHub (только чтение)
- `git remote -v` → `fatal: not a git repository` (в /workspace/badge_generator нет .git).
- `gh auth status` → `You are not logged into any GitHub hosts`.
- Существование репозитория проверить нельзя; ничего не создавалось, не пушилось, логина не было.

## Что нужно от людей
1. Решение Ивана: создать репозиторий на GitHub (имя/владелец, приватный?) и авторизация (`gh auth login` или PAT).
2. `git init`, .gitignore (.venv, dist, build, *.db, __pycache__), первый коммит, push.
3. Запуск: Actions → build-windows → Run workflow, или `git tag v0.1.0 && git push --tags`. Затем скачать артефакт BadgeGenerator и запустить на Windows.
