"""Ядро badge_backend не зависит от data_tools: фолбэк-валидатор, warning, все строки импортируются."""
import ast, csv, os, shutil, subprocess, sys, textwrap
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "badge_backend"

def _write_csv(p, n=50):
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";"); w.writerow(["Фамилия", "Имя", "Примечание"])
        for i in range(n): w.writerow([f"Ёлкин{i}", "Пётр", f'"кавычки", ё {i}'])
    return p

def test_no_module_level_data_tools_import():
    """Статически: в ядре нет import data_tools на уровне модуля (только внутри функций)."""
    bad = []
    for f in PKG.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in tree.body:  # только верхний уровень модуля
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if any(n.split(".")[0] == "data_tools" for n in names): bad.append(f"{f.name}:{node.lineno}")
    assert bad == []

def test_import_core_does_not_load_data_tools():
    code = "import sys, badge_backend, badge_backend.api; print('data_tools' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"

def test_fallback_when_data_tools_blocked(monkeypatch, tmp_path, caplog):
    from badge_backend import api
    from badge_backend.services import importer
    for m in [m for m in sys.modules if m == "data_tools" or m.startswith("data_tools.")]:
        monkeypatch.delitem(sys.modules, m)
    monkeypatch.setitem(sys.modules, "data_tools", None)   # import data_tools → ImportError
    con = api.connect()
    with pytest.warns(RuntimeWarning, match="data_tools"):
        rep = api.import_file(con, _write_csv(tmp_path / "p.csv"))
    assert rep.validator == importer.FALLBACK_VALIDATOR == "builtin-fallback"
    assert (rep.added, rep.skipped) == (50, 0) and len(api.list_persons(con)) == 50
    assert "fallback" in caplog.text
    # фолбэк всё же ловит обязательные поля
    p = tmp_path / "bad.csv"; p.write_text("Фамилия;Имя\nИванов;\n;Пётр\nА;Б\n", encoding="utf-8")
    with pytest.warns(RuntimeWarning):
        r = api.import_file(api.connect(), p)
    assert (r.added, r.skipped) == (1, 2) and {e["code"] for e in r.errors} == {"REQUIRED_MISSING"}

def test_fallback_subprocess_clean_sys_path(tmp_path):
    """Чистое окружение: копия только badge_backend, data_tools физически отсутствует на sys.path."""
    shutil.copytree(PKG, tmp_path / "badge_backend", ignore=shutil.ignore_patterns("__pycache__"))
    csvp = _write_csv(tmp_path / "p.csv", 600)
    script = textwrap.dedent(f"""
        import sys, warnings
        sys.path = [p for p in sys.path if p not in ("", {str(ROOT)!r}) and not p.startswith({str(ROOT / 'data_tools')!r})]
        sys.path.insert(0, {str(tmp_path)!r})
        try:
            import data_tools; print("DATA_TOOLS_FOUND"); sys.exit(2)
        except ImportError: pass
        import badge_backend, badge_backend.api as api
        assert badge_backend.__file__.startswith({str(tmp_path)!r})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            rep = api.import_file(api.connect(), {str(csvp)!r})
        assert any("data_tools" in str(x.message) for x in w), [str(x.message) for x in w]
        print(rep.validator, rep.added, rep.skipped)
    """)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    out = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.split() == ["builtin-fallback", "600", "0"]
