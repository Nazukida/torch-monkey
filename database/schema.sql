-- Torch Monkey SQLite schema.
-- Stored under <userData>/torch-monkey.db. Motion bodies are kept as JSON
-- (poses_json) so the file stays self-contained and portable.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ========== Motion library ==========
CREATE TABLE IF NOT EXISTS motions (
    id                TEXT PRIMARY KEY,           -- UUID
    name              TEXT NOT NULL,
    description       TEXT DEFAULT '',
    tags              TEXT DEFAULT '[]',          -- JSON array

    fps               REAL NOT NULL DEFAULT 30.0,
    duration          REAL NOT NULL,              -- seconds
    frame_count       INTEGER NOT NULL,
    skeleton_type     TEXT NOT NULL DEFAULT 'smpl_24',

    poses_json        TEXT NOT NULL,              -- JSON: FramePose[]
    beat_markers_json TEXT DEFAULT '[]',          -- JSON: BeatMarker[]
    keyframe_flags    TEXT DEFAULT '[]',          -- JSON: number[]

    motion_intensity  REAL DEFAULT 0.0,
    primary_joints    TEXT DEFAULT '[]',          -- JSON
    is_loopable       INTEGER DEFAULT 0,

    source            TEXT NOT NULL DEFAULT 'manual',
    source_video_path TEXT,

    thumbnail         TEXT,                       -- Base64 PNG (library preview)

    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_motions_name       ON motions(name);
CREATE INDEX IF NOT EXISTS idx_motions_source     ON motions(source);
CREATE INDEX IF NOT EXISTS idx_motions_intensity  ON motions(motion_intensity);
CREATE INDEX IF NOT EXISTS idx_motions_updated    ON motions(updated_at);

-- ========== Tag autocomplete ==========
CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    usage_count INTEGER DEFAULT 1
);

-- ========== Projects (also mirrored as .tmonkey files) ==========
CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    project_json  TEXT NOT NULL,
    thumbnail     TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ========== Key/value settings ==========
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                  -- JSON
);

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('stage_defaults',  '{"width":10,"depth":10,"floorMode":"grid"}'),
    ('render_quality',  '"high"'),
    ('language',        '"zh-CN"'),
    ('auto_save_interval', '300'),
    ('python_port',     '19876');
