"""core/settings.py — persisted user settings (JSON next to the data folder)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Settings:
    data_root: str = "data"
    last_port: str = ""
    collection: str = "default"
    auto_connect: bool = True
    server_enabled: bool = False
    server_port: int = 8765
    plot_seconds: float = 10.0
    auto_bounds: bool = True
    theme: str = "dark"
    gains: dict = field(default_factory=lambda: {"kp": 30.0, "kd": 2.0, "ki": 0.0, "tff": 0.0})
    show_generators: bool = False
    path: str = ""

    @classmethod
    def load(cls, path: Path) -> "Settings":
        s = cls()
        s.path = str(path)
        try:
            if path.exists():
                d = json.loads(path.read_text())
                for k, v in d.items():
                    if hasattr(s, k) and k != "path":
                        setattr(s, k, v)
        except Exception:
            log.exception("settings load failed; using defaults")
        return s

    def save(self):
        try:
            d = asdict(self)
            d.pop("path", None)
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.path).write_text(json.dumps(d, indent=2))
        except Exception:
            log.exception("settings save failed")
