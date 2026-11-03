import sys, hashlib
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "testdata"))
import make_testsets

@pytest.fixture(scope="session")
def sets(tmp_path_factory):
    return make_testsets.make(tmp_path_factory.mktemp("sets"))

def tree_hash(d: Path):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}
