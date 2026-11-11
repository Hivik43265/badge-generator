import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pytest
from badge_backend import api, demo

@pytest.fixture(autouse=True)
def _bg_app_root(tmp_path_factory, monkeypatch):
    """Замечание №1: папки программы (work/import/logs/projects) — во временном BG_APP_ROOT, не в репозитории."""
    monkeypatch.setenv("BG_APP_ROOT", str(tmp_path_factory.mktemp("bg_app_root")))

@pytest.fixture
def con(): return api.connect()

@pytest.fixture
def demo_db(tmp_path):
    c = api.connect(); demo.make_photo(tmp_path / "p.jpg"); demo.make_logo(tmp_path / "demo_logo.png")
    demo.build_demo(c)
    ids = [api.create_person(c, {"last_name": "Иванов", "first_name": "Иван", "middle_name": "Иванович",
                                 "position": "Инженер", "employee_id": "000001"}, "p.jpg", print_mark=1),
           api.create_person(c, {"last_name": "Петрова", "first_name": "Анна", "employee_id": "000002"}, "nope.jpg", print_mark=1),
           api.create_person(c, {"last_name": "Сидоров", "first_name": "Олег"}, None, print_mark=0)]
    return c, ids, tmp_path
