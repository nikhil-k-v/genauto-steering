"""
core/app.py — composition root.  Builds every service once, owns the
housekeeping thread, and guarantees shutdown always rests the motor.

    app = App(root)            # data folder
    app.start(transport)       # or app.connect_auto()
    ...                        # UI / server use app.controller, app.bus, ...
    app.shutdown()
"""
from __future__ import annotations

import atexit
import logging
import logging.handlers
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .. import protocol as P
from ..bus import Bus
from ..data.recorder import Recorder
from ..data.store import Store
from ..health.evaluator import HealthEvaluator, HealthLogger
from ..link import Link, SerialTransport, Transport, guess_port
from .controller import Controller
from .settings import Settings

log = logging.getLogger(__name__)


def setup_logging(log_dir: Path, level=logging.INFO):
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)-10s %(name)s: %(message)s")
    fh = logging.handlers.TimedRotatingFileHandler(log_dir / "app.log", when="midnight", backupCount=30)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)


class App:
    HOUSEKEEPING_HZ = 10

    def __init__(self, data_root: Path, settings: Optional[Settings] = None):
        self.root = Path(data_root)
        setup_logging(self.root / "logs")
        self.settings = settings or Settings.load(self.root / "settings.json")
        self.bus = Bus()
        self.store = Store(self.root)
        self.recorder = Recorder(self.bus, self.store)
        self.link = Link(self.bus)
        self.evaluator = HealthEvaluator(self.bus, HealthLogger(self.root / "logs"))
        self.controller = Controller(self.bus, self.link, self.store, self.recorder,
                                     collection_getter=lambda: self.settings.collection)
        self.server = None                       # steering.server.hub.Hub when enabled
        self._stop = threading.Event()
        self._hk = threading.Thread(target=self._housekeeping, name="housekeep", daemon=True)
        self._shutdown_done = False
        atexit.register(self.shutdown)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: (self.shutdown(), sys.exit(0)))
            except Exception:
                pass
        self.evaluator.store_status = {"ok": self.store.ok, "error": self.store.error}
        log.info("app start; data root %s", self.root)

    # ---- connections ------------------------------------------------------------------
    def start(self, transport: Optional[Transport] = None):
        if not self._hk.is_alive():
            self._hk.start()
        if transport is not None:
            self.link.connect(transport)
        self.link.start()

    def connect_port(self, port: str):
        self.settings.last_port = port
        self.settings.save()
        self.link.connect(SerialTransport(port))

    def connect_auto(self) -> Optional[str]:
        port = self.settings.last_port or guess_port()
        if port:
            self.connect_port(port)
        return port

    def start_server(self):
        if self.server is None:
            from ..server.hub import Hub
            self.server = Hub(self, port=self.settings.server_port)
        self.server.start()

    def stop_server(self):
        if self.server:
            self.server.stop()

    # ---- housekeeping --------------------------------------------------------------------
    def _housekeeping(self):
        period = 1.0 / self.HOUSEKEEPING_HZ
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self.evaluator.recorder_status = self.recorder.status
                self.evaluator.store_status = {"ok": self.store.ok, "error": self.store.error}
                if self.server:
                    self.evaluator.server_status = self.server.status
                    self.evaluator.phone_status = self.server.phone_status
                tree = self.evaluator.evaluate()
                self.link.set_pc_health_bits(tree.pc_bits_for_heartbeat())
                self.link.set_heartbeat_flags(recording=self.recorder.active,
                                              server_up=bool(self.server and self.server.status["running"]),
                                              phone=bool(self.server and self.server.phone_status["capturing"]),
                                              ui_alive=self.evaluator.ui_alive())
                self.controller.tick()
            except Exception:
                log.exception("housekeeping tick failed")
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    # ---- shutdown --------------------------------------------------------------------------
    def shutdown(self):
        if self._shutdown_done:
            return
        self._shutdown_done = True
        log.info("shutdown")
        try:
            self.controller.stop_all()
        except Exception:
            log.exception("stop_all failed")
        try:
            self.link.stop(send_rest=True)
        except Exception:
            log.exception("link stop failed")
        self._stop.set()
        if self.server:
            try:
                self.server.stop()
            except Exception:
                pass
        self.settings.save()
        try:
            self.evaluator.logger.close()
        except Exception:
            pass
        self.store.close()
