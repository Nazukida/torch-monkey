"""Expand Human3.6M-17 -> Torch Monkey SMPL_24 joint positions.

The 3D lifter (MotionBERT / geometric fallback) produces 17-joint, root-relative
3D positions in *millimetres*. The Torch Monkey internal skeleton is the 24-joint
``smpl_24`` defined in ``shared/constants/skeleton.ts`` (T-pose rest coordinates
given in the project brief). Before IK we must convert the 17 H36M joints into
the full 24-joint skeleton.

SMPL_24 joint order (index: name, parent)::

     0 PELVIS(-1)   1 L_HIP(0)     2 R_HIP(0)      3 SPINE_1(0)
     4 L_KNEE(1)    5 R_KNEE(2)    6 SPINE_2(3)    7 L_ANKLE(4)
     8 R_ANKLE(5)   9 SPINE_3(6)  10 L_FOOT(7)    11 R_FOOT(8)
    12 NECK(9)     13 L_COLLAR(9) 14 R_COLLAR(9)  15 HEAD(12)
    16 L_SHOULDER(13) 17 R_SHOULDER(14) 18 L_ELBOW(16) 19 R_ELBOW(17)
    20 L_WRIST(18)    21 R_WRIST(19)    22 L_HAND(20)  23 R_HAND(21)

H36M-17 order::

     0 root 1 R-hip 2 R-knee 3 R-ankle 4 L-hip 5 L-knee 6 L-ankle
     7 spine 8 neck 9 head 10 L-shoulder 11 L-elbow 12 L-wrist
    13 R-shoulder 14 R-elbow 15 R-wrist 16 thorax

All geometry here is **generic and robust**: when a needed quantity is missing
or degenerate (e.g. zero-length limb), we fall back to the canonical T-pose
direction so the output is always a valid, plausible skeleton.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

__all__ = [
    "SMPL24_REST",
    "SMPL24_PARENTS",
    "expand_h36m17_to_smpl24",
    "expand_h36m17_to_smpl24_mm",
]


# ---------------------------------------------------------------------------
# SMPL_24 rest pose (T-pose, meters, Y-up, faces +Z) -- the single source of
# truth copied verbatim from the project brief.
# ---------------------------------------------------------------------------
SMPL24_REST: np.ndarray = np.array(
    [
        [0.00, 0.90, 0.00],  #  0 PELVIS
        [0.10, 0.86, 0.00],  #  1 L_HIP
        [-0.10, 0.86, 0.00],  #  2 R_HIP
        [0.00, 1.00, 0.00],  #  3 SPINE_1
        [0.10, 0.45, 0.00],  #  4 L_KNEE
        [-0.10, 0.45, 0.00],  #  5 R_KNEE
        [0.00, 1.10, 0.00],  #  6 SPINE_2
        [0.10, 0.05, 0.00],  #  7 L_ANKLE
        [-0.10, 0.05, 0.00],  #  8 R_ANKLE
        [0.00, 1.22, 0.00],  #  9 SPINE_3
        [0.10, 0.02, 0.12],  # 10 L_FOOT
        [-0.10, 0.02, 0.12],  # 11 R_FOOT
        [0.00, 1.40, 0.00],  # 12 NECK
        [0.08, 1.34, 0.00],  # 13 L_COLLAR
        [-0.08, 1.34, 0.00],  # 14 R_COLLAR
        [0.00, 1.55, 0.00],  # 15 HEAD
        [0.18, 1.36, 0.00],  # 16 L_SHOULDER
        [-0.18, 1.36, 0.00],  # 17 R_SHOULDER
        [0.45, 1.36, 0.00],  # 18 L_ELBOW
        [-0.45, 1.36, 0.00],  # 19 R_ELBOW
        [0.70, 1.36, 0.00],  # 20 L_WRIST
        [-0.70, 1.36, 0.00],  # 21 R_WRIST
        [0.80, 1.36, 0.00],  # 22 L_HAND
        [-0.80, 1.36, 0.00],  # 23 R_HAND
    ],
    dtype=np.float64,
)

SMPL24_PARENTS: Tuple[int, ...] = (
    -1,  # 0 PELVIS
    0,   # 1 L_HIP
    0,   # 2 R_HIP
    0,   # 3 SPINE_1
    1,   # 4 L_KNEE
    2,   # 5 R_KNEE
    3,   # 6 SPINE_2
    4,   # 7 L_ANKLE
    5,   # 8 R_ANKLE
    6,   # 9 SPINE_3
    7,   # 10 L_FOOT
    8,   # 11 R_FOOT
    9,   # 12 NECK
    9,   # 13 L_COLLAR
    9,   # 14 R_COLLAR
    12,  # 15 HEAD
    13,  # 16 L_SHOULDER
    14,  # 17 R_SHOULDER
    16,  # 18 L_ELBOW
    17,  # 19 R_ELBOW
    18,  # 20 L_WRIST
    19,  # 21 R_WRIST
    20,  # 22 L_HAND
    21,  # 23 R_HAND
)

# Rest bone lengths / direction helpers (meters), used for the anthropometric
# extensions (collars, hands, feet) that H36M-17 does not provide.
_REST = SMPL24_REST
_HAND_LEN = float(np.linalg.norm(_REST[22] - _REST[20]))  # 0.10 m wrist->hand
_FOOT_LEN = float(np.linalg.norm(_REST[10] - _REST[7]))   # ~0.12 m ankle->foot (rest)

# Canonical rest directions (unit vectors) used as safe fallbacks.
def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])


_REST_NECK_TO_HEAD = _unit(_REST[15] - _REST[12])           # +Y
_REST_PELVIS_TO_NECK = _unit(_REST[12] - _REST[0])          # +Y
_REST_LWRIST_TO_HAND = _unit(_REST[22] - _REST[20])         # +X (out along arm)
_REST_RANKLE_TO_FOOT = _unit(_REST[11] - _REST[8])          # +Z (forward)


def _normalize_batch(poses17: np.ndarray) -> np.ndarray:
    """Coerce to a 3-D float64 ``(T, 17, 3)`` array, returning it + a flag."""
    arr = np.asarray(poses17, dtype=np.float64)
    if arr.ndim == 2:
        arr = arr[None, ...]
        squeezed = True
    elif arr.ndim == 3:
        squeezed = False
    else:
        raise ValueError(f"Expected (..., 17, 3); got shape {arr.shape}")
    if arr.shape[-2] != 17:
        raise ValueError(f"Expected 17 H36M joints, got {arr.shape[-2]}")
    if arr.shape[-1] != 3:
        raise ValueError(f"Expected xyz (3); got {arr.shape[-1]}")
    return arr, squeezed


def expand_h36m17_to_smpl24(
    poses17: np.ndarray,
    *,
    scale: float = 0.001,
) -> np.ndarray:
    """Expand H36M-17 3D positions into the SMPL_24 skeleton, in **meters**.

    Parameters
    ----------
    poses17 : np.ndarray
        H36M-17 3D keypoints, shape ``(17, 3)``, ``(T, 17, 3)``. By convention
        MotionBERT output is in *millimetres* and root-relative; ``scale``
        converts to meters.
    scale : float, default ``1e-3``
        Multiplier applied to all input coordinates (mm -> m). Pass ``1.0`` if
        the input is already in meters.

    Returns
    -------
    np.ndarray
        SMPL_24 positions, same rank as input: ``(24, 3)`` or ``(T, 24, 3)``,
        in meters. The root (PELVIS, joint 0) keeps the H36M root position.

    Derivation rules
    ----------------
    * **PELVIS(0)**      : H36M root(0).
    * **L_HIP(1)/R_HIP(2)**: H36M L-hip(4) / R-hip(1).
    * **SPINE_1/2/3(3,6,9)**: interpolated along pelvis->neck. We have H36M
      ``spine(7)`` and ``thorax(16)``: place SPINE_1 near pelvis, SPINE_2 at
      H36M spine, SPINE_3 at H36M thorax -- this gives a real 3-bend spine.
    * **L_KNEE/R_KNEE**  : H36M L-knee(5) / R-knee(2).
    * **L_ANKLE/R_ANKLE**: H36M L-ankle(6) / R-ankle(3).
    * **NECK(12)**       : H36M neck(8).
    * **HEAD(15)**       : H36M head(9). (Nose anchor; good enough for a head
      position. We keep the rest Y-offset when head==neck to avoid collapse.)
    * **L/R_SHOULDER(16,17)**: H36M L/R-shoulder(10,13).
    * **L/R_ELBOW(18,19)**: H36M L/R-elbow(11,14).
    * **L/R_WRIST(20,21)**: H36M L/R-wrist(12,15).
    * **L/R_COLLAR(13,14)**: derived between neck and the corresponding
      shoulder, at the canonical rest fraction along neck->shoulder. H36M-17
      has no collar landmark, so we synthesize it.
    * **L/R_HAND(22,23)**: wrist + hand_length along the wrist->fingertip
      direction. MotionBERT (17-joint) has no hand tip, so we extrapolate from
      the elbow->wrist bone direction (the arm's current direction), which is
      exactly where a glowstick would point. This is the joint the glowsticks
      bind to, so getting its direction right matters for VFX.
    * **L/R_FOOT(10,11)**: ankle + foot_length along ankle->toe. H36M-17 has no
      foot tip, so we extrapolate forward (+Z rest) blended with the current
      ankle->knee direction so feet roughly follow the shin.
    """
    arr, squeezed = _normalize_batch(poses17)
    arr = arr * scale  # to meters
    T = arr.shape[0]
    out = np.zeros((T, 24, 3), dtype=np.float64)

    p = arr  # alias, shape (T,17,3)

    # --- Direct copies / hips ---
    out[:, 0, :] = p[:, 0, :]                                    # PELVIS
    out[:, 1, :] = p[:, 4, :]                                    # L_HIP  <- H36M L-hip
    out[:, 2, :] = p[:, 1, :]                                    # R_HIP  <- H36M R-hip
    out[:, 4, :] = p[:, 5, :]                                    # L_KNEE <- L-knee
    out[:, 5, :] = p[:, 2, :]                                    # R_KNEE <- R-knee
    out[:, 7, :] = p[:, 6, :]                                    # L_ANKLE<- L-ankle
    out[:, 8, :] = p[:, 3, :]                                    # R_ANKLE<- R-ankle
    out[:, 12, :] = p[:, 8, :]                                   # NECK   <- neck
    out[:, 16, :] = p[:, 10, :]                                  # L_SHOULDER
    out[:, 17, :] = p[:, 13, :]                                  # R_SHOULDER
    out[:, 18, :] = p[:, 11, :]                                  # L_ELBOW
    out[:, 19, :] = p[:, 14, :]                                  # R_ELBOW
    out[:, 20, :] = p[:, 12, :]                                  # L_WRIST
    out[:, 21, :] = p[:, 15, :]                                  # R_WRIST

    # --- Spine chain (3, 6, 9) using pelvis, H36M spine(7), thorax(16), neck ---
    # Human3.6M-17 spine(7) and thorax(16) are derived from the same torso
    # centroid in a 2D detector, so they coincide. To avoid a collapsed spine
    # chain we *re-distribute* the three SMPL_24 spine links along the
    # pelvis(0) -> neck(8) axis at the canonical rest ratios, using the H36M
    # spine/thorax values only to nudge the curve. This guarantees a non-zero,
    # realistic 3-bend spine even when the 2D sources are identical.
    pelvis = p[:, 0, :]
    neck_h = p[:, 8, :]
    spine_h = p[:, 7, :]
    thorax_h = p[:, 16, :]

    # rest cumulative distances along pelvis -> neck, passing through 3,6,9
    d_pelvis_spine1 = float(np.linalg.norm(_REST[3] - _REST[0]))
    d_spine1_spine2 = float(np.linalg.norm(_REST[6] - _REST[3]))
    d_spine2_spine3 = float(np.linalg.norm(_REST[9] - _REST[6]))
    d_spine3_neck = float(np.linalg.norm(_REST[12] - _REST[9]))
    d_total = (d_pelvis_spine1 + d_spine1_spine2 + d_spine2_spine3 + d_spine3_neck)
    f1 = d_pelvis_spine1 / d_total                       # ~0.227
    f2 = (d_pelvis_spine1 + d_spine1_spine2) / d_total   # ~0.455
    f3 = (d_pelvis_spine1 + d_spine1_spine2 + d_spine2_spine3) / d_total  # ~0.727

    axis = neck_h - pelvis  # pelvis -> neck direction (per frame)
    out[:, 3, :] = pelvis + f1 * axis                    # SPINE_1
    out[:, 6, :] = pelvis + f2 * axis                    # SPINE_2
    out[:, 9, :] = pelvis + f3 * axis                    # SPINE_3

    # Blend the redistributed spine with the H36M spine/thorax hints where they
    # are meaningfully different (e.g. learned-3D output that has a real curve),
    # so we don't throw away information when it exists.
    spine_diff = np.linalg.norm(spine_h - thorax_h, axis=-1, keepdims=True)
    has_curve = spine_diff[:, 0] > 1e-3                   # (T,)
    if np.any(has_curve):
        # where the detector/model gave distinct spine & thorax, weight them in
        out[:, 6, :] = np.where(has_curve[:, None], 0.5 * out[:, 6, :] + 0.5 * spine_h, out[:, 6, :])
        out[:, 9, :] = np.where(has_curve[:, None], 0.5 * out[:, 9, :] + 0.5 * thorax_h, out[:, 9, :])

    # --- HEAD(15): keep nose position, but if head==neck collapse, nudge up ---
    head = p[:, 9, :]
    neck = p[:, 8, :]
    head_dist = np.linalg.norm(head - neck, axis=-1)            # (T,)
    collapsed = head_dist < 1e-3
    if np.any(collapsed):
        head = head.copy()
        head[collapsed] = neck[collapsed] + _REST_NECK_TO_HEAD * 0.15
    out[:, 15, :] = head

    # --- Collars (13 L, 14 R): between neck and shoulder at rest fraction ---
    def _collar(neck_idx, sho_idx, rest_collar):
        # rest fraction of collar along neck->shoulder
        denom = float(np.linalg.norm(
            _REST[sho_idx] - _REST[neck_idx]
        ))
        frac = float(np.linalg.norm(rest_collar - _REST[neck_idx])) / denom if denom > 1e-6 else 0.5
        return out[:, neck_idx, :] + frac * (out[:, sho_idx, :] - out[:, neck_idx, :])
    out[:, 13, :] = _collar(12, 16, _REST[13])                  # L_COLLAR
    out[:, 14, :] = _collar(12, 17, _REST[14])                  # R_COLLAR

    # --- Hands (22 L, 23 R): wrist + hand_len along elbow->wrist direction ---
    def _extend(wrist_idx, elbow_idx, length, rest_dir):
        wrist = out[:, wrist_idx, :]
        elbow = out[:, elbow_idx, :]
        d = wrist - elbow                                        # arm direction
        n = np.linalg.norm(d, axis=-1, keepdims=True)
        # avoid div-by-zero -> fall back to rest direction
        safe = n[:, 0] > 1e-6
        unit = np.where(
            safe[:, None], d / np.maximum(n, 1e-12),
            np.broadcast_to(rest_dir, d.shape),
        )
        return wrist + length * unit
    out[:, 22, :] = _extend(20, 18, _HAND_LEN, _REST_LWRIST_TO_HAND)   # L_HAND
    out[:, 23, :] = _extend(21, 19, _HAND_LEN, -_REST_LWRIST_TO_HAND)  # R_HAND

    # --- Feet (10 L, 11 R): ankle + foot_len, forward (+Z) with slight down tilt ---
    # Feet point forward (+Z, character faces +Z) with a small downward (+-Y)
    # tilt so they sit on the ground. We do NOT follow the shin direction
    # (which is nearly vertical for a standing person and would cancel the
    # forward component); H36M-17 has no toe landmark, so a fixed forward
    # plantigrade direction is the best anthropometric guess and keeps the
    # ankle->foot bone at its rest length.
    def _foot(ankle_idx):
        ankle = out[:, ankle_idx, :]
        fwd = np.array([0.0, -0.3, 1.0])  # mostly forward, slightly down
        dirn = _unit(fwd)
        dirn = np.broadcast_to(dirn, ankle.shape)
        return ankle + _FOOT_LEN * dirn
    out[:, 10, :] = _foot(7)                                    # L_FOOT
    out[:, 11, :] = _foot(8)                                    # R_FOOT

    if squeezed:
        return out[0]
    return out


def expand_h36m17_to_smpl24_mm(poses17: np.ndarray) -> np.ndarray:
    """Convenience wrapper: input is in **millimetres**, output in meters.

    Equivalent to ``expand_h36m17_to_smpl24(poses17, scale=1e-3)`` but kept as
    a separate, explicit name because MotionBERT's native output unit is mm.
    """
    return expand_h36m17_to_smpl24(poses17, scale=1e-3)


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(1)
    # Build a plausible H36M-17 frame (mm, root-relative): roughly a person
    # ~1.7m tall => root at 0, head ~900mm up, hips ~300mm out, etc.
    base = np.array([
        [0,    0,   0],   # 0 root
        [-100, -400, 0],  # 1 R-hip
        [-100, -800, 0],  # 2 R-knee
        [-100, -1200, 0], # 3 R-ankle
        [100,  -400, 0],  # 4 L-hip
        [100,  -800, 0],  # 5 L-knee
        [100,  -1200, 0], # 6 L-ankle
        [0,    200, 0],   # 7 spine
        [0,    500, 0],   # 8 neck
        [0,    700, 0],   # 9 head
        [200,  520, 0],   # 10 L-shoulder
        [400,  520, 0],   # 11 L-elbow
        [600,  520, 0],   # 12 L-wrist
        [-200, 520, 0],   # 13 R-shoulder
        [-400, 520, 0],   # 14 R-elbow
        [-600, 520, 0],   # 15 R-wrist
        [0,    350, 0],   # 16 thorax
    ], dtype=np.float64)
    seq = (base[None] + rng.normal(0, 5, (4, 17, 3))).astype(np.float64)

    out = expand_h36m17_to_smpl24_mm(seq)
    assert out.shape == (4, 24, 3), out.shape
    # root preserved (mm->m)
    assert np.allclose(out[:, 0, :], seq[:, 0, :] * 1e-3, atol=1e-6)
    # all joints populated
    assert np.all(np.isfinite(out)), "non-finite joint produced"
    # single-frame path
    s = expand_h36m17_to_smpl24_mm(base)
    assert s.shape == (24, 3), s.shape

    print("expand_joints self-check: PASS (17->24 expansion, all joints finite)")
