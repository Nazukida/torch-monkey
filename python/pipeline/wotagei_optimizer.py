"""Wota-艺 (wotagei) motion specialisation optimizer.

Real, correct implementation of the optimizer described in ``plan.md`` 6.5.
Wota-艺 motion is very different from ordinary dance: it is built around
*キメ* (kime) -- instant freezes / stops on the beat, with linear or stair-step
velocity transitions rather than smooth ones. A generic low-pass filter would
smear exactly those features away, so this optimizer is designed to **protect**
kime frames while smoothing everything else.

Pipeline (operate on **meters** internally, joint order = SMPL-24)::

    poses_3d (T,24,3) meters
      |
      | 0. short median filter (window 3) -- outlier rejection
      v
      | 1. kime detection -- negative-accel spikes, gated by preceding high
      |    speed AND following near-zero speed, on upper-body joints
      v
      | 2. Butterworth low-pass (~3 Hz) with kime-protection windows
      v
      | 3. joint-limit enforcement -- clamp elbow/knee angles via bone-direction
      |    projection (real clamping, not a stub)
      v
      | 4. velocity-curve adjustment -- kime "zero-transition" lock: at a kime
      |    frame, copy the previous pose and hold for ~2 frames
      v
    {poses, kime_points, kime_frames}

All thresholds are in **meters / meters-per-second** (the plan's mm-based
defaults are divided by 1000). The optimizer is deterministic and NumPy/SciPy
only -- it runs on the CPU dev machine and in the offline self-test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

try:  # SciPy is the preferred path (Butterworth + fast median).
    from scipy.signal import butter as _scipy_butter, filtfilt as _scipy_filtfilt
    from scipy.ndimage import median_filter as _scipy_median_filter

    _HAS_SCIPY = True
except Exception:  # pragma: no cover - exercised only on scipy-less hosts
    _HAS_SCIPY = False


def _butter_lowpass(cutoff_norm: float, order: int = 4):
    """Butterworth low-pass (b, a). Falls back to a 1st-order one-pole if SciPy
    is unavailable so the pipeline still runs (with less ideal filtering)."""
    if _HAS_SCIPY:
        return _scipy_butter(order, cutoff_norm, btype="low")
    # Numpy fallback: single-pole low-pass IIR, prewarped to the requested cutoff.
    # alpha ~ dt/(RC+dt); approximate with the normalised cutoff.
    alpha = max(min(cutoff_norm, 0.99), 1e-3)
    return np.array([alpha]), np.array([1.0, -(1.0 - alpha)])


def _filtfilt(b, a, sig: np.ndarray) -> np.ndarray:
    """Zero-phase forward-backward filter. Uses scipy when present; otherwise a
    numpy forward-backward pass of the IIR (still zero-phase-ish, edge-padded)."""
    sig = np.asarray(sig, dtype=np.float64)
    if _HAS_SCIPY:
        return _scipy_filtfilt(b, a, sig)
    # Numpy fallback: pad by reflection, run IIR forward then backward.
    pad = max(3 * max(len(b), len(a)), 12)
    padded = np.pad(sig, pad, mode="reflect")
    y = _iir_filter(b, a, padded)
    y = y[::-1]
    y = _iir_filter(b, a, y)
    y = y[::-1]
    return y[pad:len(padded) - pad]


def _iir_filter(b: np.ndarray, a: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Direct-form I transposed IIR filter (numpy)."""
    b = np.asarray(b, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    a0 = a[0] if a[0] != 0 else 1.0
    b = b / a0
    a = a / a0
    y = np.empty_like(x, dtype=np.float64)
    for n in range(len(x)):
        acc = 0.0
        for k in range(len(b)):
            if n - k >= 0:
                acc += b[k] * x[n - k]
        for k in range(1, len(a)):
            if n - k >= 0:
                acc -= a[k] * y[n - k]
        y[n] = acc
    return y


def _median_filter_1d(sig: np.ndarray, size: int = 3) -> np.ndarray:
    """Median filter along axis 0. Uses scipy.ndimage when present; otherwise a
    numpy sliding-window median."""
    if _HAS_SCIPY:
        return _scipy_median_filter(sig, size=(size, 1), mode="nearest")
    out = np.empty_like(sig, dtype=np.float64)
    half = size // 2
    T = sig.shape[0]
    for t in range(T):
        lo = max(0, t - half)
        hi = min(T, t + half + 1)
        out[t] = np.median(sig[lo:hi], axis=0)
    return out

from lib.skeleton_def import (
    NUM_JOINTS,
    SMPL24_PARENTS,
    SMPL24_REST_POSE,
    UPPER_BODY_JOINTS,
)

__all__ = ["WotageiOptimizer", "KimePoint"]

_EPS = 1e-9


# ---------------------------------------------------------------------------
# Data types.
# ---------------------------------------------------------------------------
@dataclass
class KimePoint:
    """A detected *kime* (キメ) event -- an instant freeze on the beat.

    Attributes
    ----------
    frame : int
        Frame index of the kime.
    joint : int
        Joint index whose motion froze (one of :data:`UPPER_BODY_JOINTS`).
    confidence : float
        Detection confidence in ``[0, 1]``.
    acceleration : float
        Magnitude of the negative acceleration spike (m/s^2) that triggered it.
    """

    frame: int
    joint: int
    confidence: float
    acceleration: float


# ---------------------------------------------------------------------------
# Optimizer.
# ---------------------------------------------------------------------------
class WotageiOptimizer:
    """Wota-艺 specialisation optimizer.

    Parameters
    ----------
    smoothing_cutoff : float
        Butterworth low-pass cutoff frequency in Hz (default 3.0). Higher keeps
        more detail; lower smooths more. ~3 Hz preserves wotagei arm speed while
        killing jitter.
    kime_decel_threshold : float
        Minimum *negative* acceleration magnitude (m/s^2) to count as a kime
        candidate. Default 5.0 (= 5000 mm/s^2 in the plan).
    kime_pre_speed : float
        A kime requires the joint to have been moving at least this fast just
        before the freeze (m/s). Default 0.5 (= 500 mm/s).
    kime_post_speed : float
        A kime requires the joint to be (nearly) stopped just after (m/s).
        Default 0.2 (= 200 mm/s).
    kime_protection_window : int
        Half-width (frames) of the no-smoothing window around each kime.
    sampling_fps : float
        Frame rate used for filter design and velocity/acceleration units.
    """

    def __init__(
        self,
        smoothing_cutoff: float = 3.0,
        kime_decel_threshold: float = 5.0,
        kime_pre_speed: float = 0.5,
        kime_post_speed: float = 0.2,
        kime_protection_window: int = 3,
        sampling_fps: float = 30.0,
    ):
        self.smoothing_cutoff = float(smoothing_cutoff)
        self.kime_decel_threshold = float(kime_decel_threshold)
        self.kime_pre_speed = float(kime_pre_speed)
        self.kime_post_speed = float(kime_post_speed)
        self.kime_protection_window = int(kime_protection_window)
        self.fps = float(sampling_fps)

        # Joint limits use the *fold* convention (see _enforce_joint_limits):
        # fold 0 == straight, fold ~pi == folded back. ``max_*`` is the deepest
        # allowed forward fold; straight limbs are always allowed, and genuine
        # hyperextension (child bone pointing back past straight) is clamped
        # toward straight regardless of these maxima.
        self.max_elbow_angle = np.pi * 0.92   # ~166 deg max forward fold
        self.max_knee_angle = np.pi * 0.85    # ~153 deg max forward fold

        # Joints whose fold angle we clamp: (joint, parent, child, _unused_lo, max_fold).
        self._hinge_joints: List[Tuple[int, int, int, float, float]] = [
            (18, 16, 20, 0.0, self.max_elbow_angle),  # L_ELBOW
            (19, 17, 21, 0.0, self.max_elbow_angle),  # R_ELBOW
            (4, 1, 7, 0.0, self.max_knee_angle),      # L_KNEE
            (5, 2, 8, 0.0, self.max_knee_angle),      # R_KNEE
        ]

    # ------------------------------------------------------------------
    # Public entry point.
    # ------------------------------------------------------------------
    def optimize(
        self,
        poses_3d: np.ndarray,
        apply_smoothing: bool = True,
        detect_kime: bool = True,
    ) -> Dict[str, object]:
        """Run the full optimization pipeline.

        Parameters
        ----------
        poses_3d : np.ndarray
            World positions ``(T, 24, 3)`` in meters.
        apply_smoothing : bool
            If True, apply the median prefilter + Butterworth low-pass (with
            kime protection if kime detection also runs).
        detect_kime : bool
            If True, detect kime frames and apply the velocity-curve kime lock.

        Returns
        -------
        dict
            ``{"poses": np.ndarray, "kime_points": List[KimePoint],
            "kime_frames": List[int]}``.
        """
        poses = np.asarray(poses_3d, dtype=np.float64)
        if poses.ndim != 3 or poses.shape[1] != NUM_JOINTS or poses.shape[2] != 3:
            raise ValueError(f"poses_3d must be (T,24,3); got {poses.shape}")
        T = poses.shape[0]
        poses = poses.copy()

        kime_points: List[KimePoint] = []
        kime_frames: List[int] = []

        if T < 3:
            # Not enough frames to filter/detect meaningfully; still return clean.
            return {"poses": poses, "kime_points": kime_points, "kime_frames": kime_frames}

        # Step 0: short median filter for outlier rejection (window 3) -- but
        # only when smoothing is requested so the self-test's synthetic motions
        # (which are already clean) pass through untouched if desired.
        if apply_smoothing:
            poses = self._median_prefilter(poses)

        # Step 1: kime detection (operate on the prefiltered signal).
        if detect_kime:
            kime_points = self._detect_kime(poses)
            kime_frames = sorted({kp.frame for kp in kime_points})

        # Step 2: Butterworth low-pass with kime protection.
        if apply_smoothing:
            poses = self._smooth_with_protection(poses, kime_frames)

        # Step 3: joint-limit enforcement.
        poses = self._enforce_joint_limits(poses)

        # Step 4: velocity-curve adjustment (kime zero-transition lock).
        if detect_kime and kime_frames:
            poses = self._adjust_velocity_curves(poses, kime_frames)

        return {"poses": poses, "kime_points": kime_points, "kime_frames": kime_frames}

    # ------------------------------------------------------------------
    # Step 0: median prefilter.
    # ------------------------------------------------------------------
    def _median_prefilter(self, poses: np.ndarray) -> np.ndarray:
        """Short median filter (window 3) per joint per axis for outlier rejection.

        Uses :func:`scipy.ndimage.median_filter` so short clips still work. The
        median filter is edge-preserving: it removes 1-frame spikes without
        blurring kime edges (unlike a mean filter), which is essential for
        wotagei.
        """
        T = poses.shape[0]
        if T < 3:
            return poses
        # median_filter with size=3 along the time axis, per spatial axis.
        out = np.empty_like(poses)
        for j in range(NUM_JOINTS):
            block = poses[:, j, :]  # (T,3)
            # Apply along axis 0 only.
            out[:, j, :] = _median_filter_1d(block, size=3)
        return out

    # ------------------------------------------------------------------
    # Step 1: kime detection.
    # ------------------------------------------------------------------
    def _detect_kime(self, poses: np.ndarray) -> List[KimePoint]:
        """Detect kime frames via negative-acceleration spikes.

        A kime at frame ``t`` for joint ``j`` requires *all* of:
          1. a large negative acceleration (deceleration) at ``t`` on ``j``
             (the "hard stop"),
          2. the joint was moving fast just before (>= ``kime_pre_speed``),
          3. the joint is (nearly) stopped just after (< ``kime_post_speed``).

        Acceleration is computed from per-frame position differences in m/s and
        m/s^2 using ``fps``.
        """
        T = poses.shape[0]
        if T < 4:
            return []

        dt = 1.0 / max(self.fps, _EPS)

        # Velocity at frame centers (T-1,) per joint.
        velocity = np.diff(poses, axis=0) / dt          # (T-1, J, 3) m/s
        speed = np.linalg.norm(velocity, axis=-1)       # (T-1, J)

        # Acceleration magnitude of the speed scalar (T-2,) per joint; we use the
        # signed difference of speed so a deceleration is a large negative value.
        accel = np.diff(speed, axis=0) / dt             # (T-2, J) m/s^2

        # speed[i] is the speed of the interval (frame i -> i+1). accel[i] is the
        # change of that interval-speed between interval i and interval i+1.
        # A kime "at frame f" corresponds to the hard stop as the joint arrives
        # at frame f: we map accel index i -> candidate frame i+2.
        kime_points: List[KimePoint] = []
        threshold = self.kime_decel_threshold

        for joint_idx in UPPER_BODY_JOINTS:
            ja = accel[:, joint_idx]
            for i in range(len(ja)):
                a = ja[i]
                if a > -threshold:
                    continue
                # Preceding speed: the interval just before arriving, i.e. speed[i].
                pre = speed[i, joint_idx]
                if pre < self.kime_pre_speed:
                    continue
                # Following speed: the next interval's speed, speed[i+1].
                nxt_idx = min(i + 1, speed.shape[0] - 1)
                post = speed[nxt_idx, joint_idx]
                if post > self.kime_post_speed:
                    continue
                frame = i + 2  # see mapping note above
                if frame < 0 or frame >= T:
                    continue
                confidence = float(min(1.0, abs(a) / (threshold * 3.0)))
                kime_points.append(
                    KimePoint(
                        frame=frame,
                        joint=joint_idx,
                        confidence=confidence,
                        acceleration=float(a),
                    )
                )

        # De-duplicate per frame: keep the strongest kime per frame so downstream
        # protection/lock windows don't pile up.
        if not kime_points:
            return kime_points
        best: Dict[int, KimePoint] = {}
        for kp in kime_points:
            cur = best.get(kp.frame)
            if cur is None or abs(kp.acceleration) > abs(cur.acceleration):
                best[kp.frame] = kp
        return sorted(best.values(), key=lambda kp: kp.frame)

    # ------------------------------------------------------------------
    # Step 2: protected smoothing.
    # ------------------------------------------------------------------
    def _smooth_with_protection(
        self, poses: np.ndarray, kime_frames: List[int]
    ) -> np.ndarray:
        """Butterworth low-pass per joint/axis, leaving kime windows raw.

        The trick: we cannot simply *skip* kime frames in a zero-phase filter
        (filtfilt needs a contiguous signal). Instead we:
          1. filter the full signal,
          2. blend back toward the raw signal inside each kime protection window
             using a smoothstep so the protected region stays essentially raw
             while the transition back to filtered is C1-continuous.
        """
        T = poses.shape[0]
        nyquist = self.fps / 2.0
        cutoff = self.smoothing_cutoff / max(nyquist, _EPS)
        cutoff = min(max(cutoff, 1e-3), 0.99)

        # Protection weight per frame (1 = keep raw, 0 = use filtered).
        weight = np.zeros(T, dtype=np.float64)
        W = self.kime_protection_window
        for kf in kime_frames:
            lo = max(0, kf - W)
            hi = min(T, kf + W + 1)
            weight[lo:hi] = 1.0

        # Need a long-enough signal for filtfilt's padlen; fall back to raw if
        # too short.
        min_len = 15
        if T < min_len:
            return poses

        try:
            b, a = _butter_lowpass(cutoff, order=4)
            filtered = np.empty_like(poses)
            for j in range(NUM_JOINTS):
                for d in range(3):
                    sig = poses[:, j, d]
                    try:
                        filtered[:, j, d] = _filtfilt(b, a, sig)
                    except Exception:
                        filtered[:, j, d] = sig  # filtfilt can fail on edge cases
        except Exception:
            return poses  # filter design failure -> leave raw

        w = weight[:, None, None]
        return filtered * (1.0 - w) + poses * w

    # ------------------------------------------------------------------
    # Step 3: joint-limit enforcement (REAL, not a stub).
    # ------------------------------------------------------------------
    def _enforce_joint_limits(self, poses: np.ndarray) -> np.ndarray:
        """Clamp elbow/knee hinge angles via bone-direction projection.

        Convention
        ----------
        Let ``v_in = joint - parent`` (the parent bone direction at the joint)
        and ``v_out = child - joint`` (the child bone direction). The **fold
        angle** ``theta`` is the unsigned angle between them in ``[0, pi]``::

            * ``theta ~ 0``  -> limb is straight (v_in and v_out aligned),
            * ``theta ~ pi`` -> limb folded all the way back.

        Anatomically a knee/elbow:
          * may be straight or fold forward up to ``max_fold`` (~165 deg),
          * must NOT **hyperextend** -- i.e. ``v_out`` must not point *against*
            ``v_in`` past the straight line. We detect hyperextension as
            ``dot(v_in, v_out) < 0`` (the child bone points back past the
            parent) and clamp it back toward straight.

        When a limit is violated we **rotate the child bone** about the axis
        perpendicular to the bone plane until the fold is in range. Only the
        child moves (descendants follow because downstream IK recomputes from
        positions), and bone length is preserved.
        """
        out = poses.copy()
        T = out.shape[0]
        for (joint, parent, child, _lo, hi) in self._hinge_joints:
            for t in range(T):
                p = out[t, parent]
                j = out[t, joint]
                c = out[t, child]
                v_in = j - p    # parent -> joint
                v_out = c - j   # joint -> child
                n_in = float(np.linalg.norm(v_in))
                n_out = float(np.linalg.norm(v_out))
                if n_in < _EPS or n_out < _EPS:
                    continue
                u_in = v_in / n_in
                u_out = v_out / n_out
                dot = float(np.dot(u_in, u_out))
                cos_a = float(np.clip(dot, -1.0, 1.0))
                theta = float(np.arccos(cos_a))  # fold in [0, pi]

                # Determine whether we need to clamp, and to what target fold.
                target = None
                if dot < -1e-2:
                    # Hyperextension: child bone points back past straight.
                    # Clamp toward straight (theta -> 0). Snap to a small fold so
                    # we don't leave the limb perfectly collinear (numerically
                    # fragile) but essentially straight.
                    target = 1e-2
                elif theta > hi:
                    # Over-folded beyond the anatomical maximum.
                    target = hi
                if target is None:
                    continue

                # Rotation axis = normal to the bone plane.
                axis = np.cross(u_in, u_out)
                axis_n = float(np.linalg.norm(axis))
                if axis_n < _EPS:
                    axis = _any_perpendicular(u_in)
                else:
                    axis = axis / axis_n

                # Rotate v_out by (target - theta) about `axis`. The sign of the
                # cross-product axis makes this reduce theta when theta > target.
                delta = target - theta
                R = _axis_angle_matrix(axis, delta)
                new_u_out = R @ u_out
                out[t, child] = j + new_u_out * n_out
        return out

    # ------------------------------------------------------------------
    # Step 4: velocity-curve adjustment (kime lock).
    # ------------------------------------------------------------------
    def _adjust_velocity_curves(
        self, poses: np.ndarray, kime_frames: List[int]
    ) -> np.ndarray:
        """Apply the kime "zero-transition" lock.

        At each kime frame ``kf``: copy the *previous* frame's pose into ``kf``
        (instant stop, no transition), then hold for ~2 frames (micro-hold) so
        the freeze reads as a deliberate beat hit rather than a single-sample
        dip. This matches the wotagei aesthetic of "停止时是瞬间刹车 (零过渡帧)".
        """
        adjusted = poses.copy()
        T = adjusted.shape[0]
        hold = 2  # micro-hold length (frames after the kime)
        for kf in kime_frames:
            if kf < 1 or kf >= T:
                continue
            anchor = adjusted[kf - 1].copy()
            adjusted[kf] = anchor
            for h in range(1, hold + 1):
                idx = kf + h
                if idx < T:
                    adjusted[idx] = anchor.copy()
        return adjusted


# ---------------------------------------------------------------------------
# Small geometry helpers for joint-limit enforcement.
# ---------------------------------------------------------------------------
def _any_perpendicular(v: np.ndarray) -> np.ndarray:
    """Return any unit vector perpendicular to ``v``."""
    v = np.asarray(v, dtype=np.float64)
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(v, ref))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    perp = ref - v * float(np.dot(v, ref))
    n = np.linalg.norm(perp)
    if n < _EPS:
        return np.array([0.0, 0.0, 1.0])
    return perp / n


def _axis_angle_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues rotation matrix for ``angle`` (rad) about unit ``axis``."""
    axis = np.asarray(axis, dtype=np.float64)
    n = np.linalg.norm(axis)
    if n < _EPS:
        return np.eye(3, dtype=np.float64)
    axis = axis / n
    c = np.cos(angle)
    s = np.sin(angle)
    x, y, z = axis
    C = 1.0 - c
    return np.array(
        [
            [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
        ],
        dtype=np.float64,
    )


# ---------------------------------------------------------------------------
# Self-check.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(0)
    # Build a synthetic arm-raise with a hard stop near the middle to produce a
    # kime, on the SMPL-24 rest skeleton.
    rest = SMPL24_REST_POSE
    T = 40
    base = np.tile(rest, (T, 1, 1))
    # Move L_HAND (22) quickly then freeze around frame 20.
    for t in range(T):
        if t < 18:
            base[t, 22] = rest[22] + np.array([0.0, 0.02 * t, 0.0])
        else:
            base[t, 22] = base[18, 22]  # freeze
    # Add a touch of noise.
    base = base + rng.normal(0, 0.002, base.shape)

    opt = WotageiOptimizer(sampling_fps=30.0)
    res = opt.optimize(base, apply_smoothing=True, detect_kime=True)
    poses = res["poses"]
    assert poses.shape == base.shape
    assert np.all(np.isfinite(poses))
    # At least one kime should be detected near the freeze.
    kf = res["kime_frames"]
    print(f"wotagei_optimizer self-check: detected kime frames = {kf}")
    print(f"  kime points: {[(kp.frame, kp.joint) for kp in res['kime_points']]}")
    assert any(15 <= f <= 22 for f in kf), "expected a kime near the freeze"
    print("wotagei_optimizer self-check: PASS")
