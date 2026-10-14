"""
python -m steering <command>

  ui [--port P | --sim] [--data DIR] [--server]   launch the desktop UI (default)
  sim                                             run the fake Teensy as a pty-less sanity check
  server [--data DIR]                             headless: link + hub only (no UI)
  reindex [--data DIR]                            rebuild the recording catalog from meta.json files
  docs-health                                     print docs/HEALTH.md content from health/model.py
  flash                                           pio run -t upload for the Teensy
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _data_dir(args) -> Path:
    return Path(args.data or os.environ.get("STEERING_DATA") or (ROOT / "data"))


def cmd_ui(args):
    from .core.app import App
    from .ui.app import run
    app = App(_data_dir(args))
    if args.server:
        app.settings.server_enabled = True
    if args.port:
        app.settings.last_port = args.port
    run(app, sim=args.sim, auto_connect=not args.no_connect, frames=args.frames)


def cmd_server(args):
    from .core.app import App
    from .sim import SimTransport
    app = App(_data_dir(args))
    app.settings.server_enabled = True
    if args.sim:
        app.start(SimTransport())
    else:
        app.start()
        app.connect_auto()
    app.start_server()
    print(f"hub on port {app.settings.server_port}; Ctrl-C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()


def cmd_reindex(args):
    from .data.store import Store
    s = Store(_data_dir(args))
    print(f"{s.reindex()} recordings indexed")


def cmd_docs_health(args):
    from .health.model import GROUPS, NODES
    from .health.gating import ACTIONS, affected_actions
    out = ["# Health tree reference", "", "Generated from `pc/steering/health/model.py` — edit there.", ""]
    for g, gd in GROUPS.items():
        out += [f"## Group {g} — {gd.name}", "", f"*{gd.question}*", "",
                "| Node | OK means | When not OK | Fix | Blocks |", "|---|---|---|---|---|"]
        for n in NODES:
            if n.group != g:
                continue
            acts = affected_actions(n.id) or list(n.affects)
            blocks = ", ".join(ACTIONS[a][0] if a in ACTIONS else a for a in acts) or "—"
            out.append(f"| **{n.id}** {n.name} ({n.source}) | {n.ok_means} | {n.bad_means} | {n.fix} | {blocks} |")
        out.append("")
    print("\n".join(out))


def cmd_flash(args):
    folder = ROOT / "firmware" / "teensy"
    cmd = ["pio", "run", "-t", "upload"]
    print(" ".join(cmd), "in", folder)
    sys.exit(subprocess.call(cmd, cwd=folder))


def main(argv=None):
    p = argparse.ArgumentParser(prog="steering", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    u = sub.add_parser("ui"); u.add_argument("--port"); u.add_argument("--sim", action="store_true")
    u.add_argument("--data"); u.add_argument("--server", action="store_true"); u.add_argument("--no-connect", action="store_true")
    u.add_argument("--frames", type=int, help="headless smoke test: render N frames and exit")
    s = sub.add_parser("server"); s.add_argument("--data"); s.add_argument("--sim", action="store_true")
    r = sub.add_parser("reindex"); r.add_argument("--data")
    sub.add_parser("docs-health")
    sub.add_parser("flash")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    {"ui": cmd_ui, "server": cmd_server, "reindex": cmd_reindex, "docs-health": cmd_docs_health, "flash": cmd_flash,
     None: lambda a: cmd_ui(p.parse_args(["ui"] + (argv or sys.argv[1:])))}[args.cmd](args)


if __name__ == "__main__":
    main()
