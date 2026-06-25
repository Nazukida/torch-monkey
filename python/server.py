#!/usr/bin/env python3
"""Torch Monkey AI mocap pipeline — FastAPI server.

Exposes the Stage-4 pipeline (plan.md sections 6.1-6.8) over localhost HTTP on
port 19876. Electron's main process spawns this server via ``child_process`` and
talks to it from the renderer.

Pipeline:
    video -> VideoProcessor.extract_frames
          -> MediaPipeEstimator.process_batch       (2D, BlazePose 33)
          -> MotionBERTEstimator.infer              (3D, MotionBERT -> SMPL_24)
          -> WotageiOptimizer.optimize              (smoothing + kime)
          -> FormatExporter.to_motion_data          (MotionData JSON)

Design constraints honoured here:
  * Model classes (MediaPipe / MotionBERT / WotageiOptimizer / FormatExporter)
    are imported **lazily inside the lifespan / endpoint**, not at module top
    level. So a machine without ``torch`` / ``mediapipe`` / ``opencv`` still
    imports and boots this file (the heavy endpoints then return HTTP 503 with a
    clear message). ``/api/health`` reports exactly which subsystems are ready.
  * All pipeline modules are imported via ``from pipeline.X import Y`` so the
    package layout stays consistent across agents.
  * CORS allows localhost (any port) and the ``app://.`` Electron scheme.
  * A simple in-process :class:`ProgressBroker` lets clients poll progress per
    task_id; a GET endpoint returns JSON (SSE-style streaming is optional).

Run:
    python server.py                # default port 19876
    python server.py --port 19877
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
import tempfile
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- Lightweight stdlib / fastapi imports (always available) ---------------
# FastAPI/uvicorn are the only required imports to boot; they are lightweight
# and have no torch/mediapipe dependency. If even these are missing we fail
# loudly with a helpful message rather than a partial boot.
try:
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError as exc:  # pragma: no cover - environment guard
    sys.stderr.write(
        "[torch-monkey] Fatal: FastAPI/Uvicorn are not installed.\n"
        "Install the pipeline dependencies first:\n"
        "    pip install -r requirements.txt\n"
        f"Original error: {exc}\n"
    )
    raise SystemExit(2) from exc

# Local, dependency-free config (only uses os / pathlib).
try:
    from config import settings
except ImportError:
    # Allow running server.py directly from the python/ dir without package install.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import settings  # type: ignore[no-redef]

logger = logging.getLogger("torch_monkey.server")

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet uvicorn's access logger a touch; keep error logger loud.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Progress broker (in-process, per task_id)
# ---------------------------------------------------------------------------
class ProgressBroker:
    """Minimal in-memory progress tracker, one entry per task_id.

    Not a real message bus — just enough for the Electron main process to poll
    ``GET /api/progress/{task_id}``. Keys are task ids; values are dicts with
    ``status`` (queued|running|completed|error), ``progress`` (0..1), ``stage``,
    ``message``, and timestamps. Entries auto-expire after ``ttl_seconds``.
    """

    def __init__(self, ttl_seconds: float = 1800.0) -> None:
        self._ttl = ttl_seconds
        self._items: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create(self, task_id: str, message: str = "queued") -> None:
        async with self._lock:
            self._items[task_id] = {
                "status": "queued",
                "progress": 0.0,
                "stage": "init",
                "message": message,
                "startedAt": time.time(),
                "updatedAt": time.time(),
                "error": None,
            }

    async def update(
        self,
        task_id: str,
        *,
        progress: Optional[float] = None,
        stage: Optional[str] = None,
        message: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        async with self._lock:
            entry = self._items.get(task_id)
            if entry is None:
                return
            if progress is not None:
                entry["progress"] = max(0.0, min(1.0, float(progress)))
            if stage is not None:
                entry["stage"] = stage
            if message is not None:
                entry["message"] = message
            if status is not None:
                entry["status"] = status
            entry["updatedAt"] = time.time()

    async def complete(self, task_id: str, message: str = "completed") -> None:
        await self.update(task_id, status="completed", progress=1.0, message=message)

    async def fail(self, task_id: str, error: str) -> None:
        async with self._lock:
            entry = self._items.get(task_id)
            if entry is None:
                return
            entry["status"] = "error"
            entry["error"] = error
            entry["message"] = f"failed: {error}"
            entry["updatedAt"] = time.time()

    async def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            return self._items.get(task_id)

    async def gc(self) -> None:
        """Drop entries older than the TTL. Called periodically."""
        now = time.time()
        async with self._lock:
            stale = [
                tid for tid, e in self._items.items()
                if now - e.get("updatedAt", now) > self._ttl
            ]
            for tid in stale:
                self._items.pop(tid, None)


# ---------------------------------------------------------------------------
# Pipeline runtime (lazy model singletons)
# ---------------------------------------------------------------------------
class PipelineRuntime:
    """Holds lazily-constructed pipeline singletons and their readiness flags.

    Models are loaded on first use inside the lifespan so a missing
    torch/mediapipe never crashes import time. ``ready()`` reflects whether the
    heavy estimators could actually be constructed.
    """

    def __init__(self) -> None:
        self.video_ok: bool = False
        self.mediapipe_ok: bool = False
        self.motionbert_ok: bool = False
        self.optimizer_ok: bool = False
        self.exporter_ok: bool = False
        self._mediapipe: Any = None
        self._motionbert: Any = None
        self._optimizer: Any = None
        self._exporter: Any = None
        self._load_error: Optional[str] = None

    # -- probe lightweight deps (opencv) -----------------------------------
    def probe_video(self) -> None:
        try:
            import cv2  # noqa: F401
            self.video_ok = True
        except Exception as exc:  # pragma: no cover - env dependent
            logger.warning("OpenCV unavailable: %s", exc)
            self.video_ok = False

    # -- lazy heavy model construction -------------------------------------
    def load(self) -> None:
        """Construct all pipeline singletons. Catches per-stage failures so a
        broken stage does not prevent the rest from loading."""
        self.probe_video()

        # 2D estimator (MediaPipe)
        try:
            from pipeline.pose_estimator_2d import MediaPipeEstimator
            self._mediapipe = MediaPipeEstimator()
            self.mediapipe_ok = True
            logger.info("MediaPipeEstimator ready.")
        except Exception as exc:
            self._load_error = f"MediaPipe: {exc}"
            logger.warning("MediaPipeEstimator unavailable (%s).", exc)
            self.mediapipe_ok = False

        # 3D estimator (MotionBERT). This may construct a real model if weights
        # are present, or a geometric fallback lifter if not — either way it
        # must not raise on import. We tolerate construction errors and degrade.
        try:
            from pipeline.pose_estimator_3d import MotionBERTEstimator
            self._motionbert = MotionBERTEstimator()
            self.motionbert_ok = True
            logger.info("MotionBERTEstimator ready (device=%s).",
                        getattr(self._motionbert, "device", "?"))
        except Exception as exc:
            if self._load_error:
                self._load_error += f" | MotionBERT: {exc}"
            else:
                self._load_error = f"MotionBERT: {exc}"
            logger.warning("MotionBERTEstimator unavailable (%s).", exc)
            self.motionbert_ok = False

        # Optimizer (pure numpy/scipy — should always load).
        try:
            from pipeline.wotagei_optimizer import WotageiOptimizer
            self._optimizer = WotagestOptimizerProxy()
            self.optimizer_ok = True
            logger.info("WotageiOptimizer ready.")
        except Exception as exc:
            logger.warning("WotageiOptimizer unavailable (%s).", exc)
            self.optimizer_ok = False

        # Format exporter (pure numpy/ik — should always load).
        try:
            from pipeline.format_exporter import FormatExporter
            self._exporter = FormatExporter
            self.exporter_ok = True
            logger.info("FormatExporter ready.")
        except Exception as exc:
            logger.warning("FormatExporter unavailable (%s).", exc)
            self.exporter_ok = False

    @property
    def mediapipe(self) -> Any:
        if not self.mediapipe_ok:
            raise HTTPException(
                status_code=503,
                detail="MediaPipe 2D estimator is not available "
                       "(mediapipe / model weights missing).",
            )
        return self._mediapipe

    @property
    def motionbert(self) -> Any:
        if not self.motionbert_ok:
            raise HTTPException(
                status_code=503,
                detail="MotionBERT 3D estimator is not available "
                       "(torch / model weights missing).",
            )
        return self._motionbert

    @property
    def optimizer(self) -> Any:
        if not self.optimizer_ok:
            raise HTTPException(
                status_code=503,
                detail="WotageiOptimizer is not available.",
            )
        return self._optimizer

    @property
    def exporter(self) -> Any:
        if not self.exporter_ok:
            raise HTTPException(
                status_code=503,
                detail="FormatExporter is not available.",
            )
        return self._exporter

    def health(self) -> Dict[str, Any]:
        return {
            "mediapipe": self.mediapipe_ok,
            "motionbert": self.motionbert_ok,
            "optimizer": self.optimizer_ok,
            "exporter": self.exporter_ok,
            "video_decode": self.video_ok,
            "ready": self.mediapipe_ok and self.motionbert_ok
                     and self.optimizer_ok and self.exporter_ok,
            "error": self._load_error,
        }


class WotagestOptimizerProxy:
    """Thin proxy so the endpoint code can call ``.optimize(...)`` uniformly.

    The real :class:`WotageiOptimizer` is constructed here so that an optimizer
    construction failure is caught at load time (above) rather than mid-request.
    """

    def __init__(self) -> None:
        from pipeline.wotagei_optimizer import WotageiOptimizer  # re-import is cheap
        self._impl = WotageiOptimizer()

    def optimize(self, poses_3d: Any, apply_smoothing: bool = True,
                 detect_kime: bool = True) -> Any:
        return self._impl.optimize(
            poses_3d, apply_smoothing=apply_smoothing, detect_kime=detect_kime,
        )


# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
runtime = PipelineRuntime()
broker = ProgressBroker()


# ---------------------------------------------------------------------------
# Lifespan: lazy model loading + periodic GC
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    settings.ensure_dirs()
    logger.info("Torch Monkey AI pipeline starting on %s:%d",
                settings.DEFAULT_HOST, _get_port(app))
    logger.info("Python root: %s", settings.PYTHON_ROOT)
    logger.info("Models dir: %s", settings.MODELS_DIR)

    # Load models lazily and best-effort. Failures set readiness flags but do
    # NOT crash the server — /api/health will report the missing pieces.
    try:
        runtime.load()
    except Exception:
        logger.exception("Unexpected error while loading pipeline models.")

    gc_stop = asyncio.Event()

    async def _gc_loop() -> None:
        while not gc_stop.is_set():
            try:
                await broker.gc()
            except Exception:
                pass
            try:
                await asyncio.wait_for(gc_stop.wait(), timeout=300)
            except asyncio.TimeoutError:
                pass

    gc_task = asyncio.create_task(_gc_loop())

    try:
        yield
    finally:
        gc_stop.set()
        gc_task.cancel()
        logger.info("Torch Monkey AI pipeline shutting down.")


app = FastAPI(
    title="Torch Monkey AI Pipeline",
    version="1.0.0",
    description="Wota-艺 3D choreography AI mocap pipeline.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_port(app: FastAPI) -> int:
    return getattr(app.state, "port", settings.DEFAULT_PORT)


async def _save_upload(upload: UploadFile) -> Path:
    """Stream an UploadFile to a unique temp file under the work dir. Returns
    its path. Raises HTTPException(413) if it exceeds the size ceiling."""
    suffix = Path(upload.filename or "video.bin").suffix or ".bin"
    fd, tmp_name = tempfile.mkstemp(
        prefix="upload_", suffix=suffix, dir=str(settings.WORK_DIR),
    )
    tmp_path = Path(tmp_name)
    written = 0
    try:
        with open(fd, "wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)  # 1 MiB
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload too large (>{settings.MAX_UPLOAD_BYTES} bytes).",
                    )
                out.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Could not save upload: {exc}",
        ) from exc
    finally:
        await upload.close()
    logger.info("Saved upload '%s' -> %s (%d bytes)",
                upload.filename, tmp_path, written)
    return tmp_path


def _build_video_processor(video_path: Path, target_fps: float) -> Any:
    from pipeline.video_processor import VideoProcessor, VideoProcessorError
    try:
        return VideoProcessor(
            video_path=video_path,
            target_fps=target_fps,
            max_frames=settings.MAX_FRAMES,
            ffprobe_bin=settings.FFPROBE_BIN,
        )
    except VideoProcessorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> Dict[str, Any]:
    """Report pipeline readiness. Returns 200 always (even if models missing)
    so the Electron manager can probe readiness; clients inspect ``models``."""
    return {
        "status": "ok",
        "models": runtime.health(),
        "version": app.version,
        "fps": settings.DEFAULT_TARGET_FPS,
        "time": time.time(),
    }


@app.post("/api/preview-video")
async def preview_video(file: UploadFile = File(...)) -> JSONResponse:
    """Probe a video with ffprobe and return metadata. No AI inference.

    Requires OpenCV for ffprobe-independent fps only when ffprobe is absent;
    ffprobe itself is the primary path.
    """
    from pipeline.video_processor import VideoProcessorError

    tmp_path = await _save_upload(file)
    processor = _build_video_processor(tmp_path, settings.DEFAULT_TARGET_FPS)
    try:
        try:
            info = processor.get_video_info()
            return JSONResponse(content={"ok": True, "info": info.to_dict()})
        except VideoProcessorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        processor.cleanup()
        tmp_path.unlink(missing_ok=True)


@app.post("/api/process-video")
async def process_video(
    file: UploadFile = File(...),
    fps: float = settings.DEFAULT_TARGET_FPS,
    smooth: bool = True,
    detect_kime: bool = True,
) -> JSONResponse:
    """Full pipeline: video -> frames -> 2D -> 3D -> optimize -> MotionData JSON.

    Returns the MotionData object plus processing stats.
    """
    # Gate on model readiness up front for a clear 503.
    _ = runtime.mediapipe      # raises 503 if unavailable
    _ = runtime.motionbert
    _ = runtime.optimizer
    _ = runtime.exporter

    task_id = str(uuid.uuid4())
    await broker.create(task_id, message="uploaded")

    tmp_path = await _save_upload(file)
    processor = _build_video_processor(tmp_path, fps)

    try:
        # Step 1: extract frames
        await broker.update(task_id, stage="extract_frames",
                            progress=0.05, status="running")
        try:
            frames = processor.extract_frames()
        except Exception as exc:
            await broker.fail(task_id, f"frame extraction: {exc}")
            raise HTTPException(status_code=422, detail=f"Frame extraction failed: {exc}") from exc

        if not frames:
            await broker.fail(task_id, "no frames decoded")
            raise HTTPException(status_code=422, detail="No frames decoded from video.")

        await broker.update(task_id, stage="extract_frames",
                            progress=0.15, message=f"{len(frames)} frames")

        # Step 2: 2D keypoints (MediaPipe BlazePose 33)
        await broker.update(task_id, stage="pose_2d", progress=0.20)
        try:
            keypoints_2d = runtime.mediapipe.process_batch(frames)
        except Exception as exc:
            await broker.fail(task_id, f"2D estimation: {exc}")
            raise HTTPException(status_code=500, detail=f"2D pose estimation failed: {exc}") from exc
        await broker.update(task_id, stage="pose_2d", progress=0.45)

        # Step 3: 3D lifting (MotionBERT) -> SMPL_24 (24, 3)
        await broker.update(task_id, stage="pose_3d", progress=0.50)
        try:
            poses_3d = runtime.motionbert.infer(keypoints_2d)
        except Exception as exc:
            await broker.fail(task_id, f"3D estimation: {exc}")
            raise HTTPException(status_code=500, detail=f"3D pose estimation failed: {exc}") from exc
        await broker.update(task_id, stage="pose_3d", progress=0.75)

        # Step 4: wotagei optimisation (smoothing + kime). The optimizer returns
        # a dict with 'poses', 'kime_frames', and (optionally) 'kime_points'.
        await broker.update(task_id, stage="optimize", progress=0.80)
        kime_frames: List[int] = []
        try:
            opt_result = runtime.optimizer.optimize(
                poses_3d, apply_smoothing=smooth, detect_kime=detect_kime,
            )
            if isinstance(opt_result, dict):
                poses_3d = opt_result.get("poses", poses_3d)
                kime_frames = list(opt_result.get("kime_frames", []) or [])
            else:
                poses_3d = opt_result
        except Exception as exc:
            # Smoothing is best-effort; continue with un-smoothed poses.
            logger.warning("Optimizer failed, continuing un-smoothed: %s", exc)
            await broker.update(task_id, message=f"optimizer skipped: {exc}")
        await broker.update(task_id, stage="optimize", progress=0.90)

        # Step 5: export to MotionData JSON
        await broker.update(task_id, stage="export", progress=0.92)
        try:
            motion_data = runtime.exporter.to_motion_data(
                poses_3d=poses_3d,
                fps=fps,
                source_video=file.filename or "",
                kime_frames=kime_frames,
                skeleton_type=settings.DEFAULT_SKELETON_TYPE,
            )
        except Exception as exc:
            await broker.fail(task_id, f"export: {exc}")
            raise HTTPException(status_code=500, detail=f"MotionData export failed: {exc}") from exc

        await broker.complete(task_id, message="completed")

        duration = float(len(frames) / fps) if fps > 0 else 0.0
        stats = {
            "frameCount": len(frames),
            "durationSeconds": duration,
            "kimeCount": len(kime_frames),
            "kimeFrames": kime_frames,
            "task_id": task_id,
        }
        logger.info("process-video complete: task=%s frames=%d kime=%d",
                    task_id, len(frames), len(kime_frames))
        return JSONResponse(content={
            "task_id": task_id,
            "status": "completed",
            "motion_data": motion_data,
            "stats": stats,
        })

    finally:
        processor.cleanup()
        tmp_path.unlink(missing_ok=True)


@app.get("/api/progress/{task_id}")
async def get_progress(task_id: str) -> JSONResponse:
    """Return the current progress entry for a task_id, or 404 if unknown.

    This is the JSON fallback. For SSE-style streaming a future version can wrap
    this in an EventSource; the contract (status/progress/stage/message) is
    already SSE-friendly.
    """
    entry = await broker.get(task_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown task_id: {task_id}")
    return JSONResponse(content={"task_id": task_id, **entry})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Torch Monkey AI pipeline server")
    parser.add_argument("--port", type=int, default=settings.DEFAULT_PORT,
                        help=f"Port to listen on (default {settings.DEFAULT_PORT}).")
    parser.add_argument("--host", default=settings.DEFAULT_HOST,
                        help=f"Host to bind (default {settings.DEFAULT_HOST}).")
    parser.add_argument("--log-level", default="info",
                        choices=["debug", "info", "warning", "error"],
                        help="Uvicorn log level.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)
    _configure_logging()
    # Stash the chosen port on app.state so the lifespan log line is accurate.
    app.state.port = args.port
    logger.info("Starting Torch Monkey AI pipeline: %s:%d", args.host, args.port)

    try:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level=args.log_level,
            # Single worker: the pipeline holds stateful model singletons.
            workers=1,
        )
    except OSError as exc:
        # Port-in-use etc.
        logger.error("Failed to bind %s:%d — %s", args.host, args.port, exc)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    main()
