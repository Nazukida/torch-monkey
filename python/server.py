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
import platform
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
    from pydantic import BaseModel
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

    async def snapshot(self) -> List[Dict[str, Any]]:
        """Return all non-expired task entries for the terminal dashboard.

        Each entry is a flat dict (task_id / status / progress / stage /
        message / timestamps / age) sorted most-recently-updated first. Entries
        past the TTL are filtered here so the "non-expired" contract holds at
        call time (not just after the periodic GC sweep). Used by
        ``GET /api/tasks``; safe to call frequently.
        """
        now = time.time()
        async with self._lock:
            items: List[Dict[str, Any]] = []
            for tid, e in self._items.items():
                if now - e.get("updatedAt", now) > self._ttl:
                    continue
                started = e.get("startedAt", now)
                items.append({
                    "task_id": tid,
                    "status": e.get("status"),
                    "progress": e.get("progress", 0.0),
                    "stage": e.get("stage"),
                    "message": e.get("message"),
                    "error": e.get("error"),
                    "startedAt": started,
                    "updatedAt": e.get("updatedAt", started),
                    "age": round(now - started, 1),
                })
        items.sort(key=lambda d: d.get("updatedAt") or 0, reverse=True)
        return items

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

    # Snapshot the static runtime once so /api/health doesn't re-walk PATH on
    # every poll (the dashboard + Electron manager probe frequently). VRAM is
    # refreshed live in the health endpoint.
    app.state.runtime_base = _collect_runtime()

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


def _bin_present(name_or_path: str) -> Any:
    """Resolve an external binary to its path if findable, else False.

    Accepts either an absolute path (reported verbatim if the file exists) or a
    bare name (looked up on PATH via shutil.which). Used by the runtime probe.
    """
    if not name_or_path:
        return False
    try:
        p = Path(name_or_path)
        if p.is_file():
            return str(p)
    except Exception:
        pass
    return shutil.which(name_or_path) or False


def _runtime_vram() -> Optional[tuple]:
    """Live GPU VRAM as ``(used_mb, total_mb)`` if CUDA is available, else None.

    Cheap (no PATH walk); called on every /api/health poll so the dashboard's
    VRAM reading stays live while the rest of the runtime snapshot is cached.
    """
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()  # bytes
            return round((total - free) / 1048576.0, 1), round(total / 1048576.0, 1)
    except Exception:
        pass
    return None


def _collect_runtime() -> Dict[str, Any]:
    """Best-effort snapshot of the runtime environment for ``/api/health``.

    This is the headline signal that lets the desktop client's "Test
    Connection" button (and the terminal dashboard) confirm the request really
    landed on the GPU box: device / CUDA / GPU name / VRAM / torch version.

    Every field is guarded so a missing dependency never breaks the health
    probe — the entire point of ``/api/health`` is to report readiness, so it
    must always return 200 with a populated object. Cached once at startup
    (see lifespan); VRAM is refreshed live via :func:`_runtime_vram`.
    """
    rt: Dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch_installed": False,
        "torch_version": None,
        "device": "cpu",
        "cuda_available": False,
        "device_name": None,
        "gpu_mem_total_mb": None,
        "gpu_mem_used_mb": None,
        "opencv": None,
        "ffmpeg": _bin_present(settings.FFMPEG_BIN),
        "ffprobe": _bin_present(settings.FFPROBE_BIN),
        "yt_dlp": None,
        "mediapipe": None,
    }

    # torch + CUDA — the field everyone actually reads.
    try:
        import torch  # type: ignore
        rt["torch_installed"] = True
        rt["torch_version"] = getattr(torch, "__version__", None)
        cuda = bool(torch.cuda.is_available())
        rt["cuda_available"] = cuda
        rt["device"] = "cuda" if cuda else "cpu"
        if cuda:
            try:
                rt["device_name"] = torch.cuda.get_device_name(0)
            except Exception:
                rt["device_name"] = "cuda"
            vram = _runtime_vram()
            if vram is not None:
                rt["gpu_mem_used_mb"], rt["gpu_mem_total_mb"] = vram
    except Exception:
        pass

    # opencv (video decode path)
    try:
        import cv2  # type: ignore
        rt["opencv"] = getattr(cv2, "__version__", True)
    except Exception:
        rt["opencv"] = False

    # yt-dlp (bilibili capture)
    try:
        import yt_dlp  # type: ignore
        rt["yt_dlp"] = getattr(getattr(yt_dlp, "version", None), "__version__", None) or True
    except Exception:
        rt["yt_dlp"] = False

    # mediapipe (2D estimation)
    try:
        import mediapipe as mp  # type: ignore
        rt["mediapipe"] = getattr(mp, "__version__", True)
    except Exception:
        rt["mediapipe"] = False

    return rt


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> Dict[str, Any]:
    """Report pipeline readiness. Returns 200 always (even if models missing)
    so the Electron manager can probe readiness; clients inspect ``models``.

    ``runtime`` describes the host (device / CUDA / GPU / torch / ffmpeg …) so
    a remote client can confirm its request actually reached the GPU box. The
    static part is cached at startup (no per-poll PATH walk); VRAM is live."""
    base = getattr(app.state, "runtime_base", None) or _collect_runtime()
    rt: Dict[str, Any] = dict(base)
    vram = _runtime_vram()
    if vram is not None:
        rt["gpu_mem_used_mb"], rt["gpu_mem_total_mb"] = vram
    return {
        "status": "ok",
        "models": runtime.health(),
        "runtime": rt,
        "version": app.version,
        "fps": settings.DEFAULT_TARGET_FPS,
        "host": getattr(app.state, "host", settings.DEFAULT_HOST),
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
    try:
        payload = await _run_pipeline_from_file(
            video_path=tmp_path,
            fps=fps,
            smooth=smooth,
            detect_kime=detect_kime,
            source_label=file.filename or "upload",
            task_id=task_id,
            start_progress=0.10,
        )
        return JSONResponse(content=payload)
    finally:
        tmp_path.unlink(missing_ok=True)


async def _run_pipeline_from_file(
    video_path: Path,
    fps: float,
    smooth: bool,
    detect_kime: bool,
    source_label: str,
    task_id: str,
    start_progress: float = 0.10,
) -> Dict[str, Any]:
    """Run the 5-step pipeline on an already-on-disk video file. Returns the
    response payload as a plain dict (callers wrap in JSONResponse).

    Shared by ``/api/process-video`` (local upload) and
    ``/api/process-bilibili`` (BV-id download) so both paths produce identical
    MotionData. ``source_label`` is stored as the motion's source-video tag.
    """
    processor = _build_video_processor(video_path, fps)

    try:
        # Step 1: extract frames
        await broker.update(task_id, stage="extract_frames",
                            progress=start_progress + 0.0, status="running")
        try:
            frames = processor.extract_frames()
        except Exception as exc:
            await broker.fail(task_id, f"frame extraction: {exc}")
            raise HTTPException(status_code=422, detail=f"Frame extraction failed: {exc}") from exc

        if not frames:
            await broker.fail(task_id, "no frames decoded")
            raise HTTPException(status_code=422, detail="No frames decoded from video.")

        await broker.update(task_id, stage="extract_frames",
                            progress=start_progress + 0.05, message=f"{len(frames)} frames")

        # Step 2: 2D keypoints (MediaPipe BlazePose 33)
        await broker.update(task_id, stage="pose_2d", progress=start_progress + 0.15)
        try:
            keypoints_2d = runtime.mediapipe.process_batch(frames)
        except Exception as exc:
            await broker.fail(task_id, f"2D estimation: {exc}")
            raise HTTPException(status_code=500, detail=f"2D pose estimation failed: {exc}") from exc
        await broker.update(task_id, stage="pose_2d", progress=start_progress + 0.30)

        # Step 3: 3D lifting (MotionBERT) -> SMPL_24 (24, 3)
        await broker.update(task_id, stage="pose_3d", progress=start_progress + 0.40)
        try:
            poses_3d = runtime.motionbert.infer(keypoints_2d)
        except Exception as exc:
            await broker.fail(task_id, f"3D estimation: {exc}")
            raise HTTPException(status_code=500, detail=f"3D pose estimation failed: {exc}") from exc
        await broker.update(task_id, stage="pose_3d", progress=start_progress + 0.65)

        # Step 4: wotagei optimisation (smoothing + kime). The optimizer returns
        # a dict with 'poses', 'kime_frames', and (optionally) 'kime_points'.
        await broker.update(task_id, stage="optimize", progress=start_progress + 0.70)
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
        await broker.update(task_id, stage="optimize", progress=start_progress + 0.80)

        # Step 5: export to MotionData JSON
        await broker.update(task_id, stage="export", progress=start_progress + 0.82)
        try:
            motion_data = runtime.exporter.to_motion_data(
                poses_3d=poses_3d,
                fps=fps,
                source_video=source_label,
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
        logger.info("pipeline complete: task=%s source=%s frames=%d kime=%d",
                    task_id, source_label, len(frames), len(kime_frames))
        return {
            "task_id": task_id,
            "status": "completed",
            "motion_data": motion_data,
            "stats": stats,
        }

    finally:
        processor.cleanup()


# ---------------------------------------------------------------------------
# Bilibili (BV 号) capture: download a single video by BV id, then run the
# same pipeline as /api/process-video. Uses yt-dlp (lib.bilibili_downloader).
# ---------------------------------------------------------------------------
class BilibiliCaptureRequest(BaseModel):
    """JSON body for ``/api/process-bilibili``."""
    bvid: str
    page: Optional[int] = None
    fps: float = settings.DEFAULT_TARGET_FPS
    smooth: bool = True
    detect_kime: bool = True


class BilibiliPreviewRequest(BaseModel):
    """JSON body for ``/api/preview-bilibili``."""
    bvid: str
    page: Optional[int] = None


@app.post("/api/preview-bilibili")
async def preview_bilibili(req: BilibiliPreviewRequest) -> JSONResponse:
    """Probe a Bilibili video's metadata (title / duration / uploader) **without**
    downloading. Lets the UI confirm what will be captured first."""
    try:
        from lib.bilibili_downloader import probe_bilibili, BilibiliDownloadError
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="bilibili downloader module missing.") from exc

    try:
        info = await asyncio.to_thread(
            probe_bilibili, req.bvid, req.page, settings.BILI_COOKIES_PATH or None
        )
    except BilibiliDownloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bilibili probe failed: {exc}") from exc
    return JSONResponse(content={"ok": True, "info": info})


@app.post("/api/process-bilibili")
async def process_bilibili(req: BilibiliCaptureRequest) -> JSONResponse:
    """Download a Bilibili video by BV id, then run the full mocap pipeline.

    Equivalent to ``/api/process-video`` but the source is a BV id / bilibili URL
    instead of an uploaded file. The resulting MotionData has ``source_video``
    set to ``bilibili:<BV>``. Requires ``yt-dlp`` (returns 503 with a clear
    message if it is not installed) and the usual model readiness gate.
    """
    # Gate on model readiness up front for a clear 503.
    _ = runtime.mediapipe
    _ = runtime.motionbert
    _ = runtime.optimizer
    _ = runtime.exporter

    try:
        from lib.bilibili_downloader import download_bilibili, BilibiliDownloadError
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="bilibili downloader module missing.") from exc

    task_id = str(uuid.uuid4())
    await broker.create(task_id, message="resolving bilibili")

    # Download (blocking) in a worker thread so the event loop stays responsive.
    await broker.update(task_id, stage="download", progress=0.02,
                        message=f"downloading {req.bvid}")
    try:
        dl = await asyncio.to_thread(
            download_bilibili,
            req.bvid,
            settings.WORK_DIR,
            req.page,
            settings.BILI_COOKIES_PATH or None,
            settings.BILI_MAX_DURATION_SEC,
        )
    except BilibiliDownloadError as exc:
        await broker.fail(task_id, str(exc))
        # yt-dlp missing is a 503 (service-dep), other failures are 502 (upstream).
        status = 503 if "yt-dlp is not installed" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        await broker.fail(task_id, str(exc))
        raise HTTPException(status_code=502, detail=f"Bilibili download failed: {exc}") from exc

    video_path = Path(dl["video_path"])
    source_label = f"bilibili:{dl['bvid']}" + (f"?p={dl['page']}" if dl.get("page", 1) > 1 else "")
    try:
        payload = await _run_pipeline_from_file(
            video_path=video_path,
            fps=req.fps,
            smooth=req.smooth,
            detect_kime=req.detect_kime,
            source_label=source_label,
            task_id=task_id,
            start_progress=0.15,
        )
        payload["source"] = {
            "bvid": dl["bvid"],
            "title": dl["title"],
            "duration": dl["duration"],
            "url": dl["url"],
            "page": dl.get("page", 1),
        }
        return JSONResponse(content=payload)
    finally:
        video_path.unlink(missing_ok=True)


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


@app.get("/api/tasks")
async def list_tasks() -> JSONResponse:
    """List non-expired pipeline tasks (active + recently finished) for the
    terminal dashboard. Mirrors the in-process progress broker state."""
    return JSONResponse(content={"tasks": await broker.snapshot()})


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
    # Stash the chosen port/host on app.state so the lifespan log line and
    # /api/health report the actually-bound interface (not just the import-time
    # default — matters when the user passes --host 0.0.0.0 for LAN access).
    app.state.port = args.port
    app.state.host = args.host
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
