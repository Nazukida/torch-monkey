"""MediaPipe BlazePose(33) 2D pose estimator.

Wraps ``mediapipe.tasks.python.vision.PoseLandmarker`` (model
``pose_landmarker_heavy.task``). Produces normalized ``(x, y, z, visibility)``
keypoints for single-person capture, with robust gap-filling on detection
failures.

Design notes
------------
* **Guarded import**: ``mediapipe`` is optional. The module imports cleanly
  without it; the estimator raises a clear ``RuntimeError`` if you try to
  instantiate it on a box where mediapipe isn't installed.
* **Lazy detector**: the heavy model is loaded only on first use so the FastAPI
  server boots fast and the self-test (which never touches this) stays pure.
* **Gap filling** (``process_batch``): on a detection gap we (a) re-use the
  last good frame, then (b) run a short temporal median filter that closes
  *transient* gaps (1-2 frame blips) without smearing real fast motion -- this
  is the same philosophy as the wotagei optimizer's kime-protected smoothing,
  applied here at the 2D level before any 3D lifting.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

import numpy as np

from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = ["MediaPipeEstimator", "NUM_BLAZEPOSE_JOINTS", "DetectionStats"]

NUM_BLAZEPOSE_JOINTS = 33


@dataclass(frozen=True)
class DetectionStats:
    """How much of a clip actually contained a detectable person.

    ``process_batch`` fills every gap (carry-forward + median), so its output
    array looks equally valid whether MediaPipe saw a performer in every frame
    or in none of them. Without this, a video with no person in it yields a
    confident-looking motion built entirely from filler. Callers use
    ``detection_rate`` to refuse or warn.
    """

    frames_total: int
    frames_detected: int
    mean_visibility: float

    @property
    def detection_rate(self) -> float:
        """Fraction of frames with a real detection, 0.0-1.0."""
        if self.frames_total <= 0:
            return 0.0
        return self.frames_detected / float(self.frames_total)

    def to_dict(self) -> dict:
        return {
            "framesTotal": self.frames_total,
            "framesDetected": self.frames_detected,
            "detectionRate": round(self.detection_rate, 4),
            "meanVisibility": round(self.mean_visibility, 4),
        }

# Default search locations for the pose landmarker task model.
_DEFAULT_MODEL_CANDIDATES = (
    "models/pose_landmarker_heavy.task",
    "python/models/pose_landmarker_heavy.task",
    "pose_landmarker_heavy.task",
)


def _find_model(model_path: Optional[str]) -> str:
    """Resolve the pose landmarker model path, searching common locations."""
    if model_path and os.path.isfile(model_path):
        return model_path
    candidates = [model_path] + list(_DEFAULT_MODEL_CANDIDATES) if model_path \
        else list(_DEFAULT_MODEL_CANDIDATES)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    # Return the most likely intended path even if absent, so the error message
    # is actionable; the caller decides whether to proceed.
    return model_path or _DEFAULT_MODEL_CANDIDATES[0]


class MediaPipeEstimator:
    """MediaPipe PoseLandmarker (BlazePose 33) wrapper.

    Parameters
    ----------
    model_path : str, optional
        Path to ``pose_landmarker_heavy.task``. If omitted, common locations
        are searched.
    num_poses : int
        Max number of poses to detect. Wota-gei capture is single-person, so
        the default is ``1`` (fastest, most accurate).
    min_pose_detection_confidence : float
    min_pose_presence_confidence : float
    min_tracking_confidence : float
        MediaPipe thresholds. Lower = more permissive (more detections, more
        false positives); higher = stricter.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        num_poses: int = 1,
        min_pose_detection_confidence: float = 0.5,
        min_pose_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        self.model_path = _find_model(model_path)
        self.num_poses = int(num_poses)
        self.min_pose_detection_confidence = float(min_pose_detection_confidence)
        self.min_pose_presence_confidence = float(min_pose_presence_confidence)
        self.min_tracking_confidence = float(min_tracking_confidence)
        self._detector = None  # lazy
        self._mp = None
        self._vision = None
        self._tasks_python = None
        self._available = self._probe_mediapipe()

    # ------------------------------------------------------------------
    # mediapipe availability
    # ------------------------------------------------------------------
    @staticmethod
    def _probe_mediapipe() -> bool:
        try:
            import mediapipe  # noqa: F401
            from mediapipe.tasks import python  # noqa: F401
            from mediapipe.tasks.python import vision  # noqa: F401
            return True
        except Exception:
            return False

    @property
    def available(self) -> bool:
        """True if ``mediapipe`` is importable."""
        return self._available

    def _ensure_detector(self):
        """Lazily create the PoseLandmarker (IMAGE mode for per-frame calls)."""
        if self._detector is not None:
            return
        if not self._available:
            raise RuntimeError(
                "mediapipe is not installed. Install it with "
                "`pip install mediapipe` to use MediaPipeEstimator. "
                "If you only need the pure-numpy self-test or the geometric "
                "3D lifter, you do not need mediapipe."
            )
        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(
                f"MediaPipe pose model not found at {self.model_path}. "
                "Download pose_landmarker_heavy.task from "
                "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task "
                "and place it under python/models/."
            )
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        self._mp = mp
        self._tasks_python = python
        self._vision = vision

        base_options = python.BaseOptions(model_asset_path=self.model_path)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_poses=self.num_poses,
            min_pose_detection_confidence=self.min_pose_detection_confidence,
            min_pose_presence_confidence=self.min_pose_presence_confidence,
            min_tracking_confidence=self.min_tracking_confidence,
        )
        self._detector = vision.PoseLandmarker.create_from_options(options)
        log.info("MediaPipe PoseLandmarker loaded from %s", self.model_path)

    # ------------------------------------------------------------------
    # single-frame
    # ------------------------------------------------------------------
    def process_frame(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Detect pose in a single RGB frame.

        Parameters
        ----------
        frame : np.ndarray
            RGB image, shape ``(H, W, 3)``, uint8.

        Returns
        -------
        np.ndarray or None
            ``(33, 4)`` float32 with ``[x, y, z, visibility]`` normalized to
            ``[0, 1]`` (x, y in image space; z is depth relative to hip,
            roughly in the same scale as x). ``None`` if no pose is detected.
        """
        self._ensure_detector()
        if frame is None or frame.size == 0:
            return None
        if frame.ndim != 3 or frame.shape[-1] != 3:
            raise ValueError(f"frame must be (H, W, 3) RGB; got {frame.shape}")

        mp = self._mp
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
        result = self._detector.detect(mp_image)

        landmarks_list = getattr(result, "pose_landmarks", None)
        if not landmarks_list:
            return None
        landmarks = landmarks_list[0]
        if len(landmarks) == 0:
            return None

        kp = np.zeros((NUM_BLAZEPOSE_JOINTS, 4), dtype=np.float32)
        for i, lm in enumerate(landmarks[:NUM_BLAZEPOSE_JOINTS]):
            kp[i, 0] = float(lm.x)
            kp[i, 1] = float(lm.y)
            kp[i, 2] = float(lm.z)
            kp[i, 3] = float(getattr(lm, "visibility", 1.0) or 0.0)
        return kp

    # ------------------------------------------------------------------
    # batch
    # ------------------------------------------------------------------
    def process_batch(
        self,
        frames: List[np.ndarray],
        *,
        visibility_threshold: float = 0.3,
        median_window: int = 3,
        return_stats: bool = False,
    ):
        """Run detection over a sequence of frames with robust gap-filling.

        Pipeline
        --------
        1. Per-frame detection -> ``(33, 4)`` or ``None``.
        2. **Gap filling (stage A - last good frame carry-forward)**: when a
           detection is missing entirely, repeat the last good frame; if there
           is no prior good frame, fill with zeros (the 3D lifter is robust to
           a leading gap because we median-fill next).
        3. **Visibility gating**: joints with visibility below
           ``visibility_threshold`` are marked as missing (NaN) for the median
           filter, so low-confidence detections don't pollute neighbors.
        4. **Gap filling (stage B - temporal median fill)**: for each joint
           channel, transient gaps (length <= ``median_window // 2``) are
           replaced with the median of the surrounding window. Long gaps are
           left to the carry-forward value from stage A. This closes 1-2 frame
           blips without smearing fast Wota-gei motion.

        Parameters
        ----------
        frames : list[np.ndarray]
            RGB frames ``(H, W, 3)`` uint8.
        visibility_threshold : float
            Below this, a joint is treated as missing for the median filter.
        median_window : int
            Odd window size for the temporal median fill (>= 3).
        return_stats : bool
            When True, return ``(array, DetectionStats)`` instead of just the
            array, so the caller can tell a real capture from all-filler.

        Returns
        -------
        np.ndarray
            ``(T, 33, 4)`` float32, normalized coordinates. Never contains NaN
            on output (all gaps resolved by carry-forward + median fill).
        """
        if median_window < 3:
            median_window = 3
        if median_window % 2 == 0:
            median_window += 1

        T = len(frames)
        if T == 0:
            empty = np.zeros((0, NUM_BLAZEPOSE_JOINTS, 4), dtype=np.float32)
            if return_stats:
                return empty, DetectionStats(0, 0, 0.0)
            return empty

        # Stage A: detect + carry-forward.
        raw = np.full((T, NUM_BLAZEPOSE_JOINTS, 4), np.nan, dtype=np.float32)
        last_good: Optional[np.ndarray] = None
        detected = 0
        vis_sum = 0.0
        for i, frame in enumerate(frames):
            kp = self.process_frame(frame)
            if kp is not None:
                raw[i] = kp
                last_good = kp
                detected += 1
                vis_sum += float(np.mean(kp[:, 3]))
            elif last_good is not None:
                raw[i] = last_good
            # else: leave NaN (leading gap) -> fixed by median fill / zeros below.

        # Stage B: visibility gating + temporal median fill on NaNs.
        # Mark low-visibility joints as NaN so the median ignores them.
        low_vis = raw[..., 3] < visibility_threshold
        raw_masked = raw.copy()
        raw_masked[low_vis] = np.nan

        filled = _temporal_median_fill(raw_masked, window=median_window)

        # Any remaining NaNs (e.g. an all-NaN leading run) -> zeros with vis 0.
        still_nan = ~np.isfinite(filled)
        if np.any(still_nan):
            # fall back to carry-forward of the first finite frame per channel,
            # else zero.
            filled = _forward_fill_nan(filled)
            still_nan = ~np.isfinite(filled)
            filled[still_nan] = 0.0

        # visibility channel: ensure it's in [0, 1]; NaN gaps -> 0 already handled.
        vis = filled[..., 3]
        vis = np.clip(vis, 0.0, 1.0)
        filled[..., 3] = vis

        out = filled.astype(np.float32, copy=False)
        if return_stats:
            stats = DetectionStats(
                frames_total=T,
                frames_detected=detected,
                mean_visibility=(vis_sum / detected) if detected else 0.0,
            )
            if detected == 0:
                log.warning("No pose detected in any of the %d frames.", T)
            elif stats.detection_rate < 0.5:
                log.warning(
                    "Pose detected in only %d/%d frames (%.0f%%); the rest is filler.",
                    detected, T, stats.detection_rate * 100.0,
                )
            return out, stats
        return out

    # ------------------------------------------------------------------
    def close(self):
        """Release the detector if it was created."""
        if self._detector is not None:
            try:
                self._detector.close()
            except Exception:
                pass
            self._detector = None


# ---------------------------------------------------------------------------
# numpy gap-fill helpers (no scipy dependency)
# ---------------------------------------------------------------------------
def _temporal_median_fill(arr: np.ndarray, window: int = 3) -> np.ndarray:
    """Fill NaNs along axis-0 (time) using a sliding-window median.

    ``arr`` is ``(T, 33, 4)``. For each NaN cell, take the median of the finite
    values in ``[-window//2, +window//2]`` along time. Leaves long all-NaN runs
    untouched (caller handles them via forward-fill / zeros).
    """
    T = arr.shape[0]
    half = window // 2
    out = arr.copy()
    # Find NaN positions once.
    nan_mask = ~np.isfinite(arr)
    if not np.any(nan_mask):
        return out

    # Work per (joint, channel) slice for cache-friendliness.
    for t in range(T):
        lo = max(0, t - half)
        hi = min(T, t + half + 1)
        block = arr[lo:hi]  # (<=window, 33, 4)
        finite_block = np.where(np.isfinite(block), block, np.nan)
        # nanmedian over the window axis -> (33, 4)
        with np.errstate(all="ignore"):
            med = np.nanmedian(finite_block, axis=0)
        row_nan = nan_mask[t]
        # where median is finite and the row was NaN, fill
        fillable = row_nan & np.isfinite(med)
        out[t][fillable] = np.broadcast_to(med, out[t].shape)[fillable]
    return out


def _forward_fill_nan(arr: np.ndarray) -> np.ndarray:
    """Forward-fill (then back-fill) NaNs along axis-0 per (joint, channel)."""
    out = arr.copy()
    T = out.shape[0]
    # forward fill
    for t in range(1, T):
        prev = out[t - 1]
        cur = out[t]
        nan = ~np.isfinite(cur)
        cur[nan] = prev[nan]
        out[t] = cur
    # back fill (in case leading rows were all NaN)
    for t in range(T - 2, -1, -1):
        nxt = out[t + 1]
        cur = out[t]
        nan = ~np.isfinite(cur)
        cur[nan] = nxt[nan]
        out[t] = cur
    return out


if __name__ == "__main__":  # pragma: no cover - manual smoke
    est = MediaPipeEstimator()
    if not est.available:
        print("pose_estimator_2d smoke: mediapipe not installed -> estimator "
              "marked unavailable (expected on CPU-only dev box). OK.")
    else:
        print("pose_estimator_2d smoke: mediapipe available; detector lazy.")
    # gap-fill helpers work without mediapipe:
    demo = np.full((5, 33, 4), np.nan, dtype=np.float32)
    demo[0] = 1.0
    demo[2] = 3.0
    demo[4] = 5.0
    out = _temporal_median_fill(demo, window=3)
    assert np.all(np.isfinite(out)), "median fill left NaNs"
    print("pose_estimator_2d smoke: gap-fill OK")
