"""Repository hygiene: what a fresh clone needs is actually in git, and the example data opens.

The first test exists because a bare `data/` rule in .gitignore once hid the whole
`steering.data` package (store, recorder, analysis) from the repository, so a fresh
clone failed to install.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

PC = Path(__file__).resolve().parents[1]
REPO = PC.parent


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("git") is None or not (REPO / ".git").exists(), reason="not a git checkout")
def test_no_source_file_is_gitignored():
    sources = [p for p in (PC / "steering").rglob("*") if p.is_file() and "__pycache__" not in p.parts
               and p.suffix in (".py", ".ttf", ".json", ".html")]
    sources += [p for p in (REPO / "web").rglob("*") if p.is_file()]
    sources += [p for p in (REPO / "examples").rglob("*") if p.is_file()]
    ignored = _git("check-ignore", *[str(p) for p in sources]).stdout.split()
    assert not ignored, f"these files are ignored by .gitignore and would be missing from a clone: {ignored}"


def test_example_sim_data_opens(tmp_path):
    src = REPO / "examples" / "sim_data"
    if not src.exists():
        pytest.skip("examples/sim_data not generated")
    data = tmp_path / "sim_data"
    shutil.copytree(src, data)
    from steering.data.store import Store
    st = Store(data)                       # no catalog in the repo: the store rebuilds it from meta.json
    recs = st.list(include_playbacks=True)
    names = {r.name for r in recs}
    assert {"hand-left-right", "hand-left-right_pb01", "hand-left-right_pb02", "autocal", "step", "relay",
            "switch-opened"} <= names
    hand = next(r for r in recs if r.name == "hand-left-right")
    assert hand.pinned and len(st.playbacks_of(hand.uid)) == 2
    for r in recs:
        assert r.csv.exists() and r.samples > 0
