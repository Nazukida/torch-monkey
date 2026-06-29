"""Central configuration for the Torch Monkey AI mocap pipeline.

Everything here is plain data / paths / sane defaults. Importing this module is
side-effect free and dependency free (only ``os`` / ``pathlib``), so it can be
loaded by ``server.py`` at import time without pulling in torch / mediapipe /
opencv. Heavy model dependencies stay out of the import graph entirely.

All paths are resolved relative to the ``python/`` package root so the server
works regardless of the current working directory (Electron spawns it with an
arbitrary cwd).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# python/ is the parent of this file's package (config/).
PYTHON_ROOT: Path = Path(__file__).resolve().parent.parent

# Model weights live under python/models/.
MODELS_DIR: Path = PYTHON_ROOT / "models"

# Scratch space for per-task temp files (uploaded videos, extracted frames).
WORK_DIR: Path = PYTHON_ROOT / "_work"

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
# Default port. plan.md pins 19876; overridable via ``python server.py --port``.
DEFAULT_PORT: int = 19876
# Bind address. 127.0.0.1 (loopback only) is the safe default: pair it with an
# SSH tunnel (``ssh -L 19876:127.0.0.1:19876 user@server``) for remote training.
# To expose the server on the LAN instead, run ``python server.py --host 0.0.0.0``
# or set TORCHMONKEY_HOST=0.0.0.0 (then lock down the host firewall yourself).
DEFAULT_HOST: str = os.environ.get("TORCHMONKEY_HOST", "127.0.0.1")

# Allow CORS for the Electron renderer. Origins are matched loosely (regex-ish
# via allow_origin_regex) so dev (http://localhost:*) and prod (app://.) both work.
CORS_ORIGIN_REGEX: str = r"^(https?://localhost(:\d+)?|https?://127\.0\.0\.1(:\d+)?|app://.*)$"

# Longest upload we accept directly into memory before spilling to the temp file.
# 1 GiB ceiling; the multipart upload is streamed to disk in server.py anyway.
MAX_UPLOAD_BYTES: int = 1024 * 1024 * 1024

# ---------------------------------------------------------------------------
# Video / frame extraction
# ---------------------------------------------------------------------------
DEFAULT_TARGET_FPS: float = 30.0

# Hard ceilings so a runaway long video cannot OOM the box.
MAX_FRAMES: int = 9000          # ~5 min @ 30fps, ~2.5 min @ 60fps
MIN_FRAMES_FOR_FILTER: int = 15  # filtfilt needs a non-trivial signal length

# ---------------------------------------------------------------------------
# 2D / 3D estimation
# ---------------------------------------------------------------------------
# MediaPipe PoseLandmarker task model. The 'heavy' variant is the most accurate
# and is what we want for choreography capture.
MEDIAPIPE_MODEL_FILENAME: str = "pose_landmarker_heavy.task"

# MotionBERT 3D-lifting checkpoint. The canonical public release is
# Walter0807/MotionBERT on Hugging Face (mb3d.pth). We accept several common
# names so the download script and the user both succeed.
MOTIONBERT_MODEL_FILENAMES: List[str] = [
    "mb3d.pth",
    "motionbert_lite.pth",
    "motionbert_lite.ckpt",
]

# MotionBERT temporal context window (frames). The model was trained on 243-frame
# windows; we batch with 50% overlap and average the overlapping samples.
MOTIONBERT_CONTEXT_WINDOW: int = 243
MOTIONBERT_WINDOW_STRIDE: int = 121  # ~50% overlap of 243

# MotionBERT operates on the Human3.6M 17-joint layout.
H36M_NUM_JOINTS: int = 17

# ---------------------------------------------------------------------------
# SMPL_24 internal skeleton
# ---------------------------------------------------------------------------
SMPL24_NUM_JOINTS: int = 24

# Upper-body joints used for kime detection (shoulders, elbows, wrists, hands).
KIME_UPPER_BODY_JOINTS: List[int] = [16, 17, 18, 19, 20, 21, 22, 23]

# Glowstick bind joints (L_HAND, R_HAND).
GLOWSTICK_JOINTS: List[int] = [22, 23]

# ---------------------------------------------------------------------------
# Wotagei optimizer defaults
# ---------------------------------------------------------------------------
# Butterworth low-pass cutoff (Hz). ~3Hz preserves wotagei gestures while
# removing single-frame jitter from the 2D detector.
DEFAULT_SMOOTHING_CUTOFF_HZ: float = 3.0
DEFAULT_BUTTERWORTH_ORDER: int = 4

# Kime detection thresholds. Units are mm/s and mm/s^2 because the 3D lifter
# outputs millimetres; the exporter later rescales to metres for the skeleton.
KIME_MIN_PREV_SPEED_MMPS: float = 500.0      # was moving fast before
KIME_MAX_NEXT_SPEED_MMPS: float = 200.0      # nearly stopped after
KIME_ACCEL_THRESHOLD_MMPS2: float = 5000.0   # sharp deceleration
KIME_PROTECTION_WINDOW_FRAMES: int = 2       # leave raw +/- N frames around a kime

# 2D outlier cleaning before lifting (median filter window).
OUTLIER_MEDIAN_WINDOW: int = 3

# ---------------------------------------------------------------------------
# Output / MotionData
# ---------------------------------------------------------------------------
DEFAULT_SKELETON_TYPE: str = "smpl_24"
DEFAULT_MOTION_SOURCE: str = "ai-capture"
DEFAULT_TAGS: List[str] = ["ai-capture", "wotagei"]

# ---------------------------------------------------------------------------
# FFmpeg / FFprobe
# ---------------------------------------------------------------------------
# If bundled with the app, point these at the bundled binaries. Default: assume
# they are on PATH (standard for a dev / GPU machine).
FFPROBE_BIN: str = os.environ.get("TORCHMONKEY_FFPROBE", "ffprobe")
FFMPEG_BIN: str = os.environ.get("TORCHMONKEY_FFMPEG", "ffmpeg")

# ---------------------------------------------------------------------------
# Bilibili (BV 号) video acquisition
# ---------------------------------------------------------------------------
# yt-dlp (https://github.com/yt-dlp/yt-dlp) is imported lazily by
# lib.bilibili_downloader. Install it with:  pip install yt-dlp
# Optional Netscape cookies file for higher-quality / member-only content.
# Export from your browser, then set this to the file path.
BILI_COOKIES_PATH: str = os.environ.get("TORCHMONKEY_BILI_COOKIES", "")
# Refuse videos longer than this (seconds) to avoid accidental huge downloads.
# Default 15 minutes. Set to 0 to disable the cap.
BILI_MAX_DURATION_SEC: float = float(os.environ.get("TORCHMONKEY_BILI_MAX_DURATION", "900"))



def ensure_dirs() -> None:
    """Create the on-disk working directories if they are missing.

    Called once at server startup. Safe to call repeatedly.
    """
    for d in (MODELS_DIR, WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)


def resolve_model_path(filename: str) -> Path:
    """Return the absolute path to a model file under ``models/``."""
    return MODELS_DIR / filename


def find_existing_model(filenames: List[str]) -> Path | None:
    """Return the first model path in ``filenames`` that exists, else None."""
    for name in filenames:
        p = MODELS_DIR / name
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None
