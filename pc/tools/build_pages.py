"""
tools/build_pages.py - build the GitHub Pages copy of the web UI.

    python pc/tools/build_pages.py --out _site

The output is a static site: the same web/index.html the hub serves, its fonts,
the diagrams and screenshots, and every doc pre-rendered to JSON (api/docs.json,
api/docs/<ID>.json), so Docs work with no hub at all.  Live pages (System,
Recordings) connect to a hub from the page itself - see web/index.html
("connecting") and pc/steering/server/net.py.

Deployed by .github/workflows/pages.yml on every push to main.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from steering.server.hub import DOC_PAGES, Hub  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def build(out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    (out / "api" / "docs").mkdir(parents=True)
    shutil.copy(REPO / "web" / "index.html", out / "index.html")
    shutil.copytree(REPO / "web" / "fonts", out / "fonts")
    shutil.copytree(REPO / "docs" / "diagrams", out / "diagrams", ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    if (REPO / "docs" / "screenshots").is_dir():
        shutil.copytree(REPO / "docs" / "screenshots", out / "screenshots")
    docs = []
    for doc_id, title, path in DOC_PAGES:
        if not path.exists():
            continue
        docs.append({"id": doc_id, "title": title})
        html = Hub._markdown(path.read_text())
        (out / "api" / "docs" / f"{doc_id}.json").write_text(json.dumps({"id": doc_id, "title": title, "html": html}))
    (out / "api" / "docs.json").write_text(json.dumps({"docs": docs}))
    (out / ".nojekyll").write_text("")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site")
    a = ap.parse_args()
    out = build(Path(a.out))
    n = sum(1 for _ in out.rglob("*") if _.is_file())
    print(f"built {out} ({n} files)")


if __name__ == "__main__":
    main()
