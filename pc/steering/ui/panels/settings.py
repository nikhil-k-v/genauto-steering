"""Settings - motor id and CAN scan, web hub (and how other devices reach it), data folder, preferences.

    ┌ Motor ─────────────┐   ┌ Web hub ───────────────────────────────────────────┐
    │ CAN id [2] [Use]   │   │ ☑ Run the web hub   port [8765]   running, 1 browser│
    │ [Scan the CAN bus] │   │ On this laptop   http://localhost:8765/   [Open]    │
    ├ Data ──────────────┤   │ On the Wi-Fi     http://192.168.1.42:8765/          │
    │ /path/to/data      │   │ By name          http://genauto.local:8765/         │
    │ [Rebuild catalog]  │   │ Bookmark         https://…github.io/…/?hub=…   [QR] │
    ├ Preferences ───────┤   │ ☐ Allow remote control                              │
    └────────────────────┘   └─────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import webbrowser

import dearpygui.dearpygui as dpg

from ...server.net import hub_urls, qr_matrix
from ...words import can_scan_line
from .. import theme as T
from ..safe import safe, toast

LEFT_W = 380
QR_PX = 156


class SettingsPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}
        self._qr_text = None
        self._mid_seen = None

    def build(self):
        g = self.ui.gate
        s = self.app.settings
        with dpg.group(horizontal=True, horizontal_spacing=40):
            with dpg.child_window(width=LEFT_W, border=False, tag="set_left") as lc:
                dpg.bind_item_theme(lc, T.theme("bare"))
                T.heading("Motor")
                with dpg.group(horizontal=True):
                    T.label("CAN id")
                    self.tags["mid"] = dpg.add_input_int(default_value=2, width=80, step=0)
                    T.tip(self.tags["mid"], "The motor's CAN id (1-127). Factory default on this build is 2. "
                                            "Shows the id the Teensy is using once it is connected.")
                    b = T.action("Use this id", "secondary", safe(lambda: self.c.set_motor_id(dpg.get_value(self.tags["mid"]))))
                    g.bind(b, "can_scan", "Tell the Teensy which CAN id to command. Only while the motor is off. "
                                          "It does not reprogram the motor (that needs the motor's own debug port).")
                b = T.action("Scan the CAN bus for motors", "secondary", safe(lambda: self.c.can_scan()), LEFT_W - 4)
                g.bind(b, "can_scan", "Ping ids 1 to 127 with a zero-torque frame and list the ones that answer. "
                                      "Takes about a third of a second; only while the motor is off.")
                self.tags["scan"] = T.label("", wrap=LEFT_W - 6)

                T.gap(22)
                T.heading("Data")
                p = T.mono_text(str(self.app.root.resolve()), T.MUTED, wrap=LEFT_W - 6)
                T.tip(p, "Recordings, logs, settings and the catalog live here.")
                with dpg.group(horizontal=True):
                    T.action("Rebuild catalog from disk", "secondary", safe(self._reindex),
                             tip_text="Re-read every recording folder and rebuild the library index. Brings back "
                                      "hidden recordings and fixes a catalog left broken by a crash.")
                    T.action("Open logs folder", "quiet", safe(self._open_logs),
                             tip_text="Health transitions, the app log and tracebacks.")

                T.gap(22)
                T.heading("Preferences")
                T.toggle("Connect to the last port on start", s.auto_connect, safe(self._pref("auto_connect")),
                         tip_text="When the app starts, open the serial port used last time.")
                T.toggle("Show the waveforms section open", s.show_generators, safe(self._pref("show_generators")),
                         tip_text="Open the Waveforms section on the Tune page by default.")

            with dpg.child_window(border=False, tag="set_right") as rc:
                dpg.bind_item_theme(rc, T.theme("bare"))
                T.heading("Web hub")
                with dpg.group(horizontal=True):
                    self.tags["srv"] = T.toggle("Run the web hub", s.server_enabled, safe(self._server), tip_text=(
                        "Serve the browser pages (system check, recordings, docs) to any device on this Wi-Fi, "
                        "plus phone video/IMU capture and the planner input. It never sits between this app "
                        "and the Teensy."))
                    dpg.add_spacer(width=12)
                    T.label("port")
                    self.tags["port"] = dpg.add_input_int(default_value=s.server_port, width=80, step=0)
                    T.tip(self.tags["port"], "TCP port for the hub. Change it while the hub is off.")
                    self.tags["srv_status"] = T.label("")
                T.gap(4)
                with dpg.group(horizontal=True, horizontal_spacing=24):
                    with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, borders_innerH=False,
                                   width=500) as tb:
                        dpg.bind_item_theme(tb, T.theme("compact"))
                        dpg.add_table_column(width_fixed=True, init_width_or_weight=100)
                        dpg.add_table_column(width_fixed=True, init_width_or_weight=390)
                        for key, lab, tip in (
                            ("local", "On this laptop", "Open in this computer's browser."),
                            ("lan", "On the Wi-Fi", "Type this on a phone or another computer on the same Wi-Fi."),
                            ("mdns", "By name", "Same, by name: stays valid when the laptop gets a new IP address. "
                                                "Needs the zeroconf package; some Android phones can't resolve .local names."),
                            ("pages", "Bookmark", "The GitHub Pages copy of these pages, pointed at this laptop. Bookmark "
                                                  "it once: docs work anywhere, and on this Wi-Fi it opens the laptop. "
                                                  "The QR code is this link."),
                        ):
                            with dpg.table_row():
                                l = T.label(lab)
                                T.tip(l, tip)
                                self.tags[f"u_{key}"] = dpg.add_input_text(default_value="", width=380, readonly=True)
                                T.tip(self.tags[f"u_{key}"], tip + " Select and copy with Ctrl+C.")
                    with dpg.group():
                        self.qr = dpg.add_drawlist(width=QR_PX, height=QR_PX, tag="set_qr")
                with dpg.group(horizontal=True):
                    T.action("Open in browser", "secondary", safe(self._open_local),
                             tip_text="Open the hub's pages in this computer's browser.")
                    T.action("Open bookmark link", "quiet", safe(self._open_pages),
                             tip_text="Open the GitHub Pages copy pointed at this laptop.")
                T.gap(8)
                T.toggle("Allow remote control", s.allow_remote_control, safe(self._remote), tip_text=(
                    "Let other devices send planner setpoints, turn on position control and set 0°. Off: they can "
                    "only watch, record, stop playback and turn the motor off. Every remote action passes the same "
                    "checks as a button here."))

    # ---- callbacks ----------------------------------------------------------------------------------
    def _pref(self, key):
        def f(sender, value):
            setattr(self.app.settings, key, value)
            self.app.settings.save()
        return f

    def _remote(self, sender, value):
        self.app.settings.allow_remote_control = bool(value)
        self.app.settings.save()
        if self.app.server:
            self.app.server.allow_remote_control = bool(value)

    def _server(self, sender, on):
        self.app.settings.server_enabled = on
        self.app.settings.server_port = dpg.get_value(self.tags["port"])
        self.app.settings.save()
        if on:
            self.app.start_server()
        else:
            self.app.stop_server()

    def _urls(self) -> dict:
        sv = self.app.server
        if sv is not None and sv.status.get("running"):
            return sv.urls()
        st = self.app.settings
        return hub_urls(st.server_port, st.pages_url, st.mdns_name, False)

    def _open_local(self):
        webbrowser.open(self._urls()["local"])

    def _open_pages(self):
        u = self._urls()
        webbrowser.open(u.get("pages_link") or u.get("pages") or u["local"])

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

    # ---- refresh ---------------------------------------------------------------------------------
    def on_resize(self, w, h):
        dpg.configure_item("set_left", height=h + 30)
        dpg.configure_item("set_right", width=max(400, w - LEFT_W - 40), height=h + 30)

    def refresh(self):
        lv = self.c.live
        cfg_id = lv.config.motor_id if lv.config else None
        dpg.set_value(self.tags["scan"], can_scan_line(lv.can_scan_status, lv.can_scan_ids, lv.can_scan_range, cfg_id))
        # show the id the Teensy really uses (once per change, so typing is not overwritten)
        if cfg_id is not None and cfg_id != self._mid_seen:
            self._mid_seen = cfg_id
            dpg.set_value(self.tags["mid"], cfg_id)

    def slow_refresh(self):
        sv = self.app.server
        running = bool(sv and sv.status["running"])
        if running:
            n = sv.status["clients"]
            txt = f"running, {n} browser" + ("" if n == 1 else "s")
        else:
            txt = f"failed: {sv.status['error']}" if sv and sv.status["error"] else "off"
        dpg.set_value(self.tags["srv_status"], txt)
        dpg.configure_item(self.tags["srv_status"], color=T.BAD if sv and sv.status.get("error") else T.MUTED)
        u = self._urls()
        mdns_err = sv.mdns.error if (sv and sv.mdns and not sv.mdns.ok) else ""
        vals = {"local": u["local"], "lan": "   ".join(u["lan"]) or "no network address",
                "mdns": u["mdns"] or (f"off ({mdns_err})" if mdns_err else "starts with the hub"),
                "pages": u.get("pages_link", "")}
        for k, v in vals.items():
            if dpg.get_value(self.tags[f"u_{k}"]) != v:
                dpg.set_value(self.tags[f"u_{k}"], v)
        self._draw_qr(u.get("pages_link") or (u["lan"][0] if u["lan"] else u["local"]))

    def _draw_qr(self, text: str):
        if text == self._qr_text:
            return
        self._qr_text = text
        dpg.delete_item(self.qr, children_only=True)
        m = qr_matrix(text)
        if m is None:
            dpg.draw_text((0, QR_PX / 2 - 10), "QR needs: pip install segno", color=T.MUTED, size=13, parent=self.qr)
            return
        n = len(m) + 4
        cell = QR_PX / n
        dpg.draw_rectangle((0, 0), (QR_PX, QR_PX), fill=T.SURFACE, color=T.RULE, parent=self.qr)
        for r, row in enumerate(m):
            for c, dark in enumerate(row):
                if dark:
                    x, y = (c + 2) * cell, (r + 2) * cell
                    dpg.draw_rectangle((x, y), (x + cell, y + cell), fill=T.INK, color=T.INK, parent=self.qr)
