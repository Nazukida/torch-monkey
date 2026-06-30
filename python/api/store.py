"""SQLite-backed persistence for the web client (motions / projects / settings).

This is the browser-side counterpart of the Electron desktop app's
``DatabaseHandler`` (``src/main/ipc/database-handler.ts``). It reuses
``database/schema.sql`` verbatim so the on-disk layout is identical, and it
returns **camelCase** dicts that match the TypeScript contracts in
``shared/types/motion.ts`` / ``shared/types/project.ts`` — the browser shim hands
them straight to the renderer without any key reshaping.

Threading: FastAPI endpoints run on the event loop, so callers wrap each method
in ``asyncio.to_thread(...)``. Internally every access is serialized by a lock
around a single ``check_same_thread=False`` connection (the pipeline server runs
a single uvicorn worker with stateful model singletons, so one DB connection is
fine).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings

logger = logging.getLogger("torch_monkey.store")

# Reuse the canonical schema shipped with the desktop app (database/schema.sql).
REPO_ROOT: Path = settings.PYTHON_ROOT.parent
SCHEMA_PATH: Path = Path(__file__).resolve().parent.parent.parent / "database" / "schema.sql"


def _safe_parse(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


class Store:
    """Single-connection SQLite store mirroring the desktop ``DatabaseHandler``."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        schema_path: Optional[Path] = None,
    ) -> None:
        self._db_path = Path(db_path) if db_path else settings.DATA_DIR / "torch-monkey.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_path = Path(schema_path) if schema_path else SCHEMA_PATH
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        logger.info("Store ready: %s", self._db_path)

    # -- lifecycle ---------------------------------------------------------
    def _init_schema(self) -> None:
        schema = self._schema_path.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(schema)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- Motion CRUD -------------------------------------------------------
    def create_motion(self, data: Dict[str, Any]) -> None:
        """INSERT OR REPLACE a full MotionData (camelCase keys). Bumps tags."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO motions
                  (id, name, description, tags, fps, duration, frame_count, skeleton_type,
                   poses_json, beat_markers_json, keyframe_flags, motion_intensity,
                   primary_joints, is_loopable, source, source_video_path, thumbnail,
                   created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["id"],
                    data.get("name", ""),
                    data.get("description", "") or "",
                    json.dumps(data.get("tags", [])),
                    data.get("fps", 30.0),
                    data.get("duration", 0.0),
                    data.get("frameCount", 0),
                    data.get("skeletonType", "smpl_24"),
                    json.dumps(data.get("poses", [])),
                    json.dumps(data.get("beatMarkers", [])),
                    json.dumps(data.get("keyframeFlags", [])),
                    data.get("motionIntensity", 0.0),
                    json.dumps(data.get("primaryJoints", [])),
                    1 if data.get("isLoopable") else 0,
                    data.get("source", "manual"),
                    data.get("sourceVideoPath"),
                    data.get("thumbnail"),
                    data.get("createdAt"),
                    data.get("updatedAt"),
                ),
            )
            self._bump_tags_locked(data.get("tags", []))
            self._conn.commit()

    def get_motion(self, motion_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM motions WHERE id = ?", (motion_id,)
            ).fetchone()
        return self._row_to_motion_data(row) if row else None

    def list_motions(self, options: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], int]:
        """Return (motion_meta_list, total) matching the filter/sort/paging opts.

        Mirrors DatabaseHandler.listMotions: search across name+description,
        source filter, tag filter (tags JSON substring), sort by
        name/created_at/intensity/updated_at, default limit 200.
        """
        options = options or {}
        where: List[str] = []
        params: List[Any] = []

        search = (options.get("search") or "").strip()
        if search:
            where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            like = f"%{search.lower()}%"
            params += [like, like]
        if options.get("source"):
            where.append("source = ?")
            params.append(options["source"])
        for tag in options.get("tags") or []:
            where.append("tags LIKE ?")
            params.append(json.dumps(tag))  # '"tag"' substring match inside the JSON array

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        sort_by = options.get("sortBy", "updated_at")
        sort_col = {
            "name": "name",
            "intensity": "motion_intensity",
            "created_at": "created_at",
        }.get(sort_by, "updated_at")
        order = "ASC" if options.get("sortOrder", "desc") == "asc" else "DESC"
        limit = int(options.get("limit", 200))
        offset = int(options.get("offset", 0))

        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS c FROM motions {where_sql}", params
            ).fetchone()["c"]
            rows = self._conn.execute(
                f"SELECT * FROM motions {where_sql} ORDER BY {sort_col} {order} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

        return [self._row_to_motion_meta(r) for r in rows], total

    def update_motion(self, motion_id: str, partial: Dict[str, Any]) -> None:
        """Partial update of editable fields; refreshes updated_at."""
        sets: List[str] = []
        params: List[Any] = []
        if "name" in partial:
            sets.append("name = ?"); params.append(partial["name"])
        if "description" in partial:
            sets.append("description = ?"); params.append(partial["description"])
        if "tags" in partial:
            sets.append("tags = ?"); params.append(json.dumps(partial["tags"]))
        if "beatMarkers" in partial:
            sets.append("beat_markers_json = ?"); params.append(json.dumps(partial["beatMarkers"]))
        if "keyframeFlags" in partial:
            sets.append("keyframe_flags = ?"); params.append(json.dumps(partial["keyframeFlags"]))
        if "thumbnail" in partial:
            sets.append("thumbnail = ?"); params.append(partial["thumbnail"])
        if not sets:
            return
        import datetime as _dt
        sets.append("updated_at = ?"); params.append(_dt.datetime.now().isoformat())
        params.append(motion_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE motions SET {', '.join(sets)} WHERE id = ?", params
            )
            self._conn.commit()

    def delete_motion(self, motion_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM motions WHERE id = ?", (motion_id,))
            self._conn.commit()

    def popular_tags(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, usage_count AS count FROM tags ORDER BY usage_count DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"name": r["name"], "count": r["count"]} for r in rows]

    # -- Project CRUD ------------------------------------------------------
    def save_project(self, data: Dict[str, Any]) -> str:
        """Upsert a ProjectFile (DB mirror). Returns the project id."""
        metadata = data.get("metadata", {}) or {}
        project_id = data.get("id") or metadata.get("name") or "project"
        import datetime as _dt
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO projects (id, name, project_json, thumbnail, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    metadata.get("name", "Project"),
                    json.dumps(data),
                    None,
                    _dt.datetime.now().isoformat(),
                ),
            )
            self._conn.commit()
        return project_id

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT project_json FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return _safe_parse(row["project_json"], None) if row else None

    def list_projects(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, thumbnail, updated_at FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "thumbnail": r["thumbnail"] or None,
                "updatedAt": r["updated_at"],
            }
            for r in rows
        ]

    # -- Settings & stats --------------------------------------------------
    def get_setting(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
            self._conn.commit()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            m = self._conn.execute(
                "SELECT COUNT(*) AS c, SUM(LENGTH(poses_json)) AS s FROM motions"
            ).fetchone()
            p = self._conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()
        return {
            "motionCount": m["c"],
            "projectCount": p["c"],
            "totalStorageBytes": m["s"] or 0,
        }

    # -- helpers -----------------------------------------------------------
    def _bump_tags_locked(self, tags: List[str]) -> None:
        """Increment tag usage counts (called under the lock)."""
        for tag in tags:
            if not tag:
                continue
            self._conn.execute(
                """
                INSERT INTO tags (name, usage_count) VALUES (?, 1)
                ON CONFLICT(name) DO UPDATE SET usage_count = usage_count + 1
                """,
                (tag,),
            )

    @staticmethod
    def _row_to_motion_meta(r: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "duration": r["duration"],
            "fps": r["fps"],
            "frameCount": r["frame_count"],
            "tags": _safe_parse(r["tags"], []),
            "motionIntensity": r["motion_intensity"],
            "source": r["source"],
            "thumbnail": r["thumbnail"] or None,
            "updatedAt": r["updated_at"],
        }

    @staticmethod
    def _row_to_motion_data(r: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "tags": _safe_parse(r["tags"], []),
            "fps": r["fps"],
            "duration": r["duration"],
            "frameCount": r["frame_count"],
            "skeletonType": r["skeleton_type"],
            "poses": _safe_parse(r["poses_json"], []),
            "beatMarkers": _safe_parse(r["beat_markers_json"], []),
            "keyframeFlags": _safe_parse(r["keyframe_flags"], []),
            "motionIntensity": r["motion_intensity"],
            "primaryJoints": _safe_parse(r["primary_joints"], []),
            "isLoopable": bool(r["is_loopable"]),
            "source": r["source"],
            "sourceVideoPath": r["source_video_path"],
            "thumbnail": r["thumbnail"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
