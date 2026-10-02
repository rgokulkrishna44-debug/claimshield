"""Builds the free web version into docs/ for GitHub Pages.

The page is the same static/index.html the server uses. On Pages there is no /api, so the app
runs fully on the phone: rule engine, reading files, letters. Run: python scripts/build_pages.py
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "static", ROOT / "docs"

if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "static").mkdir(parents=True)
shutil.copy(SRC / "index.html", OUT / "index.html")
for f in SRC.iterdir():
    if f.suffix in {".js", ".css", ".json"}:
        shutil.copy(f, OUT / "static" / f.name)
(OUT / ".nojekyll").write_text("")
print("built", sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file()))
