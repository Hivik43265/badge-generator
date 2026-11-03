"""D50: --self-test даёт одинаковый полный результат с tests/fixtures/face_astronaut.jpg и без него (как в exe).
Без fixture — копия main.py/ui/badge_backend во временный каталог (fixture ищется от ui/__file__), реальный файл не трогается."""
import os, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RX = re.compile(r"ИТОГО: (\d+)/(\d+) PASS; исключений в слотах: (\d+)")


def _run(root, log):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    p = subprocess.run([sys.executable, str(root / "main.py"), "--self-test", "--log", str(log)], cwd=str(root),
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    text = log.read_text(encoding="utf-8") if log.is_file() else p.stdout + p.stderr
    m = RX.search(text)
    assert p.returncode == 0 and m, f"rc={p.returncode}\n{text[-3000:]}"
    passed, total, exc = map(int, m.groups())
    assert passed == total and exc == 0, text[-3000:]
    return passed, total


def test_selftest_same_with_and_without_fixture(tmp_path):
    assert (ROOT / "tests" / "fixtures" / "face_astronaut.jpg").is_file()
    normal = _run(ROOT, tmp_path / "with.log")
    copy = tmp_path / "repo"
    copy.mkdir()
    shutil.copy2(ROOT / "main.py", copy / "main.py")
    ign = shutil.ignore_patterns("__pycache__")
    for d in ("ui", "badge_backend", "data_tools"):
        if (ROOT / d).is_dir(): shutil.copytree(ROOT / d, copy / d, ignore=ign)
    assert not (copy / "tests" / "fixtures" / "face_astronaut.jpg").exists()
    without = _run(copy, tmp_path / "without.log")
    assert normal == without, (normal, without)
    assert (ROOT / "tests" / "fixtures" / "face_astronaut.jpg").is_file()
