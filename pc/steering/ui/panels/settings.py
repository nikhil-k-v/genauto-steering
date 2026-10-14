"""Settings tab - motor id / CAN scan, device hub, data folder, UI prefs."""
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
        dpg.add_text("MOTOR / CAN", color=T.ACCENT)
        with dpg.group(horizontal=True):
            self.tags["mid"] = dpg.add_input_int(label="motor CAN id", default_value=2, width=100)
            b = dpg.add_button(label="Set id", width=80, callback=safe(lambda: self.c.set_motor_id(dpg.get_value(self.tags["mid"]))))
            g.bind(b, "can_scan", "Only in REST.")
            b = dpg.add_button(label="Scan bus (1-127)", width=150, callback=safe(self.c.can_scan))
            g.bind(b, "can_scan", "Pings every id with a zero-torque frame (~1 s, REST only).")
            self.tags["scan"] = dpg.add_text("", color=T.DIM)
        dpg.add_spacer(height=10)
        dpg.add_text("DEVICE HUB (phones, other devices)", color=T.ACCENT)
        with dpg.group(horizontal=True):
            self.tags["srv"] = dpg.add_checkbox(label="run hub", default_value=s.server_enabled, callback=safe(self._server))
            self.tags["port"] = dpg.add_input_int(label="port", default_value=s.server_port, width=100)
            self.tags["srv_status"] = dpg.add_text("", color=T.DIM)
        dpg.add_text("On the phone (same Wi-Fi), open:", color=T.DIM)
        self.tags["url"] = dpg.add_text(f"http://{_lan_ip()}:{s.server_port}/")
        dpg.add_spacer(height=10)
        dpg.add_text("DATA", color=T.ACCENT)
        dpg.add_text(f"folder: {self.app.root.resolve()}", wrap=900)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Rebuild catalog from disk", width=220, callback=safe(self._reindex))
            dpg.add_button(label="Open logs folder", width=160, callback=safe(self._open_logs))
        dpg.add_spacer(height=10)
        dpg.add_text("UI", color=T.ACCENT)
        dpg.add_checkbox(label="auto-connect to last port on start", default_value=s.auto_connect, callback=safe(self._pref("auto_connect")))
        dpg.add_checkbox(label="show synthetic generators expanded", default_value=s.show_generators, callback=safe(self._pref("show_generators")))

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
        toast(f"catalog rebuilt: {n} recordings")
        self.ui.panels["play"]._dirty = True

    def _open_logs(self):
        import subprocess, sys, os
        p = str(self.app.root / "logs")
        if sys.platform == "win32":
            os.startfile(p)              # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])

    def refresh(self):
        ids = self.c.live.can_scan_ids
        dpg.set_value(self.tags["scan"], ("found ids: " + ", ".join(str(i) for i in ids)) if ids else "")
        sv = self.app.server
        dpg.set_value(self.tags["srv_status"], (f"running | {sv.status['clients']} client(s)" if sv and sv.status["running"] else (sv.status["error"] if sv and sv.status["error"] else "stopped")))
