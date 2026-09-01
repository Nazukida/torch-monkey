"""Video ingestion and frame extraction for the Torch Monkey AI pipeline.

``VideoProcessor`` wraps ffprobe (metadata) and OpenCV (frame decoding). It is
defensively coded so a missing ffprobe, a corrupt video, or an empty/short clip
raises a clear ``VideoProcessorError`` rather than an opaque traceback.

The decoder downsamples to a configurable ``target_fps`` (wotagei benefits from
60 fps source video to catch fast arm motion, but the pipeline default is 30 fps).
Frames are returned as ``list[np.ndarray]`` in RGB (H, W, 3), uint8.

This module imports OpenCV lazily inside the methods so that the package stays
importable on a machine where ``opencv-python`` is not yet installed.
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class VideoProcessorError(RuntimeError):
    """Raised when a video cannot be probed or decoded."""


@dataclass(frozen=True)
class VideoInfo:
    """Lightweight, JSON-serialisable video metadata."""

    width: int
    height: int
    fps: float
    duration: float          # seconds
    frame_count: int         # best estimate (duration * fps), 0 if unknown
    codec: str
    bitrate: int             # bits/s, 0 if unknown
    has_audio: bool
    path: str

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration": self.duration,
            "frameCount": self.frame_count,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "hasAudio": self.has_audio,
            "path": self.path,
        }


_FPS_RE = re.compile(r"^\s*(\d+)\s*(?:/\s*(\d+))?\s*$")


def _parse_frame_rate(value: str) -> float:
    """Parse an ffmpeg ``r_frame_rate`` like ``"30000/1001"`` into a float.

    Falls back to 30.0 for malformed input (never raises).
    """
    if not value:
        return 30.0
    m = _FPS_RE.match(str(value))
    if not m:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 30.0
    num = int(m.group(1))
    den = int(m.group(2)) if m.group(2) else 1
    if den == 0:
        return 30.0
    return num / den


class VideoProcessor:
    """Probe and decode a video file into RGB frames."""

    def __init__(
        self,
        video_path: str | Path,
        target_fps: float = 30.0,
        max_frames: int = 9000,
        ffprobe_bin: str = "ffprobe",
    ) -> None:
        self.video_path: Path = Path(video_path)
        self.target_fps: float = max(1.0, float(target_fps))
        #: fps actually achieved by :meth:`extract_frames`. Frames are only ever
        #: dropped, never interpolated, so asking for 30 fps from 24 fps footage
        #: yields 24. Set during extraction; falls back to the request until then.
        self.effective_fps: float = self.target_fps
        self.max_frames: int = max(1, int(max_frames))
        self.ffprobe_bin: str = ffprobe_bin

        if not self.video_path.is_file():
            raise VideoProcessorError(f"Video file not found: {self.video_path}")

        self.temp_dir: Path = Path(tempfile.mkdtemp(prefix="torchmonkey_vp_"))
        logger.debug("VideoProcessor created for %s (target_fps=%.2f)",
                     self.video_path, self.target_fps)

    # ------------------------------------------------------------------ probe
    def get_video_info(self) -> VideoInfo:
        """Run ffprobe and return :class:`VideoInfo`.

        Raises :class:`VideoProcessorError` if ffprobe is missing, fails, or
        returns no usable video stream.
        """
        cmd = [
            self.ffprobe_bin,
            "-v", "error",  # only real errors, suppress warnings
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(self.video_path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError as exc:
            raise VideoProcessorError(
                f"ffprobe not found on PATH ({self.ffprobe_bin!r}). "
                "Install ffmpeg or set TORCHMONKEY_FFPROBE to its full path."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise VideoProcessorError("ffprobe timed out after 60s.") from exc

        if result.returncode != 0:
            raise VideoProcessorError(
                f"ffprobe failed (code {result.returncode}): "
                f"{result.stderr.strip()[:500]}"
            )

        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise VideoProcessorError(f"ffprobe returned non-JSON output: {exc}") from exc

        streams = info.get("streams") or []
        video_stream = next(
            (s for s in streams if s.get("codec_type") == "video"), None,
        )
        if video_stream is None:
            raise VideoProcessorError("No video stream found in file.")

        fmt = info.get("format") or {}

        fps = _parse_frame_rate(
            video_stream.get("avg_frame_rate")
            or video_stream.get("r_frame_rate", "30/1")
        )
        if not math.isfinite(fps) or fps <= 0:
            fps = 30.0

        duration = 0.0
        for key in ("duration",):
            raw = video_stream.get(key) or fmt.get(key)
            try:
                duration = float(raw)
                if math.isfinite(duration) and duration > 0:
                    break
            except (TypeError, ValueError):
                duration = 0.0

        bitrate_raw = video_stream.get("bit_rate") or fmt.get("bit_rate")
        try:
            bitrate = int(bitrate_raw) if bitrate_raw else 0
        except (TypeError, ValueError):
            bitrate = 0

        has_audio = any(s.get("codec_type") == "audio" for s in streams)

        frame_count = 0
        nbf = video_stream.get("nb_frames")
        try:
            frame_count = int(nbf) if nbf else 0
        except (TypeError, ValueError):
            frame_count = 0
        if frame_count <= 0 and duration > 0:
            frame_count = int(round(duration * fps))

        return VideoInfo(
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            fps=fps,
            duration=duration,
            frame_count=frame_count,
            codec=str(video_stream.get("codec_name", "unknown")),
            bitrate=bitrate,
            has_audio=has_audio,
            path=str(self.video_path),
        )

    # ----------------------------------------------------------------- decode
    def extract_frames(self) -> List["object"]:
        """Decode the video into a list of RGB ``np.ndarray`` frames.

        Downsamples to ``target_fps`` by keeping every Nth decoded frame where
        ``N = round(source_fps / target_fps)`` (N >= 1). Frames are converted
        BGR -> RGB. Respects :attr:`max_frames`.

        Returns an empty list only for a genuinely empty/undecodable video;
        raises :class:`VideoProcessorError` if OpenCV cannot open the file.
        """
        try:
            import cv2  # imported lazily
        except ImportError as exc:  # pragma: no cover - environment guard
            raise VideoProcessorError(
                "opencv-python is required for frame extraction but is not "
                "installed. Run: pip install opencv-python"
            ) from exc

        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise VideoProcessorError(
                f"OpenCV could not open video: {self.video_path}"
            )

        try:
            source_fps = cap.get(cv2.CAP_PROP_FPS)
            if not math.isfinite(source_fps) or source_fps <= 0:
                source_fps = self.target_fps

            # Keep every Nth frame to hit the target fps (no interpolation).
            step = max(1, int(round(source_fps / self.target_fps)))
            # With step clamped at 1 we cannot exceed the source rate, so the
            # real output rate is source/step. Tagging the result with the
            # *requested* fps instead makes the motion play back at the wrong
            # speed (24 fps footage labelled 30 fps runs 25% fast).
            self.effective_fps = source_fps / step

            frames: List[object] = []
            frame_idx = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % step == 0:
                    # BGR -> RGB; guard against exotic channel counts.
                    if frame.ndim == 3 and frame.shape[2] == 3:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frames.append(frame)
                    if len(frames) >= self.max_frames:
                        logger.warning(
                            "Reached max_frames=%d; stopping early for %s",
                            self.max_frames, self.video_path,
                        )
                        break
                frame_idx += 1
        finally:
            cap.release()

        if not frames:
            raise VideoProcessorError(
                f"No frames could be decoded from {self.video_path} "
                "(file may be empty or corrupt)."
            )

        logger.info(
            "Extracted %d frames (source_fps=%.2f, target=%.2f, effective=%.2f, "
            "step=%d) from %s",
            len(frames), source_fps, self.target_fps, self.effective_fps, step,
            self.video_path,
        )
        return frames

    # ----------------------------------------------------------------- helper
    def extract_info_and_frames(self) -> tuple[Optional[VideoInfo], List[object]]:
        """Convenience: probe (best-effort) then decode.

        If ffprobe is unavailable the probe result is ``None`` and we still
        attempt to decode with OpenCV, which can usually read fps itself.
        """
        info: Optional[VideoInfo]
        try:
            info = self.get_video_info()
        except VideoProcessorError as exc:
            logger.warning("ffprobe unavailable, continuing without info: %s", exc)
            info = None
        frames = self.extract_frames()
        return info, frames

    # ------------------------------------------------------------------ cleanup
    def cleanup(self) -> None:
        """Remove the temp directory owned by this processor."""
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:  # pragma: no cover - best effort
            logger.debug("cleanup failed for %s", self.temp_dir, exc_info=True)
