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
        T.section("Motor / CAN")
        with dpg.group(horizontal=True):
            self.tags["mid"] = dpg.add_input_int(label="motor CAN id", default_value=2, width=100)
            dpg.bind_item_theme(self.tags["mid"], T.theme("input")); T.bind_font(self.tags["mid"], "mono")
            b = T.action("Set id", "neutral", safe(lambda: self.c.set_motor_id(dpg.get_value(self.tags["mid"]))), 80)
            g.bind(b, "can_scan", "Only in REST.")
            b = T.action("Scan bus (1-127)", "neutral", safe(self.c.can_scan), 150)
            g.bind(b, "can_scan", "Pings every id with a zero-torque frame (~1 s, REST only).")
            self.tags["scan"] = T.mono_text("", color=T.DIM)
        dpg.add_spacer(height=10)
        T.section("Web hub  -  browser UI, phones, planner")
        with dpg.group(horizontal=True):
            self.tags["srv"] = T.toggle("run hub", s.server_enabled, safe(self._server))
            self.tags["port"] = dpg.add_input_int(label="port", default_value=s.server_port, width=100)
            dpg.bind_item_theme(self.tags["port"], T.theme("input")); T.bind_font(self.tags["port"], "mono")
            self.tags["srv_status"] = T.mono_text("", color=T.DIM)
        T.toggle("allow remote control (planner setpoint stream, enable/zero from clients)",
                 s.allow_remote_control, safe(self._pref("allow_remote_control")))
        h = dpg.add_text("Open in a browser (laptop) or on the phone (same Wi-Fi):", color=T.DIM); T.bind_font(h, "small")
        self.tags["url"] = T.mono_text(f"http://{_lan_ip()}:{s.server_port}/", bold=True)
        dpg.add_spacer(height=10)
        T.section("Data")
        T.mono_text(f"folder: {self.app.root.resolve()}", wrap=900, color=T.DIM)
        with dpg.group(horizontal=True):
            T.action("Rebuild catalog from disk", "neutral", safe(self._reindex), 220)
            T.action("Open logs folder", "ghost", safe(self._open_logs), 160)
        dpg.add_spacer(height=10)
        T.section("UI")
        T.toggle("auto-connect to last port on start", s.auto_connect, safe(self._pref("auto_connect")))
        T.toggle("show synthetic generators expanded", s.show_generators, safe(self._pref("show_generators")))

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
