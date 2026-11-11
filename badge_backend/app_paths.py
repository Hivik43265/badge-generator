"""Замечание №1 (11.11): рабочие папки программы рядом с exe.

app_root()     — корень программы:
                 переменная окружения BG_APP_ROOT (если задана) → она;
                 собранный exe (sys.frozen) → папка sys.executable;
                 запуск из исходников → корень репозитория (папка над badge_backend/).
work_dir()     — <root>/work      рабочие копии проектов, несохранённые проекты (project_session);
import_dir()   — <root>/import    временные мигрированные копии .db-импорта (sources);
logs_dir()     — <root>/logs      логи;
projects_dir() — <root>/projects  проекты пользователя по умолчанию: БД exe по умолчанию (project.db, см.
                 db.default_db_path) и настройки программы settings_path() = projects/settings.ini;
assets_dir()   — <root>/assets    шрифты (assets/fonts) и эталон smartid (assets/smartid/reference.csd).
                 В exe лежит рядом с BadgeGenerator.exe (onedir), НЕ в _MEIPASS. Из исходников
                 <repo>/assets обычно нет — поиск ресурсов тогда идёт в badge_backend/assets (см. asset_candidates).

Папки work/import/logs/projects создаются лениво, при первом вызове функции. Если корень недоступен
на запись (например, C:\\Program Files), берётся запасной корень %LOCALAPPDATA%\\BadgeGenerator
(не Windows: ~/.local/share/BadgeGenerator), в лог пишется предупреждение; исключений нет.
assets_dir() ничего не создаёт и запасного корня не имеет: ресурсы только читаются.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

ENV_ROOT = "BG_APP_ROOT"
APP_NAME = "BadgeGenerator"
_PKG_DIR = Path(__file__).resolve().parent          # badge_backend/

_lock = threading.Lock()
_cache: dict[tuple[str, str], Path] = {}            # (root, имя папки) → итоговый путь
_warned: set[tuple[str, str]] = set()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Корень программы (см. модуль). Ничего не создаёт."""
    env = (os.environ.get(ENV_ROOT) or "").strip()
    if env:
        return Path(env).expanduser().absolute()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _PKG_DIR.parent


def fallback_root() -> Path:
    """Запасной корень для записи: %LOCALAPPDATA%\\BadgeGenerator (не Windows — ~/.local/share/BadgeGenerator)."""
    base = (os.environ.get("LOCALAPPDATA") or "").strip()
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def _writable_dir(d: Path) -> bool:
    """Создать d (если нет) и проверить запись пробным файлом. Ошибки → False."""
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f".bg_wtest_{os.getpid()}_{threading.get_ident()}"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _data_dir(name: str) -> Path:
    root = app_root()
    key = (str(root), name)
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit.is_dir():
            return hit
        d = root / name
        if _writable_dir(d):
            res = d
        else:
            res = fallback_root() / name
            if key not in _warned:
                _warned.add(key)
                log.warning("папка %s недоступна на запись, использую запасную %s", d, res)
            try:
                res.mkdir(parents=True, exist_ok=True)
            except OSError as e:   # не падаем: вызывающий получит ошибку при записи конкретного файла
                log.error("не удалось создать запасную папку %s: %s", res, e)
        _cache[key] = res
        return res


def work_dir() -> Path:
    """<root>/work (создаётся при первом вызове; запасной — %LOCALAPPDATA%\\BadgeGenerator\\work)."""
    return _data_dir("work")


def import_dir() -> Path:
    """<root>/import (создаётся при первом вызове; запасной — %LOCALAPPDATA%\\BadgeGenerator\\import)."""
    return _data_dir("import")


def logs_dir() -> Path:
    """<root>/logs (создаётся при первом вызове; запасной — %LOCALAPPDATA%\\BadgeGenerator\\logs)."""
    return _data_dir("logs")


def projects_dir() -> Path:
    """<root>/projects (создаётся при первом вызове; запасной — %LOCALAPPDATA%\\BadgeGenerator\\projects)."""
    return _data_dir("projects")


SETTINGS_FILE = "settings.ini"


def settings_path() -> Path:
    """Замечание №1 (доп.): файл настроек программы (последний проект db_path, окно, сетка) —
    projects_dir()/settings.ini, формат INI (QSettings IniFormat). Файл не создаётся — только путь;
    папка projects/ создаётся (см. projects_dir)."""
    return projects_dir() / SETTINGS_FILE


def legacy_appdata_dir() -> Path | None:
    """Где exe держал данные до замечания №1: %APPDATA%\\BadgeGenerator (нет APPDATA — ~/.BadgeGenerator).
    Только для однократного КОПИРОВАНИЯ старых данных в новые папки; ничего не создаёт и не удаляет."""
    base = (os.environ.get("APPDATA") or "").strip()
    return Path(base) / APP_NAME if base else Path.home() / ".BadgeGenerator"


def assets_dir() -> Path:
    """<root>/assets — только чтение, не создаётся."""
    return app_root() / "assets"


def asset_candidates(*parts: str) -> list[Path]:
    """Где искать ресурс assets/<parts>, по порядку:
    1) <root>/assets/<parts> (exe: рядом с BadgeGenerator.exe);
    2) badge_backend/assets/<parts> (запуск из исходников);
    3) <_MEIPASS>/badge_backend/assets/<parts> (старые onefile-сборки)."""
    out = [assets_dir().joinpath(*parts), _PKG_DIR.joinpath("assets", *parts)]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        out.append(Path(mei).joinpath("badge_backend", "assets", *parts))
    seen, res = set(), []
    for p in out:
        k = str(p)
        if k not in seen:
            seen.add(k); res.append(p)
    return res


def find_asset(*parts: str) -> Path | None:
    """Первый существующий файл из asset_candidates(*parts) или None."""
    for p in asset_candidates(*parts):
        if p.is_file():
            return p
    return None


__all__ = ["ENV_ROOT", "APP_NAME", "SETTINGS_FILE", "is_frozen", "app_root", "fallback_root", "work_dir", "import_dir",
           "logs_dir", "projects_dir", "settings_path", "legacy_appdata_dir", "assets_dir", "asset_candidates",
           "find_asset"]
