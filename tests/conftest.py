import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.app_context import AppContext  # noqa: E402


@pytest.fixture
def ctx(tmp_path):
    kb = tmp_path / "kb"
    shutil.copytree(ROOT / "knowledge_base", kb)
    c = AppContext(data_dir=tmp_path / "data", kb_dir=kb, defaults_dir=ROOT / "knowledge_base" / "defaults")
    yield c
    c.close()
