"""Перегенерировать tests/golden/*.png (запускать осознанно, после проверки глазами)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from badge_backend import api, demo
d = Path(tempfile.mkdtemp()); c = api.connect()
demo.make_photo(d / "p.jpg"); demo.make_logo(d / "demo_logo.png"); demo.build_demo(c)
a = api.create_person(c, {"last_name": "Иванов", "first_name": "Иван", "middle_name": "Иванович",
                          "position": "Инженер", "employee_id": "000001"}, "p.jpg", print_mark=1)
b = api.create_person(c, {"last_name": "Петрова", "first_name": "Анна", "employee_id": "000002"}, "nope.jpg", print_mark=1)
out = Path(__file__).parent / "golden"; out.mkdir(exist_ok=True)
for name, (pid, s) in {"front_full": (a, "front"), "front_no_photo": (b, "front"), "back": (a, "back")}.items():
    api.render_card_db(c, pid, s, base_dir=d).save(out / f"{name}.png", dpi=(300, 300)); print(out / f"{name}.png")

# этап 10: barcode_*, qr_*, line_*
import warnings
from badge_backend.render import render_card
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tests_golden_cases import CASES
# python tests/make_golden.py [name ...]  — без аргументов все кейсы
wanted = set(sys.argv[1:])
for name, args in CASES.items():
    if wanted and name not in wanted:
        continue
    with warnings.catch_warnings():
        warnings.simplefilter("ignore"); render_card(*args).save(out / f"{name}.png", dpi=(300, 300))
    print(out / f"{name}.png")
