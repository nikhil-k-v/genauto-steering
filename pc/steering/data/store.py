"""
data/store.py — where recordings live and how they are found.

Folder layout (docs/DATA.md) — two levels, no deeper:

    <data>/recordings/<collection>/<YYYY-MM-DD>/<HHMMSS>_<kind>_<name>/
        data.csv        samples (see recorder.CSV_COLUMNS)
        meta.json       who/what/when, gains, limits, metrics, health summary, parent link
        health.jsonl    health snapshots (1 Hz) + transitions during the recording
        events.jsonl    firmware events + PC actions during the recording
        video.mp4       optional (phone capture)
        imu.csv         optional (phone capture)

`collection` is user-defined ("drift-tests", "tuning", default "default");
the date folder is automatic.  The SQLite catalog is an index over these
folders: it can always be rebuilt from meta.json files (`Store.reindex()`),
so deleting it is safe.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

KINDS = ("manual", "trajectory", "playback", "test_step", "test_relay", "freespin", "calibration")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    collection TEXT NOT NULL DEFAULT 'default',
    parent_uid TEXT,
    path TEXT NOT NULL,
    created_at REAL NOT NULL,
    duration_s REAL DEFAULT 0,
    samples INTEGER DEFAULT 0,
    pinned INTEGER DEFAULT 0,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    metrics_json TEXT DEFAULT '{}',
    health_summary TEXT DEFAULT '',
    health_worst TEXT DEFAULT '',
    gains_json TEXT DEFAULT '{}',
    has_video INTEGER DEFAULT 0,
    deleted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_rec_created ON recordings(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_rec_parent ON recordings(parent_uid);
CREATE INDEX IF NOT EXISTS ix_rec_collection ON recordings(collection);
"""


@dataclass
class Recording:
    uid: str
    name: str
    kind: str
    collection: str
    path: str
    created_at: float
    parent_uid: Optional[str] = None
    duration_s: float = 0.0
    samples: int = 0
    pinned: bool = False
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    metrics: Dict = field(default_factory=dict)
    health_summary: str = ""
    health_worst: str = ""
    gains: Dict = field(default_factory=dict)
    has_video: bool = False
    playback_count: int = 0

    @property
    def dir(self) -> Path:
        return Path(self.path)

    @property
    def csv(self) -> Path:
        return self.dir / "data.csv"

    @property
    def meta_path(self) -> Path:
        return self.dir / "meta.json"

    @property
    def created_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.created_at))

    @property
    def is_playback(self) -> bool:
        return self.kind == "playback"


def _slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s.strip()).strip("-")
    return (s or "rec")[:n]


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.rec_root = self.root / "recordings"
        self.log_dir = self.root / "logs"
        self.ok = False
        self.error = ""
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = None
        try:
            self.rec_root.mkdir(parents=True, exist_ok=True)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".write_test"
            probe.write_text("ok")
            probe.unlink()
            self._db = sqlite3.connect(self.root / "catalog.sqlite", check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.executescript(SCHEMA)
            self.ok = True
            # a copied / cloned data folder has recordings but no catalog yet: index it
            if not self._db.execute("SELECT 1 FROM recordings LIMIT 1").fetchone() and \
                    next(self.rec_root.glob("*/*/*/meta.json"), None) is not None:
                log.info("catalog empty, rebuilt from disk: %d recordings", self.reindex())
        except Exception as e:
            self.error = str(e)
            log.exception("store init failed")

    # ---- creation ---------------------------------------------------------------
    def new_recording_dir(self, kind: str, name: str, collection: str = "default",
                          parent: Optional[Recording] = None) -> Recording:
        """Allocate a folder + catalog row.  For playbacks the name is derived
        from the parent: <parent>_pb<N>."""
        with self._lock:
            now = time.time()
            if parent is not None:
                n = self.playback_count(parent.uid) + 1
                name = f"{parent.name}_pb{n:02d}"
                collection = parent.collection
            name = _slug(name)
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            stamp = time.strftime("%H%M%S", time.localtime(now))
            folder = self.rec_root / _slug(collection) / day / f"{stamp}_{kind}_{name}"
            k = 1
            base = folder
            while folder.exists():
                k += 1
                folder = base.with_name(f"{base.name}-{k}")
            folder.mkdir(parents=True)
            rec = Recording(uid=uuid.uuid4().hex[:12], name=name, kind=kind, collection=collection,
                            path=str(folder), created_at=now, parent_uid=parent.uid if parent else None)
            self._db.execute(
                "INSERT INTO recordings(uid,name,kind,collection,parent_uid,path,created_at) VALUES(?,?,?,?,?,?,?)",
                (rec.uid, rec.name, rec.kind, rec.collection, rec.parent_uid, rec.path, rec.created_at))
            self._db.commit()
            self._write_meta(rec)
            return rec

    def finalize(self, rec: Recording):
        with self._lock:
            self._db.execute(
                "UPDATE recordings SET duration_s=?, samples=?, metrics_json=?, health_summary=?, health_worst=?, "
                "gains_json=?, has_video=?, notes=?, tags=? WHERE uid=?",
                (rec.duration_s, rec.samples, json.dumps(rec.metrics), rec.health_summary, rec.health_worst,
                 json.dumps(rec.gains), int(rec.has_video), rec.notes, ",".join(rec.tags), rec.uid))
            self._db.commit()
            self._write_meta(rec)

    def _write_meta(self, rec: Recording):
        d = asdict(rec)
        d["created_str"] = rec.created_str
        d["schema"] = 2
        try:
            (rec.dir / "meta.json").write_text(json.dumps(d, indent=2))
        except Exception:
            log.exception("meta write failed for %s", rec.path)

    # ---- edits ----------------------------------------------------------------------
    def set_pinned(self, uid: str, pinned: bool):
        with self._lock:
            self._db.execute("UPDATE recordings SET pinned=? WHERE uid=?", (int(pinned), uid))
            self._db.commit()
            self._sync_meta(uid)

    def set_notes(self, uid: str, notes: str):
        with self._lock:
            self._db.execute("UPDATE recordings SET notes=? WHERE uid=?", (notes, uid))
            self._db.commit()
            self._sync_meta(uid)

    def set_tags(self, uid: str, tags: List[str]):
        with self._lock:
            self._db.execute("UPDATE recordings SET tags=? WHERE uid=?", (",".join(t.strip() for t in tags if t.strip()), uid))
            self._db.commit()
            self._sync_meta(uid)

    def rename(self, uid: str, name: str):
        with self._lock:
            self._db.execute("UPDATE recordings SET name=? WHERE uid=?", (_slug(name), uid))
            self._db.commit()
            self._sync_meta(uid)

    def soft_delete(self, uid: str):
        """Hide from the catalog; files stay.  Written to meta.json too so a rebuilt catalog keeps it hidden."""
        with self._lock:
            row = self._db.execute("SELECT path FROM recordings WHERE uid=?", (uid,)).fetchone()
            self._db.execute("UPDATE recordings SET deleted=1 WHERE uid=?", (uid,))
            self._db.commit()
        if row:
            mp = Path(row[0]) / "meta.json"
            try:
                d = json.loads(mp.read_text())
                d["deleted"] = True
                mp.write_text(json.dumps(d, indent=2))
            except Exception:
                log.exception("could not mark %s hidden in meta.json", mp)

    def _sync_meta(self, uid: str):
        r = self.get(uid)
        if r:
            self._write_meta(r)

    # ---- queries ------------------------------------------------------------------------
    def _row_to_rec(self, r: sqlite3.Row) -> Recording:
        return Recording(uid=r["uid"], name=r["name"], kind=r["kind"], collection=r["collection"], path=r["path"],
                         created_at=r["created_at"], parent_uid=r["parent_uid"], duration_s=r["duration_s"] or 0.0,
                         samples=r["samples"] or 0, pinned=bool(r["pinned"]),
                         tags=[t for t in (r["tags"] or "").split(",") if t], notes=r["notes"] or "",
                         metrics=json.loads(r["metrics_json"] or "{}"), health_summary=r["health_summary"] or "",
                         health_worst=r["health_worst"] or "", gains=json.loads(r["gains_json"] or "{}"),
                         has_video=bool(r["has_video"]), playback_count=r["pc"] if "pc" in r.keys() else 0)

    def get(self, uid: str) -> Optional[Recording]:
        with self._lock:
            r = self._db.execute("SELECT r.*, (SELECT COUNT(*) FROM recordings p WHERE p.parent_uid=r.uid AND p.deleted=0) AS pc "
                                 "FROM recordings r WHERE uid=?", (uid,)).fetchone()
            return self._row_to_rec(r) if r else None

    def list(self, sort: str = "recent", collection: Optional[str] = None, kind: Optional[str] = None,
             include_playbacks: bool = False, search: str = "", limit: int = 500) -> List[Recording]:
        """sort: recent | pinned | playbacks | name"""
        order = {"recent": "r.pinned DESC, r.created_at DESC", "pinned": "r.pinned DESC, r.created_at DESC",
                 "playbacks": "pc DESC, r.created_at DESC", "name": "r.name COLLATE NOCASE ASC"}[sort]
        where = ["r.deleted=0"]
        args: list = []
        if not include_playbacks:
            where.append("r.kind != 'playback'")
        if collection:
            where.append("r.collection=?"); args.append(collection)
        if kind:
            where.append("r.kind=?"); args.append(kind)
        if search:
            where.append("(r.name LIKE ? OR r.tags LIKE ? OR r.notes LIKE ?)")
            args += [f"%{search}%"] * 3
        if sort == "pinned":
            where.append("r.pinned=1")
        sql = (f"SELECT r.*, (SELECT COUNT(*) FROM recordings p WHERE p.parent_uid=r.uid AND p.deleted=0) AS pc "
               f"FROM recordings r WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?")
        args.append(limit)
        with self._lock:
            return [self._row_to_rec(r) for r in self._db.execute(sql, args)]

    def playbacks_of(self, uid: str) -> List[Recording]:
        with self._lock:
            rows = self._db.execute("SELECT r.*, 0 AS pc FROM recordings r WHERE parent_uid=? AND deleted=0 "
                                    "ORDER BY created_at DESC", (uid,)).fetchall()
            return [self._row_to_rec(r) for r in rows]

    def playback_count(self, uid: str) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM recordings WHERE parent_uid=? AND deleted=0", (uid,)).fetchone()[0]

    def collections(self) -> List[str]:
        with self._lock:
            rows = self._db.execute("SELECT DISTINCT collection FROM recordings WHERE deleted=0 ORDER BY collection").fetchall()
            names = [r[0] for r in rows]
            return names if "default" in names else ["default"] + names

    # ---- maintenance ----------------------------------------------------------------------
    def reindex(self) -> int:
        """Rebuild the catalog from meta.json files on disk."""
        n = 0
        with self._lock:
            self._db.execute("DELETE FROM recordings")
            for meta in self.rec_root.glob("*/*/*/meta.json"):
                try:
                    d = json.loads(meta.read_text())
                    self._db.execute(
                        "INSERT OR REPLACE INTO recordings(uid,name,kind,collection,parent_uid,path,created_at,duration_s,"
                        "samples,pinned,tags,notes,metrics_json,health_summary,health_worst,gains_json,has_video,deleted) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (d["uid"], d["name"], d["kind"], d.get("collection", "default"), d.get("parent_uid"),
                         str(meta.parent), d["created_at"], d.get("duration_s", 0), d.get("samples", 0),
                         int(d.get("pinned", False)), ",".join(d.get("tags", [])), d.get("notes", ""),
                         json.dumps(d.get("metrics", {})), d.get("health_summary", ""), d.get("health_worst", ""),
                         json.dumps(d.get("gains", {})), int(d.get("has_video", False)), int(d.get("deleted", False))))
                    n += 1
                except Exception:
                    log.exception("reindex: bad meta %s", meta)
            self._db.commit()
        return n

    def close(self):
        if self._db:
            self._db.close()
            self._db = None
