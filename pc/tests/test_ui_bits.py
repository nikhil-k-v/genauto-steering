"""Pieces of the UI that don't need a window: dashed-line geometry and the GitHub Pages build."""
import json
import math
import sys
from pathlib import Path

import numpy as np

from steering.ui.lines import dash


def test_dash_cuts_in_screen_space():
    x = np.linspace(0, 10, 101)
    y = np.zeros_like(x)
    X, Y = dash(x, y, 10.0, 1.0, (8.0, 5.0))           # 100 px long, period 13 px -> 8 dashes
    gaps = int(np.isnan(X).sum())
    assert 7 <= gaps <= 8
    finite = X[np.isfinite(X)]
    assert finite.min() == 0 and abs(finite.max() - 10) < 0.5
    # a steep segment gets dashes too (length is measured in pixels, not in x)
    X2, Y2 = dash([0, 0.01], [0, 100], 1.0, 1.0, (8.0, 5.0))
    assert np.isnan(X2).sum() >= 6


def test_dash_keeps_existing_gaps_and_solid_passthrough():
    X, Y = dash([0, 1, math.nan, 2, 3], [0, 0, math.nan, 0, 0], 100.0, 1.0, (8.0, 5.0))
    assert np.isnan(X).any()
    X, Y = dash([0, 1, 2], [0, 1, 2], 1, 1, None)
    assert list(X) == [0, 1, 2]


def test_build_pages(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import build_pages
    out = build_pages.build(tmp_path / "site")
    idx = (out / "index.html").read_text()
    assert "PAGES" in idx and "url(/fonts" not in idx and 'src="/diagrams' not in idx    # relative paths only
    docs = json.loads((out / "api" / "docs.json").read_text())
    assert any(d["id"] == "HEALTH" for d in docs["docs"])
    h = json.loads((out / "api" / "docs" / "HEALTH.json").read_text())["html"]
    assert "<h1" in h and 'src="/diagrams' not in h
    assert (out / "fonts" / "DejaVuSans-plot.woff2").exists() and (out / ".nojekyll").exists()
