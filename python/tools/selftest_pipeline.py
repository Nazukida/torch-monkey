"""Closed-loop accuracy self-test for the Torch Monkey AI mocap pipeline.

This is our proxy for "improving accuracy without a GPU". It runs with **no
model weights and no GPU** (pure NumPy, optionally SciPy) and exercises the
position -> rotation -> FK round trip that is the heart of the pipeline's
accuracy:

    positions --(ik_solver.positions_to_rotations)--> local quats + root
                 --(forward_kinematics)--------------> positions'

If ``positions'`` reproduces ``positions`` to within tolerance, the IK solver and
FK are mutually consistent and the exported per-joint rotations will drive the
renderer's skeleton to the same pose the 3D lifter saw.

It also runs:
  * a :class:`pipeline.wotagei_optimizer.WotageiOptimizer` round-trip (optimiser
    must not blow up the motion or produce non-finite values, and must detect a
    planted kime), and
  * a :class:`pipeline.format_exporter.FormatExporter.to_motion_data` smoke test
    that validates the emitted JSON has ``frameCount`` poses, joint 0 carries a
    position and no other joint does, and rotations are unit quaternions.

Exit code 0 on PASS, 1 on FAIL. Prints clear per-motion PASS/FAIL with mean/max
position error in millimetres.

Run::

    python tools/selftest_pipeline.py        # from the python/ directory
    python -m tools.selftest_pipeline        # equivalently
"""

from __future__ import annotations

import math
import sys
from typing import Dict, List, Tuple

import numpy as np

# Make ``lib`` / ``pipeline`` / ``tools`` importable regardless of CWD.
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir))
if _PYTHON_ROOT not in sys.path:
    sys.path.insert(0, _PYTHON_ROOT)

from lib.skeleton_def import (  # noqa: E402
    NUM_JOINTS,
    SMPL24_NAMES,
    SMPL24_PARENTS,
    SMPL24_REST_POSE,
    UPPER_BODY_JOINTS,
)
from lib.forward_kinematics import (  # noqa: E402
    forward_kinematics,
    quat_identity,
)
from pipeline.ik_solver import positions_to_rotations  # noqa: E402
from pipeline.wotagei_optimizer import WotageiOptimizer  # noqa: E402
from pipeline.format_exporter import FormatExporter  # noqa: E402

#: Tolerance for the position round trip: 2 cm mean per joint.
MEAN_TOL_M = 0.02
#: Hard ceiling on the worst single joint/frame error: 5 cm.
MAX_TOL_M = 0.05


# ---------------------------------------------------------------------------
# Quaternion construction helpers (xyzw, consistent with lib.forward_kinematics).
# ---------------------------------------------------------------------------
def _axis_angle_quat(axis: np.ndarray, angle: float) -> np.ndarray:
    """Unit xyzw quaternion for a rotation of ``angle`` rad about ``axis``."""
    axis = np.asarray(axis, dtype=np.float64)
    n = float(np.linalg.norm(axis))
    if n < 1e-12 or abs(angle) < 1e-15:
        return quat_identity()
    axis = axis / n
    s = math.sin(angle / 2.0)
    c = math.cos(angle / 2.0)
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, c], dtype=np.float64)


def _local_rotations_per_frame(
    per_joint_angle_funcs: Dict[int, callable], T: int
) -> np.ndarray:
    """Build a ``(T, 24, 4)`` local-rotation array.

    ``per_joint_angle_funcs[joint]`` is a callable ``f(t) -> (axis, angle)`` (or
    ``None`` to leave the joint at identity). Joints not listed stay at identity.
    """
    local = np.tile(quat_identity(), (T, NUM_JOINTS, 1))
    for j, func in per_joint_angle_funcs.items():
        if func is None:
            continue
        for t in range(T):
            axis, angle = func(t)
            local[t, j] = _axis_angle_quat(axis, angle)
    return local


# ---------------------------------------------------------------------------
# Synthetic motions.
# ---------------------------------------------------------------------------
def synth_left_hand_circle(T: int = 60) -> Tuple[np.ndarray, np.ndarray, str]:
    """Motion A: L_HAND (22) draws a horizontal circle while standing.

    We rotate the whole left arm chain (L_COLLAR 13 -> L_SHOULDER 16 ->
    L_ELBOW 18 -> L_WRIST 20 -> L_HAND 22) so the hand traces a circle in the
    X-Z plane. Ground truth is the FK of these known local rotations, so the
    self-test can compare IK->FK output to it exactly.
    """
    # Raise the arm out to the side first (about +Z at the collar/shoulder),
    # then oscillate the shoulder forward/back to draw the circle.
    def collar(_t):
        # lift arm laterally
        return (np.array([0.0, 0.0, 1.0]), math.radians(70))

    def shoulder(t):
        # sinusoidal pitch to sweep the hand through a circle
        ang = math.radians(35) * math.sin(2 * math.pi * t / T)
        return (np.array([0.0, 1.0, 0.0]), ang)

    def elbow(t):
        # slight fixed bend so the forearm points outward
        ang = math.radians(20) + math.radians(10) * math.cos(2 * math.pi * t / T)
        return (np.array([0.0, 1.0, 0.0]), ang)

    funcs = {13: collar, 16: shoulder, 18: elbow}
    local = _local_rotations_per_frame(funcs, T)
    root = np.tile(SMPL24_REST_POSE[0], (T, 1))
    positions = forward_kinematics(local, root)
    return positions, local, "left_hand_circle"


def synth_right_arm_wave(T: int = 50) -> Tuple[np.ndarray, np.ndarray, str]:
    """Motion B: a right-arm wave (R_ELBOW 19 / R_WRIST 21 oscillation).

    The right elbow flexes and the wrist flaps sinusoidally, simulating a wave.
    """
    def collar(_t):
        # raise the right arm up
        return (np.array([0.0, 0.0, -1.0]), math.radians(80))

    def elbow(t):
        ang = math.radians(50) + math.radians(35) * math.sin(2 * math.pi * t / (T / 2))
        return (np.array([0.0, 1.0, 0.0]), ang)

    def wrist(t):
        ang = math.radians(30) * math.sin(2 * np.pi * t / (T / 2))
        return (np.array([1.0, 0.0, 0.0]), ang)

    funcs = {14: collar, 19: elbow, 21: wrist}
    local = _local_rotations_per_frame(funcs, T)
    root = np.tile(SMPL24_REST_POSE[0], (T, 1))
    positions = forward_kinematics(local, root)
    return positions, local, "right_arm_wave"


# ---------------------------------------------------------------------------
# Round-trip checks.
# ---------------------------------------------------------------------------
def round_trip_error(positions: np.ndarray) -> Tuple[float, float, np.ndarray]:
    """Run IK then FK on ``positions`` and return (mean_err_m, max_err_m, err).

    Only the *positions* are compared -- the IK/FK pair is an exact inverse on
    positions by construction; the twist around each bone is free and does not
    move any joint. The root trajectory uses the input pelvis.
    """
    ik = positions_to_rotations(positions, use_real_root_height=True)
    recon = forward_kinematics(ik["rotations"], ik["root_positions"])
    err = np.linalg.norm(recon - positions, axis=-1)  # (T, 24)
    return float(err.mean()), float(err.max()), err


def check_motion(positions: np.ndarray, name: str) -> bool:
    """Assert the IK->FK round trip on ``positions`` is within tolerance."""
    mean_err, max_err, err = round_trip_error(positions)
    ok_mean = mean_err < MEAN_TOL_M
    ok_max = max_err < MAX_TOL_M
    passed = ok_mean and ok_max
    # Per-joint breakdown for diagnostics.
    per_joint = err.mean(axis=0)  # (24,)
    worst_j = int(np.argmax(per_joint))
    status = "PASS" if passed else "FAIL"
    print(
        f"  [{status}] {name}: mean err {mean_err * 1000:7.3f} mm  "
        f"max err {max_err * 1000:7.3f} mm  "
        f"(tol mean<{MEAN_TOL_M * 1000:.0f}mm, max<{MAX_TOL_M * 1000:.0f}mm)  "
        f"worst joint {worst_j}:{SMPL24_NAMES[worst_j]} "
        f"({per_joint[worst_j] * 1000:.2f} mm)"
    )
    return passed


# ---------------------------------------------------------------------------
# Optimiser + exporter smoke tests.
# ---------------------------------------------------------------------------
def check_optimizer() -> bool:
    """WotageiOptimizer must: round-trip cleanly, detect a planted kime."""
    print("  [.... ] wotagei_optimizer round-trip + kime detection")
    T = 40
    base = np.tile(SMPL24_REST_POSE, (T, 1, 1)).astype(np.float64)
    # Move L_HAND fast then freeze at frame 20 -> a planted kime.
    for t in range(T):
        if t < 18:
            base[t, 22] = SMPL24_REST_POSE[22] + np.array([0.0, 0.02 * t, 0.0])
        else:
            base[t, 22] = base[18, 22]
    rng = np.random.default_rng(7)
    noisy = base + rng.normal(0, 0.002, base.shape)

    opt = WotageiOptimizer(sampling_fps=30.0)
    res = opt.optimize(noisy, apply_smoothing=True, detect_kime=True)
    out = res["poses"]
    cond_finite = np.all(np.isfinite(out))
    cond_shape = out.shape == noisy.shape
    kime_frames = res["kime_frames"]
    # A kime should land near the freeze (frames 15..22) on an upper-body joint.
    cond_kime = any(15 <= f <= 22 for f in kime_frames)
    # On a NON-kime frame (mid-motion, before the freeze), the optimizer must
    # stay close to the clean ground truth -- it should only alter motion in the
    # kime protection/lock windows, not smear the whole clip. We exclude the
    # freeze window (>= frame 15) and the ramp-up start. Tolerance 3 cm so the
    # check passes even with the pure-numpy Butterworth fallback (which smooths
    # slightly more than scipy's filtfilt); the full-SciPy path drifts ~9 mm.
    check_frame = 8
    drift = float(np.max(np.abs(out[check_frame] - base[check_frame])))
    cond_drift = drift < 0.03  # 3 cm on a smooth, non-kime frame
    # At the kime frame itself the optimizer is *allowed* to alter the velocity
    # curve (that is its job). We only assert the held hand pose is still close
    # to the input trajectory as a whole (it must not fly off into nowhere) --
    # i.e. the held pose equals some frame's hand position within a few cm.
    hand_traj = base[:, 22]  # (T,3) clean L_HAND trajectory
    held = out[min(20, T - 1), 22]
    dist_to_traj = np.linalg.norm(hand_traj - held, axis=1).min()
    near_freeze = dist_to_traj < 0.03  # held pose matches some input frame within 3 cm
    passed = cond_finite and cond_shape and cond_kime and cond_drift and near_freeze
    status = "PASS" if passed else "FAIL"
    print(
        f"  [{status}] wotagei_optimizer: finite={cond_finite} shape={cond_shape} "
        f"kime_frames={kime_frames} (near-freeze={cond_kime}) "
        f"mid_motion_drift={drift * 1000:.1f}mm held_pose_ok={near_freeze}"
    )
    return passed


def check_exporter(positions: np.ndarray) -> bool:
    """FormatExporter.to_motion_data must emit schema-correct JSON."""
    print("  [.... ] format_exporter.to_motion_data schema check")
    T = positions.shape[0]
    md = FormatExporter.to_motion_data(
        positions, fps=30.0, source_video="selftest.mp4", kime_frames=[T // 2]
    )
    import json

    json.dumps(md)  # must be JSON-serialisable

    checks = {
        "skeletonType==smpl_24": md["skeletonType"] == "smpl_24",
        "frameCount==T": md["frameCount"] == T,
        "len(poses)==T": len(md["poses"]) == T,
        "duration==T/fps": abs(md["duration"] - T / 30.0) < 1e-9,
        "intensity in [0,1]": 0.0 <= md["motionIntensity"] <= 1.0,
        "source==ai-capture": md["source"] == "ai-capture",
        "has id/createdAt/updatedAt": bool(md["id"] and md["createdAt"] and md["updatedAt"]),
        "beatMarkers from kime": (
            len(md["beatMarkers"]) == 1 and md["beatMarkers"][0]["type"] == "kime"
        ),
        "keyframeFlags==[T//2]": md["keyframeFlags"] == [T // 2],
    }

    # joint 0 carries position; others do not.
    p0 = md["poses"][0]["transforms"]
    checks["joint0 has position"] = "position" in p0["0"] and len(p0["0"]["position"]) == 3
    joint_only_root = all(
        ("position" not in p0[str(j)]) for j in range(1, NUM_JOINTS)
    )
    checks["only joint0 has position"] = joint_only_root

    # rotations are unit quaternions across every frame/joint.
    unit_ok = True
    for t in range(T):
        for j in range(NUM_JOINTS):
            q = md["poses"][t]["transforms"][str(j)]["rotation"]
            if abs(float(np.linalg.norm(q)) - 1.0) > 1e-5:
                unit_ok = False
                break
    checks["rotations are unit quats"] = unit_ok

    failed = [k for k, v in checks.items() if not v]
    passed = not failed
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] format_exporter: {len(checks)}/{len(checks) - len(failed)} checks "
          f"passed" + (f" FAILED={failed}" if failed else ""))
    return passed


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 70)
    print("Torch Monkey -- AI pipeline closed-loop accuracy self-test")
    print(f"  numpy={np.__version__}, tolerance mean<{MEAN_TOL_M * 1000:.0f}mm "
          f"max<{MAX_TOL_M * 1000:.0f}mm")
    print("=" * 70)

    results: List[bool] = []

    print("\n[1/3] Position -> Rotation -> FK round trip (IK solver accuracy):")
    for synth in (synth_left_hand_circle, synth_right_arm_wave):
        positions, _local, name = synth()
        results.append(check_motion(positions, name))

    print("\n[2/3] WotageiOptimizer round-trip + kime detection:")
    results.append(check_optimizer())

    print("\n[3/3] FormatExporter.to_motion_data schema + JSON serialisability:")
    # Use the circle motion for the exporter smoke test.
    positions, _, _ = synth_left_hand_circle(T=40)
    results.append(check_exporter(positions))

    print("\n" + "=" * 70)
    if all(results):
        print("OVERALL: PASS  (all sub-tests passed)")
        print("=" * 70)
        return 0
    print(f"OVERALL: FAIL  ({sum(1 for r in results if not r)}/{len(results)} sub-tests failed)")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    sys.exit(main())
