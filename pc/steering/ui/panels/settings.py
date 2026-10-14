"""Settings - motor id and CAN scan, web hub, data folder, preferences."""
from __future__ import annotations

import socket

import dearpygui.dearpygui as dpg

from .. import theme as T
from ..safe import safe, toast


def _lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class SettingsPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}

    def build(self):
        g = self.ui.gate
        s = self.app.settings
        T.heading("Motor", "Only while the motor is resting.")
        with dpg.group(horizontal=True):
            T.label("CAN id")
            self.tags["mid"] = dpg.add_input_int(default_value=2, width=90, step=0)
            b = T.action("Set id", "secondary", safe(lambda: self.c.set_motor_id(dpg.get_value(self.tags["mid"]))))
            g.bind(b, "can_scan")
            b = T.action("Scan the bus", "secondary", safe(self.c.can_scan))
            g.bind(b, "can_scan", "Pings ids 1 to 127 with a zero-torque frame. Takes about a second.")
            self.tags["scan"] = T.label("")

        T.gap(22)
        T.heading("Web hub", "Browser pages (system, recordings, docs), phone camera and IMU, and a planner input.")
        with dpg.group(horizontal=True):
            self.tags["srv"] = T.toggle("Run the hub", s.server_enabled, safe(self._server))
            dpg.add_spacer(width=12)
            T.label("port")
            self.tags["port"] = dpg.add_input_int(default_value=s.server_port, width=90, step=0)
            self.tags["srv_status"] = T.label("")
        self.tags["url"] = T.mono_text(f"http://{_lan_ip()}:{s.server_port}/")
        T.toggle("Allow remote control (planner setpoints, enable and zero from other devices)",
                 s.allow_remote_control, safe(self._pref("allow_remote_control")))

        T.gap(22)
        T.heading("Data")
        T.mono_text(str(self.app.root.resolve()), T.MUTED)
        with dpg.group(horizontal=True):
            T.action("Rebuild catalog from disk", "secondary", safe(self._reindex))
            T.action("Open logs folder", "quiet", safe(self._open_logs))

        T.gap(22)
        T.heading("Preferences")
        T.toggle("Connect to the last port on start", s.auto_connect, safe(self._pref("auto_connect")))
        T.toggle("Show test waveforms expanded", s.show_generators, safe(self._pref("show_generators")))

    def _pref(self, key):
        def f(sender, value):
            setattr(self.app.settings, key, value)
            self.app.settings.save()
        return f

    def _server(self, sender, on):
        self.app.settings.server_enabled = on
        self.app.settings.server_port = dpg.get_value(self.tags["port"])
        self.app.settings.save()
        if on:
            self.app.start_server()
        else:
            self.app.stop_server()
        dpg.set_value(self.tags["url"], f"http://{_lan_ip()}:{self.app.settings.server_port}/")

    def _reindex(self):
        n = self.app.store.reindex()
        toast(f"Catalog rebuilt: {n} recordings.")
        self.ui.panels["play"]._dirty = True

    def _open_logs(self):
        import os
        import subprocess
        import sys
        p = str(self.app.root / "logs")
        if sys.platform == "win32":
            os.startfile(p)              # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])

    def refresh(self):
        ids = self.c.live.can_scan_ids
        dpg.set_value(self.tags["scan"], ("Found ids " + ", ".join(str(i) for i in ids)) if ids else "")
        sv = self.app.server
        if sv and sv.status["running"]:
            n = sv.status["clients"]
            txt = f"Running, {n} client" + ("" if n == 1 else "s")
        else:
            txt = (sv.status["error"] if sv and sv.status["error"] else "Stopped")
        dpg.set_value(self.tags["srv_status"], txt)
