"""Renders every page to PNG (offscreen) for visual checks: python tools/screenshots.py OUTDIR [dark]"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.app_context import AppContext  # noqa: E402
from tools.demo_data import seed  # noqa: E402
from ui.main_window import MainWindow, NAV  # noqa: E402
from ui.theme import Theme  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
dark = len(sys.argv) > 2 and sys.argv[2] == "dark"
tmp = Path(tempfile.mkdtemp())
shutil.copytree(ROOT / "knowledge_base", tmp / "kb")
app = QApplication([])
ctx = AppContext(tmp / "data", tmp / "kb", ROOT / "knowledge_base" / "defaults")
seed(ctx)
Theme.apply("dark" if dark else "light")
w = MainWindow(ctx)
w.resize(1320, 840)
w.show()
from datetime import date, timedelta
d = date.today()
while d.weekday() > 4:
    d += timedelta(days=1)
w.pages[3].day = d
for i, (name, _, _) in enumerate(NAV):
    w.go(i)
    QTest.qWait(900)
    w.grab().save(str(out / f"{i}_{name.replace(' ', '_')}{'_dark' if dark else ''}.png"))
print("ok")
