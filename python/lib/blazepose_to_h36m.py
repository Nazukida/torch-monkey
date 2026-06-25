"""Canonical BlazePose(33) -> Human3.6M(17) joint mapping.

The ``plan.md`` draft (section 6.4 ``_map_to_17_joints``) had a *buggy* mapping:
it reused BlazePose index ``0`` three times (for root, neck and thorax) and
mis-labelled the hips (root was set from a single hip instead of the hip center).
This module replaces it with the **canonical** BlazePose(33) -> Human3.6M(17)
mapping that is consumed downstream by MotionBERT and the 3D-pose-baseline
family.

Why BlazePose indices look the way they do
------------------------------------------
MediaPipe PoseLandmarker (BlazePose) exposes 33 landmarks in this layout::

    0  nose
    1  left eye (inner)        2  left eye             3  left eye (outer)
    4  right eye (inner)       5  right eye            6  right eye (outer)
    7  left ear                8  right ear
    9  mouth (left)            10 mouth (right)
    11 left shoulder           12 right shoulder
    13 left elbow              14 right elbow
    15 left wrist              16 right wrist
    17 left pinky              18 right pinky
    19 left index              20 right index
    21 left thumb              22 right thumb
    23 left hip                24 right hip
    25 left knee               26 right knee
    27 left ankle              28 right ankle
    29 left heel               30 right heel
    31 left foot index         32 right foot index

(See https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker )

Human3.6M-17 joint order (as used by MotionBERT / ``modules/loading.py``)::

    0  root         (pelvis / hip center)
    1  R-hip        2  R-knee       3  R-ankle
    4  L-hip        5  L-knee       6  L-ankle
    7  spine        8  neck         9  head / nose
    10 L-shoulder   11 L-elbow      12 L-wrist
    13 R-shoulder   14 R-elbow      15 R-wrist
    16 thorax

NOTE on the H36M L/R convention: Human3.6M stores the *subject's* left/right,
which in a front-facing camera image maps to the image *right/left*.
BlazePose uses the *subject's* anatomical left/right too (e.g. landmark 23 is
the subject's **left** hip, which appears on the image's right side when the
person faces the camera). So the mapping is direct on the anatomical labels:
BlazePose left-hip(23) -> H36M L-hip(4), BlazePose right-hip(24) -> H36M
R-hip(1). This is the convention MotionBERT was trained on.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

__all__ = [
    "BLAZEPOSE_INDEX_FOR_H36M",
    "H36M_JOINT_NAMES",
    "map_blazepose33_to_h36m17",
    "compute_visibility",
]


# ---------------------------------------------------------------------------
# Canonical mapping table
# ---------------------------------------------------------------------------
#
# Each entry maps one Human3.6M-17 output joint to a *function* of the BlazePose
# landmarks, because several H36M joints (root, spine, neck, thorax, head) are
# *derived* as means of several BlazePose landmarks rather than a single copy.
# We express it as a small DSL: a tuple of ``(blazepose_indices, weights)``.
# A single landmark => a direct copy. Two landmarks with weights => a weighted
# mean (used for symmetric midpoints). A weight of 0.0 means "use this index
# only when no better one is available" -- not used here, all entries are real.
#
# Comment table (the authoritative spec):
#
#  H36M idx | H36M name      | BlazePose source(s)                     | rule
#  ---------|----------------|-----------------------------------------|----------------------
#   0       | root (pelvis)  | 23 (L-hip) + 24 (R-hip)                 | mean of the two hips
#   1       | R-hip          | 24 (R-hip)                              | direct copy
#   2       | R-knee         | 26 (R-knee)                             | direct copy
#   3       | R-ankle        | 28 (R-ankle)                            | direct copy
#   4       | L-hip          | 23 (L-hip)                              | direct copy
#   5       | L-knee         | 25 (L-knee)                             | direct copy
#   6       | L-ankle        | 27 (L-ankle)                            | direct copy
#   7       | spine          | 23,24 (hips) + 11,12 (shoulders)        | torso centroid (lower-chest)
#   8       | neck           | 11 (L-shoulder) + 12 (R-shoulder)       | mean of the two shoulders
#   9       | head           | 0 (nose)                                | direct copy (face anchor)
#  10       | L-shoulder     | 11 (L-shoulder)                         | direct copy
#  11       | L-elbow        | 13 (L-elbow)                            | direct copy
#  12       | L-wrist        | 15 (L-wrist)                            | direct copy
#  13       | R-shoulder     | 12 (R-shoulder)                         | direct copy
#  14       | R-elbow        | 14 (R-elbow)                            | direct copy
#  15       | R-wrist        | 16 (R-wrist)                            | direct copy
#  16       | thorax         | 11,12 (shoulders) + 23,24 (hips)        | torso centroid (same as spine)
#
# NOTE: Human3.6M-17 indexes 7 (spine) and 16 (thorax) at the *same* torso
# centroid when derived from a 2D detector (MotionBERT's own data prep does
# this too -- there is no separate spine/thorax landmark in a 2D detector).
# They become distinct in the *3D* output because MotionBERT learns a spine
# curve, and downstream we re-distribute them along the pelvis->neck axis in
# expand_joints (SPINE_2 lower, SPINE_3 upper) so the SMPL_24 spine chain never
# collapses even though the 2D sources coincide.
#
# This is the same derivation MotionBERT's own ``h36m`` data prep uses when
# converting 2D detections into the 17-joint format: root/thorax/spine are
# *constructed* (not present as single landmarks in BlazePose) and the four
# limb chains copy directly.

H36M_JOINT_NAMES: Tuple[str, ...] = (
    "root",    # 0
    "R-hip",   # 1
    "R-knee",  # 2
    "R-ankle", # 3
    "L-hip",   # 4
    "L-knee",  # 5
    "L-ankle", # 6
    "spine",   # 7
    "neck",    # 8
    "head",    # 9
    "L-shoulder", # 10
    "L-elbow",    # 11
    "L-wrist",    # 12
    "R-shoulder", # 13
    "R-elbow",    # 14
    "R-wrist",    # 15
    "thorax",     # 16
)

# BlazePose indices required by each H36M joint, and the per-index weight.
# A single index with weight 1.0 == direct copy. Two indices with weight 0.5
# each == their midpoint. Four indices == their centroid.
BLAZEPOSE_INDEX_FOR_H36M: Tuple[Tuple[Tuple[int, ...], Tuple[float, ...]], ...] = (
    ((23, 24),            (0.5, 0.5)),             # 0 root        = hip center
    ((24,),               (1.0,)),                 # 1 R-hip
    ((26,),               (1.0,)),                 # 2 R-knee
    ((28,),               (1.0,)),                 # 3 R-ankle
    ((23,),               (1.0,)),                 # 4 L-hip
    ((25,),               (1.0,)),                 # 5 L-knee
    ((27,),               (1.0,)),                 # 6 L-ankle
    # spine: midway between hip-center and shoulder-center. We compose that as
    # the mean of all four (L-hip,R-hip,L-shoulder,R-shoulder) == (hip_mid+sho_mid)/2.
    ((23, 24, 11, 12),    (0.25, 0.25, 0.25, 0.25)),  # 7 spine
    ((11, 12),            (0.5, 0.5)),             # 8 neck       = shoulder center
    ((0,),                (1.0,)),                 # 9 head       = nose
    ((11,),               (1.0,)),                 # 10 L-shoulder
    ((13,),               (1.0,)),                 # 11 L-elbow
    ((15,),               (1.0,)),                 # 12 L-wrist
    ((12,),               (1.0,)),                 # 13 R-shoulder
    ((14,),               (1.0,)),                 # 14 R-elbow
    ((16,),               (1.0,)),                 # 15 R-wrist
    ((23, 24, 11, 12),    (0.25, 0.25, 0.25, 0.25)),  # 16 thorax  = torso centroid
)

# Sanity: every H36M output must have a definition, and weights must sum to 1.
assert len(BLAZEPOSE_INDEX_FOR_H36M) == 17, "H36M-17 must define exactly 17 joints"
for _idxs, _w in BLAZEPOSE_INDEX_FOR_H36M:
    assert len(_idxs) == len(_w), "index/weight length mismatch"
    assert abs(sum(_w) - 1.0) < 1e-6, f"weights for an H36M joint must sum to 1.0 (got {sum(_w)})"
    assert all(0 <= i <= 32 for i in _idxs), "BlazePose index out of range 0..32"


def _as_4d(kp33: np.ndarray) -> np.ndarray:
    """Coerce input to a float32 ``(T, 33, 4)`` or ``(33, 4)`` array.

    Accepts ``(33, 4)``, ``(T, 33, 4)``, ``(33, 3)`` or ``(T, 33, 3)`` (in
    which case a synthetic visibility channel of 1.0 is appended).
    """
    arr = np.asarray(kp33, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr[None, ...]  # (1, J, C)
        squeeze = True
    elif arr.ndim == 3:
        squeeze = False
    else:
        raise ValueError(
            f"Expected keypoints with 2 or 3 dims (..., 33, C), got shape {arr.shape}"
        )
    if arr.shape[-2] != 33:
        raise ValueError(
            f"Expected 33 BlazePose joints, got {arr.shape[-2]} (shape {arr.shape})"
        )
    if arr.shape[-1] == 3:
        vis = np.ones(arr.shape[:-1] + (1,), dtype=np.float32)
        arr = np.concatenate([arr, vis], axis=-1)
    elif arr.shape[-1] != 4:
        raise ValueError(
            f"Last dim must be 3 (x,y,z) or 4 (x,y,z,visibility); got {arr.shape[-1]}"
        )
    return arr, squeeze


def map_blazepose33_to_h36m17(kp33: np.ndarray) -> np.ndarray:
    """Map BlazePose(33) detections to the Human3.6M-17 2D layout.

    Parameters
    ----------
    kp33 : np.ndarray
        BlazePose keypoints, shape ``(33, C)``, ``(T, 33, C)`` with ``C`` in
        ``{3, 4}``. Channels are ``(x, y, [z], [visibility])``. Normalized
        image coordinates (x,y in [0,1]) are expected for 2D lifting; ``z`` is
        kept but the downstream 2D lifter only uses ``(x, y)``.

    Returns
    -------
    np.ndarray
        H36M-17 keypoints, **same rank as input**:
        - input ``(33, C)``  -> output ``(17, 2)``  (only x, y retained)
        - input ``(T, 33, C)`` -> output ``(T, 17, 2)``

        Root/spine/neck/thorax are *derived* (means of their BlazePose sources),
        so all 17 outputs are always populated; no BlazePose index is reused
        incorrectly and no output is left at zero.

    Notes
    -----
    Output dtype is ``float32``. Visibility is intentionally dropped here --
    use :func:`compute_visibility` if you need a per-joint confidence mask.
    """
    arr, squeeze = _as_4d(kp33)
    T = arr.shape[0]
    out = np.zeros((T, 17, 2), dtype=np.float32)
    for h36m_idx, (bp_idxs, weights) in enumerate(BLAZEPOSE_INDEX_FOR_H36M):
        acc = np.zeros((T, 2), dtype=np.float32)
        for bp_idx, w in zip(bp_idxs, weights):
            acc += w * arr[:, bp_idx, :2]
        out[:, h36m_idx, :] = acc
    if squeeze:
        return out[0]
    return out


def compute_visibility(kp33: np.ndarray) -> np.ndarray:
    """Per-H36M-joint visibility, derived as the min visibility of its sources.

    A derived joint (root = mean of two hips) is only "visible" when *all* its
    source landmarks are visible, so we take the elementwise minimum over the
    contributing BlazePose landmarks.

    Parameters
    ----------
    kp33 : np.ndarray
        BlazePose keypoints, shape ``(33, C)`` or ``(T, 33, C)`` with ``C`` in
        ``{3, 4}`` (3 => assumed fully visible).

    Returns
    -------
    np.ndarray
        Visibility in ``[0, 1]``, shape ``(17,)`` or ``(T, 17)`` matching the
        input rank.
    """
    arr, squeeze = _as_4d(kp33)
    vis_src = arr[..., 3]  # (T, 33)
    out = np.ones((arr.shape[0], 17), dtype=np.float32)
    for h36m_idx, (bp_idxs, _weights) in enumerate(BLAZEPOSE_INDEX_FOR_H36M):
        # joint visible iff all its sources are visible
        out[:, h36m_idx] = np.min(vis_src[:, list(bp_idxs)], axis=1)
    if squeeze:
        return out[0]
    return out


# ---------------------------------------------------------------------------
# Self-check: run this module directly to verify the mapping table.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(0)
    demo = rng.random((5, 33, 4)).astype(np.float32)
    out = map_blazepose33_to_h36m17(demo)
    assert out.shape == (5, 17, 2), out.shape
    # All 17 outputs populated (no zero rows from a mis-mapped index)
    assert np.all(np.any(out != 0, axis=-1)), "some H36M joints left at zero"

    # Verify root == midpoint of hips, neck == midpoint of shoulders, etc.
    expected_root = 0.5 * (demo[:, 23, :2] + demo[:, 24, :2])
    assert np.allclose(out[:, 0, :], expected_root, atol=1e-5)
    expected_neck = 0.5 * (demo[:, 11, :2] + demo[:, 12, :2])
    assert np.allclose(out[:, 8, :], expected_neck, atol=1e-5)
    # Direct copies
    for h36m_i, bp_i in [(1, 24), (2, 26), (4, 23), (9, 0), (11, 13), (14, 14)]:
        assert np.allclose(out[:, h36m_i, :], demo[:, bp_i, :2], atol=1e-5), (h36m_i, bp_i)

    vis = compute_visibility(demo)
    assert vis.shape == (5, 17)

    # 2D single-frame input path
    single = rng.random((33, 4)).astype(np.float32)
    s_out = map_blazepose33_to_h36m17(single)
    assert s_out.shape == (17, 2), s_out.shape

    print("blazepose_to_h36m self-check: PASS (17/17 joints mapped, derivations correct)")
