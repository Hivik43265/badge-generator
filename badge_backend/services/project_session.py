"""Этап 15 B3: сессия проекта — исходник не трогается, пока пользователь не нажмёт «Сохранить».

Рабочая копия: <имя>.db.work рядом с проектом (на Windows — скрытый) или
%TEMP%/BadgeGenerator-work/… (нет прав / сетевой диск). Пути photos/ и фонов —
от каталога исходника (con.bg_base_dir).

Новый проект — тройка <имя>.csp + <имя>.csd + <имя>.db рядом, плюс photos/ и
template_bg/. Эталон шаблона — наша .db; .csd нужен для совместимости со
Smart ID Designer. Свой .csp (ссылается на нашу .db) открывается из .db как
сохранённый проект. Чужой .csp/.csd — импорт в несохранённый проект.
Старый проект из одной .db по-прежнему открывается; Save пишет только .db,
«Сохранить как» превращает его в тройку.
"""
from __future__ import annotations
import json, os, socket, sqlite3, tempfile, time, logging
from pathlib import Path

from .. import db as _db
from .photos import set_project_base_dir

log = logging.getLogger(__name__)
SESSION_FMT = 1
WORK_TEMP_DIR = "BadgeGenerator-work"
STALE_AGE_S = 6 * 3600
SAVE_RETRIES = 8


class ProjectLockedError(RuntimeError):
    """Файл открыт живым процессом. .source_path, .pid, .host"""
    def __init__(self, source_path, pid=None, host=None):
        super().__init__(f"файл уже открыт в другой копии программы: {source_path}")
        self.source_path, self.pid, self.host = Path(source_path), pid, host


class RecoverableProjectError(RuntimeError):
    """Есть рабочая копия после сбоя. .info — как у list_recoverable_sessions()."""
    def __init__(self, info: dict):
        super().__init__("проект не был сохранён — есть несохранённые правки")
        self.info = info


class ProjectSaveError(RuntimeError):
    """Сохранение не удалось (файл занят, диск, частичный отказ ReplaceFile)."""


class UnsavedChangesError(RuntimeError):
    """close(..., save=None) при is_dirty() — Frontend показывает вопрос."""


class TemplateEditActiveError(RuntimeError):
    """save/save_as/import_template без commit_template=True, пока есть template_edit_snapshot."""


def _host():
    try: return socket.gethostname()
    except OSError: return ""


def _pid_alive(pid, host=None) -> bool:
    if not pid: return False
    if host and host != _host(): return False
    if os.name == "nt":
        # os.kill(pid, 0) на Windows = CTRL_C_EVENT всей консольной группе.
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED -> жив
        try:
            code = ctypes.c_uint32()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _same_path(a, b) -> bool:
    try: return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def session_path(source: Path) -> Path:
    return source.with_name(source.name + ".bg-session")


def _work_session_path(work: Path) -> Path:
    return work.with_name(work.name + ".bg-session")


def _find_session_file(source: Path) -> Path | None:
    """Рядом с исходником или в %TEMP%/BadgeGenerator-work/ (source_path в JSON)."""
    sp = session_path(source)
    if sp.is_file():
        return sp
    root = Path(tempfile.gettempdir()) / WORK_TEMP_DIR
    if not root.is_dir():
        return None
    try:
        files = list(root.glob("*.bg-session"))
    except OSError:
        return None
    for cand in files:
        data = _read_session(cand)
        if not data:
            continue
        src = data.get("source_path")
        if src and _same_path(src, source):
            return cand
    return None


def default_work_path(source: Path) -> Path:
    return source.with_name(source.name + ".work")


def bak_path(source: Path) -> Path:
    return source.with_suffix(source.suffix + ".bak")


def _hide_windows(path: Path) -> None:
    if os.name != "nt": return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)
    except Exception:
        log.debug("не удалось скрыть %s", path, exc_info=True)


def should_use_temp_work(directory: Path) -> bool:
    """True, если в каталог проекта нельзя писать или это сетевой диск."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".bg_wtest_{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return True
    raw = str(directory.resolve()) if directory.exists() else str(directory)
    if raw.startswith("\\\\") or raw.startswith("//"): return True
    if os.name == "nt":
        try:
            import ctypes
            root = os.path.splitdrive(os.path.abspath(raw))[0] + "\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 4:  # DRIVE_REMOTE
                return True
        except Exception:
            pass
    return False


def _temp_work_path(source: Path) -> Path:
    d = Path(tempfile.gettempdir()) / WORK_TEMP_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{os.urandom(4).hex()}_{source.stem}.db"


def _sidecar_paths(p: Path):
    return [Path(str(p) + sfx) for sfx in ("-wal", "-shm", "-journal")]


def _remove_sidecars(p: Path) -> None:
    for s in _sidecar_paths(p):
        try: s.unlink(missing_ok=True)
        except OSError as e:
            log.warning("не удалось удалить журнал %s: %s", s, e)


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_session(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _integrity_ok(db_path) -> tuple[bool, str]:
    c = sqlite3.connect(str(db_path))
    try:
        msg = c.execute("PRAGMA integrity_check").fetchone()[0]
        return msg == "ok", msg
    finally:
        c.close()


def _copy_db(src, dest) -> None:
    dest = Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists(): dest.unlink()
    s = sqlite3.connect(f"file:{Path(src).resolve().as_posix()}?mode=ro", uri=True)
    d = sqlite3.connect(str(dest))
    try: s.backup(d)
    finally:
        d.close(); s.close()


def _replace_with_retry(tmp: Path, dest: Path, bak: Path | None):
    """Атомарно подменить dest файлом tmp; прежняя версия — в bak (если dest существовал)."""
    last = None
    delay = 0.05
    for attempt in range(SAVE_RETRIES):
        try:
            _replace_once(tmp, dest, bak)
            return
        except PermissionError as e:
            last = e
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
    raise ProjectSaveError(f"Не удалось сохранить: файл занят другой программой: {dest}") from last


def _replace_once(tmp: Path, dest: Path, bak: Path | None):
    if os.name == "nt" and dest.exists() and bak is not None:
        import ctypes
        ok = ctypes.windll.kernel32.ReplaceFileW(str(dest), str(tmp), str(bak), 0, None, None)
        if ok:
            return
        err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
        # fallback to replace
        if err in (5, 32) or not dest.exists():
            raise PermissionError(err)
    if dest.exists() and bak is not None:
        if bak.exists(): bak.unlink()
        os.replace(dest, bak)
    os.replace(tmp, dest)


def cleanup_stale_temp_work(min_age_s: float = STALE_AGE_S) -> list[str]:
    """Удалить старые копии в %TEMP%/BadgeGenerator-work/ без живого pid (метаданные в имени не обязательны)."""
    out, root = [], Path(tempfile.gettempdir()) / WORK_TEMP_DIR
    try:
        if not root.is_dir(): return out
        now = time.time()
        for f in root.iterdir():
            try:
                if now - f.stat().st_mtime < min_age_s: continue
                if f.is_dir() and f.name.startswith("unsaved_"):
                    import shutil
                    shutil.rmtree(f, ignore_errors=True)
                    out.append(f.name)
                    continue
                if not f.is_file(): continue
                f.unlink(); out.append(f.name)
            except OSError as e:
                log.warning("не удалось удалить старую рабочую копию %s: %s", f, e)
    except Exception:
        log.exception("очистка BadgeGenerator-work")
    return out


def list_recoverable_sessions(search_dirs: list | None = None) -> list[dict]:
    """Сессии с мёртвым pid и существующей рабочей копией.
    Всегда просматривает и %TEMP%/BadgeGenerator-work/ (.bg-session рядом с рабочей копией,
    если каталог исходника недоступен на запись)."""
    dirs, seen, out = [], set(), []
    for d in (search_dirs or []):
        p = Path(d)
        dirs.append(p if p.is_dir() else p.parent)
    temp_root = Path(tempfile.gettempdir()) / WORK_TEMP_DIR
    if temp_root not in dirs:
        dirs.append(temp_root)
    for d in dirs:
        try: files = list(Path(d).glob("*.bg-session"))
        except OSError: continue
        for sp in files:
            info = _session_info(sp)
            if info and info["source_path"] not in seen:
                seen.add(info["source_path"]); out.append(info)
    return out


def _session_info(sp: Path) -> dict | None:
    data = _read_session(sp)
    if not data: return None
    src, work = Path(data.get("source_path") or ""), Path(data.get("work_path") or "")
    if _pid_alive(data.get("pid"), data.get("host")): return None
    if not work.is_file(): return None
    ok, _ = _integrity_ok(work)
    if not ok: return None
    return {"source_path": str(src), "work_path": str(work), "opened_at": data.get("opened_at"),
            "last_change_at": data.get("last_change_at"), "dirty": bool(data.get("dirty")),
            "pid": data.get("pid"), "host": data.get("host"), "session_path": str(sp)}


def recover(info_or_path, *, accept: bool) -> "ProjectSession":
    """accept=True — продолжить с рабочей копией (dirty=True); False — удалить её и открыть исходник."""
    if isinstance(info_or_path, dict):
        info = info_or_path
    else:
        p = Path(info_or_path)
        found = _find_session_file(p)
        info = (_session_info(found) if found else None) or _session_info(p)
        if info is None:
            return open_project(info_or_path if not str(info_or_path).endswith(".bg-session")
                                else Path(info_or_path).with_name(Path(info_or_path).name.removesuffix(".bg-session")))
    src = Path(info["source_path"])
    if accept:
        return ProjectSession._resume(src, Path(info["work_path"]), force_dirty=True)
    _discard_files(src, Path(info["work_path"]))
    return open_project(src)


def create_unsaved_project(name=None) -> "ProjectSession":
    """Пустой несохранённый проект (первое сохранение — save_as). name — имя файла без пути."""
    return ProjectSession._unsaved(name)


def triple_paths(dest) -> tuple[Path, Path, Path]:
    """Пути тройки (.csp, .csd, .db) для dest (.csp/.csd/.db/.sqlite или без суффикса).

    Суффикс .sqlite/.sqlite3 сохраняется у файла базы; .csp/.csd нормализуются к .db.
    """
    dest = Path(dest)
    suf = dest.suffix.lower()
    if suf in {".csp", ".csd"}:
        return dest.with_suffix(".csp"), dest.with_suffix(".csd"), dest.with_suffix(".db")
    if suf in {".db", ".sqlite", ".sqlite3"}:
        return dest.with_suffix(".csp"), dest.with_suffix(".csd"), dest
    return Path(str(dest) + ".csp"), Path(str(dest) + ".csd"), Path(str(dest) + ".db")


def _ensure_asset_dirs(base: Path) -> None:
    for sub in ("photos", "template_bg"):
        (base / sub).mkdir(parents=True, exist_ok=True)


def create_project(path) -> "ProjectSession":
    """Создать новый проект-тройку и открыть сессию (dirty=False).

    Пишет <stem>.csp + <stem>.csd + <stem>.db (суффикс .sqlite сохраняется),
    создаёт photos/ и template_bg/. Любой из трёх файлов уже есть → FileExistsError.
    """
    path = Path(path)
    csp, csd, db = triple_paths(path)
    for cand in (path, csp, csd, db):
        if cand.exists():
            raise FileExistsError(cand)
    db.parent.mkdir(parents=True, exist_ok=True)
    _ensure_asset_dirs(db.parent)
    created: list[Path] = []
    try:
        c = _db.connect(str(db)); c.close()
        created.append(db)
        _write_new_project_sidecars(db, csd, csp)
        created.extend((csd, csp))
    except Exception:
        for f in reversed(created):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return open_project(db)


def _write_new_project_sidecars(db: Path, csd: Path, csp: Path) -> None:
    from .smartid_write import (
        write_csd, write_csp, template_from_con, bundled_reference_csd,
    )
    con = _db.connect(str(db))
    try:
        tmpl = template_from_con(con, base_dir=db.parent)
        ref = bundled_reference_csd()
        write_csd(tmpl, csd, overwrite=False, reference_csd=ref, base_dir=db.parent)
        names = [f["name"] for f in (tmpl.get("fields") or [])]
        write_csp(csp, csd, db, overwrite=False, csd_fields=names, tbl_fields=names, template=tmpl)
    finally:
        con.close()


def open_project(path, *, recover: bool | None = None, create: bool = False) -> "ProjectSession":
    """Открыть проект. path=':memory:' — без файла.
    recover=None и нужна развилка → RecoverableProjectError.
    create=True — создать пустой проект-тройку, если файла нет.
    path с суффиксом .csp/.csd — свой .csp открывается из нашей .db,
    чужой .csp/.csd импортируется как несохранённый проект."""
    cleanup_stale_temp_work()
    if str(path) == ":memory:":
        return ProjectSession._memory()
    path = Path(path)
    if path.suffix.lower() in {".csp", ".csd"}:
        if not path.exists():
            if create:
                return create_project(path)
            raise FileNotFoundError(path)
        from .smartid import open_csd_or_csp
        session, _ = open_csd_or_csp(path, recover=recover)
        return session
    if str(path).endswith(".work"):
        path = Path(str(path)[:-5])  # project.db.work → project.db
    if not path.exists():
        if create: return create_project(path)
        raise FileNotFoundError(path)
    sp = _find_session_file(path)
    data = _read_session(sp) if sp and sp.is_file() else None
    if data:
        work = Path(data.get("work_path") or default_work_path(path))
        pid, host = data.get("pid"), data.get("host")
        if _pid_alive(pid, host):
            raise ProjectLockedError(path, pid, host)
        if work.is_file():
            ok, _ = _integrity_ok(work)
            if ok:
                info = {"source_path": str(path), "work_path": str(work), "opened_at": data.get("opened_at"),
                        "last_change_at": data.get("last_change_at"), "dirty": bool(data.get("dirty")),
                        "pid": pid, "host": host, "session_path": str(sp)}
                if recover is None:
                    raise RecoverableProjectError(info)
                return recover(info, accept=bool(recover))
        try: sp.unlink(missing_ok=True)
        except OSError: pass
        _remove_sidecars(work)
        try: work.unlink(missing_ok=True)
        except OSError: pass
    return ProjectSession._from_source(path)


def _discard_files(source: Path, work: Path | None):
    if work:
        _remove_sidecars(work)
        try: work.unlink(missing_ok=True)
        except OSError as e: log.warning("не удалось удалить рабочую копию %s: %s", work, e)
        try: _work_session_path(work).unlink(missing_ok=True)
        except OSError: pass
    try: session_path(source).unlink(missing_ok=True)
    except OSError: pass


class ProjectSession:
    """Сессия файлового проекта (или :memory:). con всегда на рабочую копию."""

    def __init__(self):
        self.source_path: Path | None = None
        self.work_path: Path | None = None
        self.base_dir: Path = Path.cwd()
        self.con: sqlite3.Connection | None = None
        self._clean_total_changes = 0
        self._force_dirty = False
        self._photos_at_open: set[str] = set()
        self.suggested_name: str | None = None
        self.import_source_paths: list[Path] = []
        self.csp_path: Path | None = None
        self.csd_path: Path | None = None
        self.last_save_dropped: list[str] = []
        self._owned_base_dir = False

    # ----- constructors -----
    @classmethod
    def _memory(cls) -> "ProjectSession":
        s = cls()
        s.con = _db.connect(":memory:")
        s.base_dir = Path.cwd()
        set_project_base_dir(s.con, s.base_dir)
        s._mark_clean()
        return s

    @classmethod
    def _unsaved(cls, name=None) -> "ProjectSession":
        """Пустой несохранённый проект: source_path нет, своя временная base_dir."""
        s = cls()
        s.con = _db.connect(":memory:")
        stem = Path(str(name)).stem if name else "проект"
        s.suggested_name = f"{stem}.db"
        root = Path(tempfile.gettempdir()) / WORK_TEMP_DIR
        root.mkdir(parents=True, exist_ok=True)
        s.base_dir = Path(tempfile.mkdtemp(prefix=f"unsaved_{stem}_", dir=str(root)))
        s._owned_base_dir = True
        set_project_base_dir(s.con, s.base_dir)
        s._mark_clean()
        return s

    @classmethod
    def _from_source(cls, source: Path) -> "ProjectSession":
        source = Path(source).resolve()
        s = cls()
        s.source_path = source
        s.base_dir = source.parent
        work = default_work_path(source)
        if should_use_temp_work(source.parent):
            work = _temp_work_path(source)
        _copy_db(source, work)
        _hide_windows(work)
        s.work_path = work
        s.con = _db.connect(str(work))
        try: s.con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error: pass
        set_project_base_dir(s.con, s.base_dir)
        s._photos_at_open = s._list_photos()
        s._attach_sidecars()
        s._write_session()
        _remove_sidecars(source)
        s._mark_clean()
        return s

    @classmethod
    def _resume(cls, source: Path, work: Path, *, force_dirty: bool) -> "ProjectSession":
        s = cls()
        s.source_path = Path(source).resolve()
        s.base_dir = s.source_path.parent
        s.work_path = Path(work)
        s.con = _db.connect(str(s.work_path))
        try: s.con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error: pass
        set_project_base_dir(s.con, s.base_dir)
        s._photos_at_open = s._list_photos()
        s._attach_sidecars()
        s._force_dirty = force_dirty
        s._clean_total_changes = s.con.total_changes
        s._write_session()
        return s

    def _list_photos(self) -> set[str]:
        d = self.base_dir / "photos"
        if not d.is_dir(): return set()
        try: return {f.name for f in d.iterdir() if f.is_file()}
        except OSError: return set()

    def _mark_clean(self):
        self._force_dirty = False
        self._clean_total_changes = self.con.total_changes

    def _session_data(self) -> dict:
        st = self.source_path.stat() if self.source_path and self.source_path.exists() else None
        return {"format_version": SESSION_FMT,
                "source_path": str(self.source_path) if self.source_path else "",
                "source_mtime_ns": getattr(st, "st_mtime_ns", 0) if st else 0,
                "source_size": st.st_size if st else 0,
                "work_path": str(self.work_path) if self.work_path else "",
                "base_dir": str(self.base_dir),
                "pid": os.getpid(), "host": _host(),
                "opened_at": _db.now_iso(), "last_change_at": _db.now_iso(),
                "dirty": self.is_dirty()}

    def _write_session(self):
        if not self.source_path: return
        data = self._session_data()
        dest = session_path(self.source_path)
        try:
            _write_json_atomic(dest, data)
            return
        except OSError:
            if self.work_path is None:
                raise
            alt = _work_session_path(self.work_path)
            alt.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(alt, data)

    def is_dirty(self) -> bool:
        if self.con is None: return False
        return self._force_dirty or self.con.total_changes != self._clean_total_changes

    def _require_no_template_draft(self, commit_template: bool):
        from .templates import get_template_edit_state, commit_template_edit
        if get_template_edit_state(self.con) is None:
            return
        if not commit_template:
            raise TemplateEditActiveError("сначала сохраните или отмените правки шаблона")
        commit_template_edit(self.con)

    def save(self, *, commit_template: bool = False) -> dict:
        if self.source_path is None:
            raise ValueError("нет файла проекта — используйте save_as")
        self._require_no_template_draft(commit_template)
        r = self._write_source(self.source_path, overwrite=True)
        r.update(self._write_companions(self.source_path, overwrite=True, required=False))
        return r

    def save_as(self, dest_path, *, overwrite: bool = False, commit_template: bool = False) -> dict:
        self._require_no_template_draft(commit_template)
        dest_in = Path(dest_path)
        _csp, _csd, dest = triple_paths(dest_in)
        for cand in (dest_in, dest, _csp, _csd):
            blocked = self._protected_save_target(cand)
            if blocked is not None:
                raise ValueError(
                    "нельзя сохранить проект поверх исходного файла Smart ID Designer "
                    f"(.csp, .csd или его базы данных):\n{blocked}"
                )
        if self.work_path and dest.exists() and _same_path(dest, self.work_path):
            raise ValueError("нельзя сохранить поверх рабочей копии")
        if self.source_path and (
            (dest_in.exists() and _same_path(dest_in, self.source_path))
            or (dest.exists() and _same_path(dest, self.source_path))
        ):
            return self.save(commit_template=False)  # draft already committed if requested
        exists = dest_in.exists() or dest.exists()
        if exists and not overwrite:
            raise FileExistsError(dest_in if dest_in.exists() else dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        _ensure_asset_dirs(dest.parent)
        old_source, old_work, old_base = self.source_path, self.work_path, self.base_dir
        old_owned = self._owned_base_dir
        r = self._write_source(dest, overwrite=overwrite or not dest.exists())
        r.update(self._write_companions(dest, overwrite=True, required=True))
        # переключить сессию на новый исходник (.db)
        if old_source is None or old_source.parent.resolve() != dest.parent.resolve():
            self._copy_asset_trees(old_base, dest.parent)
        if old_source and old_work:
            if not _same_path(old_source, dest):
                _discard_files(old_source, old_work)
        self.source_path = dest.resolve()
        self.base_dir = self.source_path.parent
        self._owned_base_dir = False
        work = default_work_path(self.source_path)
        if should_use_temp_work(self.base_dir):
            work = _temp_work_path(self.source_path)
        if old_work is None or work != old_work:
            if self.con: self.con.close()
            _copy_db(dest, work)
            _hide_windows(work)
            self.work_path = work
            self.con = _db.connect(str(work))
            try: self.con.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error: pass
        set_project_base_dir(self.con, self.base_dir)
        self._photos_at_open = self._list_photos()
        self._attach_sidecars()
        self._write_session()
        self._mark_clean()
        if old_owned and old_base.resolve() != self.base_dir.resolve():
            self._rm_owned_base_dir(old_base)
        r["path"] = self.source_path
        return r

    def _protected_save_target(self, dest: Path) -> Path | None:
        """Если dest совпадает с исходником импорта Smart ID — вернуть этот путь."""
        for raw in self.import_source_paths or []:
            if raw is None:
                continue
            src = Path(raw)
            try:
                if _same_path(dest, src):
                    return src.resolve() if src.exists() else src
            except OSError:
                if os.path.normcase(os.path.realpath(dest)) == os.path.normcase(os.path.realpath(src)):
                    return src
        return None

    def _attach_sidecars(self) -> None:
        """Если рядом с нашей .db есть свой .csp — запомнить пути тройки."""
        if not self.source_path:
            return
        from .smartid import detect_own_csp_db, parse_csp, resolve_csp_csd
        csp = self.source_path.with_suffix(".csp")
        if not csp.is_file():
            return
        own = detect_own_csp_db(csp)
        if own is None:
            return
        try:
            if not _same_path(own, self.source_path):
                return
        except OSError:
            return
        self.csp_path = csp.resolve()
        try:
            self.csd_path = resolve_csp_csd(parse_csp(csp)).resolve()
        except (FileNotFoundError, OSError, ValueError):
            csd = self.source_path.with_suffix(".csd")
            self.csd_path = csd.resolve() if csd.is_file() else csd

    def _has_triple(self) -> bool:
        """True, если сессия уже привязана к своему .csp (не любой файл рядом)."""
        return bool(self.csp_path and self.csd_path)

    def _import_source_csd(self):
        """Исходный .csd импорта Smart ID (из import_source_paths), если есть."""
        from .smartid import parse_csp, resolve_csp_csd
        for raw in self.import_source_paths or []:
            if raw is None:
                continue
            q = Path(raw)
            try:
                if q.is_file() and q.suffix.lower() == ".csd":
                    return q
            except OSError:
                continue
        for raw in self.import_source_paths or []:
            if raw is None:
                continue
            q = Path(raw)
            try:
                if not (q.is_file() and q.suffix.lower() == ".csp"):
                    continue
            except OSError:
                continue
            try:
                csd = resolve_csp_csd(parse_csp(q))
            except (FileNotFoundError, OSError, ValueError):
                continue
            if csd.is_file():
                return csd
        return None

    def _own_csd_file(self):
        """Существующий .csd этого проекта (после создания или Save As)."""
        if self.csd_path:
            p = Path(self.csd_path)
            if p.is_file():
                return p
        if self.source_path:
            p = Path(self.source_path).with_suffix(".csd")
            if p.is_file():
                return p
        return None

    def _reference_csd(self):
        """Эталон для write_csd: (a) исходный .csd импорта — только пока сессия
        несохранена; (b) свой уже записанный .csd; (c) встроенный ресурс."""
        from .smartid_write import bundled_reference_csd
        if self.source_path is None:
            src = self._import_source_csd()
            if src is not None:
                return src
        own = self._own_csd_file()
        if own is not None:
            return own
        return bundled_reference_csd()

    def _write_companions(self, dest_db: Path, *, overwrite: bool, required: bool) -> dict:
        """Записать .csd/.csp рядом с dest_db.

        required=False: для Save старого .db-проекта (нет тройки) — ничего не писать.
        required=True: «Сохранить как» всегда пишет тройку.
        Возвращает {"dropped": [...], "csd_path", "csp_path", "db_path"?}.
        """
        dest_db = Path(dest_db)
        if not required and not self._has_triple():
            self.last_save_dropped = []
            return {"dropped": []}
        csp, csd, db = triple_paths(dest_db)
        if self.csp_path and self.csd_path and not required:
            try:
                if _same_path(dest_db, self.source_path):
                    csp, csd = Path(self.csp_path), Path(self.csd_path)
            except OSError:
                pass
        for cand in (csp, csd, db):
            blocked = self._protected_save_target(cand)
            if blocked is not None:
                raise ValueError(
                    "нельзя сохранить проект поверх исходного файла Smart ID Designer "
                    f"(.csp, .csd или его базы данных):\n{blocked}"
                )
        from .smartid_write import (
            write_csd, write_csp, template_from_con, SmartIdSourceProtectedError,
        )
        tmpl = template_from_con(
            self.con, base_dir=self.base_dir,
            import_source_paths=self.import_source_paths,
        )
        logical_ref = self._reference_csd()
        ref_tmp = None
        try:
            ref = logical_ref
            # (b) свой .csd = и эталон, и назначение: сначала снимок в память/temp,
            # затем write_csd атомарно перезаписывает назначение (temp + os.replace).
            if (logical_ref is not None and Path(csd).exists()
                    and _same_path(logical_ref, csd)):
                blob = Path(logical_ref).read_bytes()
                fd, tmp_name = tempfile.mkstemp(
                    prefix=Path(csd).name + ".", suffix=".ref.csd",
                    dir=str(Path(csd).parent),
                )
                os.close(fd)
                ref_tmp = Path(tmp_name)
                ref_tmp.write_bytes(blob)
                ref = ref_tmp
            wr = write_csd(
                tmpl, csd, overwrite=overwrite,
                import_source_paths=self.import_source_paths,
                base_dir=self.base_dir, reference_csd=ref,
            )
            names = [f["name"] for f in (tmpl.get("fields") or [])]
            wr2 = write_csp(
                csp, csd, dest_db, overwrite=overwrite,
                import_source_paths=self.import_source_paths,
                csd_fields=names, tbl_fields=names, template=tmpl,
            )
        except SmartIdSourceProtectedError as e:
            raise ValueError(
                "нельзя сохранить проект поверх исходного файла Smart ID Designer "
                f"(.csp, .csd или его базы данных):\n{e}"
            ) from e
        finally:
            if ref_tmp is not None:
                try:
                    ref_tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        dropped = list(wr.get("dropped") or []) + list(wr2.get("dropped") or [])
        self.csp_path = Path(wr2["path"]).resolve() if wr2.get("path") else csp.resolve()
        self.csd_path = Path(wr["path"]).resolve() if wr.get("path") else csd.resolve()
        self.last_save_dropped = dropped
        return {
            "dropped": dropped,
            "csd_path": self.csd_path,
            "csp_path": self.csp_path,
            "db_path": dest_db,
            "reference_csd": logical_ref,
        }

    def _rm_owned_base_dir(self, path: Path | None) -> None:
        if not path:
            return
        import shutil
        try:
            shutil.rmtree(path, ignore_errors=True)
        except OSError as e:
            log.warning("не удалось удалить временный каталог проекта %s: %s", path, e)

    def _copy_asset_trees(self, old_base: Path, new_base: Path):
        if old_base.resolve() == new_base.resolve(): return
        import shutil
        for sub in ("photos", "template_bg"):
            src, dst = old_base / sub, new_base / sub
            if not src.is_dir(): continue
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file() and not (dst / f.name).exists():
                    shutil.copy2(f, dst / f.name)

    def _write_source(self, dest: Path, *, overwrite: bool) -> dict:
        dest = Path(dest)
        if self.con.in_transaction: self.con.commit()
        try: self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error: pass
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=str(dest.parent))
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            b = sqlite3.connect(str(tmp))
            try: self.con.backup(b)
            finally: b.close()
            ok, msg = _integrity_ok(tmp)
            if not ok:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"integrity_check: {msg}")
            bak = bak_path(dest) if dest.exists() else None
            _replace_with_retry(tmp, dest, bak)
            _remove_sidecars(dest)
            self._mark_clean()
            self._write_session()
            return {"path": dest, "bak_path": bak if bak and bak.exists() else None, "integrity": "ok"}
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def restore_from(self, backup_path) -> None:
        """Восстановить содержимое только в рабочую копию; исходник не трогать, dirty=True."""
        from ..api import restore_db
        if self.work_path is None:
            raise ValueError("восстановление из .bak доступно только для файлового проекта")
        if self.con: self.con.close()
        restore_db(self.work_path, backup_path)
        self.con = _db.connect(str(self.work_path))
        try: self.con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error: pass
        set_project_base_dir(self.con, self.base_dir)
        self._force_dirty = True
        self._clean_total_changes = self.con.total_changes
        self._write_session()

    def discard(self) -> None:
        """Закрыть, удалить рабочую копию и сессию; исходник не трогать."""
        self._cleanup_session_photos()
        if self.con:
            set_project_base_dir(self.con, None)
            try: self.con.close()
            except sqlite3.Error: pass
            self.con = None
        if self.source_path:
            _discard_files(self.source_path, self.work_path)
        self.work_path = None
        if self._owned_base_dir:
            self._rm_owned_base_dir(self.base_dir)
            self._owned_base_dir = False

    def close(self, *, save: bool | None = None, commit_template: bool = False) -> None:
        """save=True — записать и закрыть; save=False — discard;
        save=None и dirty → UnsavedChangesError; save=None и не dirty — закрыть без вопроса."""
        if save is True:
            if self.source_path is None:
                raise ValueError("нет файла проекта — используйте save_as")
            self.save(commit_template=commit_template)
            self.discard()
            return
        if save is False:
            self.discard()
            return
        if self.is_dirty():
            raise UnsavedChangesError("есть несохранённые изменения")
        self.discard()

    def _source_referenced_files(self) -> set[str]:
        """Имена файлов в photos/, на которые ссылается ИСХОДНИК (не рабочая копия)."""
        names = set()
        if not self.source_path or not self.source_path.is_file(): return names
        c = sqlite3.connect(f"file:{self.source_path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            try:
                for (pp,) in c.execute("SELECT photo_path FROM persons WHERE COALESCE(photo_path,'')<>''"):
                    names.add(Path(pp).name)
            except sqlite3.Error:
                pass
            try:
                for (fj,) in c.execute("SELECT fields_json FROM persons"):
                    try: d = json.loads(fj or "{}")
                    except (TypeError, ValueError): continue
                    for v in d.values():
                        if isinstance(v, str) and v: names.add(Path(v).name)
            except sqlite3.Error:
                pass
        finally:
            c.close()
        return names

    def _cleanup_session_photos(self):
        d = self.base_dir / "photos"
        if not d.is_dir() or self.source_path is None: return
        keep = self._source_referenced_files() | self._photos_at_open
        try:
            for f in d.iterdir():
                if f.is_file() and f.name not in keep:
                    try: f.unlink()
                    except OSError: pass
        except OSError:
            pass
