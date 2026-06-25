"""Torch Monkey SMPL-24 skeleton definition -- single source of truth.

This module is the canonical, importable definition of the 24-joint
``smpl_24`` skeleton used everywhere on the Python side:

* joint names and indices,
* the parent of every joint (``-1`` for the root),
* the T-pose rest joint positions (meters, Y-up, character faces ``+Z``),
* the upper-body joint set used for *kime* (キメ) detection,
* the joints the glowsticks (荧光棒) are bound to.

Other modules (:mod:`lib.forward_kinematics`, :mod:`pipeline.ik_solver`,
:mod:`pipeline.wotagei_optimizer`, :mod:`pipeline.format_exporter`,
:mod:`tools.selftest_pipeline`) all read these constants from here.

The values are copied verbatim from the Torch Monkey project brief and are kept
in sync with ``shared/constants/skeleton.ts`` on the TypeScript side. Treat this
file as authoritative: if the skeleton changes, change it here first.

Coordinate convention
---------------------
* **Y-up, meters**, character faces ``+Z`` (forward).
* Rest pose is a T-pose with the root (PELVIS) near ``(0, 0.9, 0)``.
* Local bone rotations produced downstream are applied to each joint's
  *incoming* bone (the bone that runs ``parent -> joint``), relative to the
  parent's frame.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

__all__ = [
    "SMPL24_NAMES",
    "SMPL24_PARENTS",
    "SMPL24_REST_POSE",
    "UPPER_BODY_JOINTS",
    "GLOWSTICK_JOINTS",
    "NUM_JOINTS",
    "SMPL24Name",
    "smpl24_index",
    "smpl24_children",
]

# ---------------------------------------------------------------------------
# Joint names, in index order.
# ---------------------------------------------------------------------------
SMPL24_NAMES: Tuple[str, ...] = (
    "PELVIS",       #  0
    "L_HIP",        #  1
    "R_HIP",        #  2
    "SPINE_1",      #  3
    "L_KNEE",       #  4
    "R_KNEE",       #  5
    "SPINE_2",      #  6
    "L_ANKLE",      #  7
    "R_ANKLE",      #  8
    "SPINE_3",      #  9
    "L_FOOT",       # 10
    "R_FOOT",       # 11
    "NECK",         # 12
    "L_COLLAR",     # 13
    "R_COLLAR",     # 14
    "HEAD",         # 15
    "L_SHOULDER",   # 16
    "R_SHOULDER",   # 17
    "L_ELBOW",      # 18
    "R_ELBOW",      # 19
    "L_WRIST",      # 20
    "R_WRIST",      # 21
    "L_HAND",       # 22
    "R_HAND",       # 23
)
"""Display names of the 24 joints, indexed by joint index."""

SMPL24Name = str  # convenience alias for type hints referring to joint names

# ---------------------------------------------------------------------------
# Parent index per joint (-1 == root).
# ---------------------------------------------------------------------------
SMPL24_PARENTS: Tuple[int, ...] = (
    -1,  #  0 PELVIS    (root)
    0,   #  1 L_HIP      <- PELVIS
    0,   #  2 R_HIP      <- PELVIS
    0,   #  3 SPINE_1    <- PELVIS
    1,   #  4 L_KNEE     <- L_HIP
    2,   #  5 R_KNEE     <- R_HIP
    3,   #  6 SPINE_2    <- SPINE_1
    4,   #  7 L_ANKLE    <- L_KNEE
    5,   #  8 R_ANKLE    <- R_KNEE
    6,   #  9 SPINE_3    <- SPINE_2
    7,   # 10 L_FOOT     <- L_ANKLE
    8,   # 11 R_FOOT     <- R_ANKLE
    9,   # 12 NECK       <- SPINE_3
    9,   # 13 L_COLLAR   <- SPINE_3
    9,   # 14 R_COLLAR   <- SPINE_3
    12,  # 15 HEAD       <- NECK
    13,  # 16 L_SHOULDER <- L_COLLAR
    14,  # 17 R_SHOULDER <- R_COLLAR
    16,  # 18 L_ELBOW    <- L_SHOULDER
    17,  # 19 R_ELBOW    <- R_SHOULDER
    18,  # 20 L_WRIST    <- L_ELBOW
    19,  # 21 R_WRIST    <- R_ELBOW
    20,  # 22 L_HAND     <- L_WRIST
    21,  # 23 R_HAND     <- R_WRIST
)
"""Parent joint index per joint. ``SMPL24_PARENTS[0] == -1`` marks the root."""

NUM_JOINTS: int = len(SMPL24_NAMES)  # 24


# ---------------------------------------------------------------------------
# T-pose rest joint positions (meters, Y-up, faces +Z), verbatim from brief.
# ---------------------------------------------------------------------------
SMPL24_REST_POSE: np.ndarray = np.array(
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
"""T-pose rest joint positions, shape ``(24, 3)``, meters, Y-up, faces +Z.

The array is read-only via :func:`np.asarray` copies made by callers; mutating
it in place would silently corrupt every downstream module, so do not.
"""

# Defensive: freeze the rest pose so an accidental in-place edit fails loudly.
SMPL24_REST_POSE.setflags(write=False)


# ---------------------------------------------------------------------------
# Joint sets of interest.
# ---------------------------------------------------------------------------
#: Upper-body joints used for *kime* detection: shoulders, elbows, wrists, hands.
UPPER_BODY_JOINTS: Tuple[int, ...] = (16, 17, 18, 19, 20, 21, 22, 23)

#: Joints the glowsticks are bound to (left hand, right hand).
GLOWSTICK_JOINTS: Tuple[int, ...] = (22, 23)


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------
def smpl24_index(name: str) -> int:
    """Return the joint index for a joint ``name``.

    Parameters
    ----------
    name : str
        Case-sensitive joint name, e.g. ``"L_HAND"``.

    Raises
    ------
    KeyError
        If ``name`` is not a known SMPL-24 joint.
    """
    return SMPL24_NAMES.index(name)


def smpl24_children() -> List[List[int]]:
    """Return, for every joint, the sorted list of its direct children."""
    children: List[List[int]] = [[] for _ in range(NUM_JOINTS)]
    for j, p in enumerate(SMPL24_PARENTS):
        if p >= 0:
            children[p].append(j)
    return children


def _self_check() -> None:
    """Sanity-check the constants at import/build time (no external deps)."""
    assert len(SMPL24_NAMES) == NUM_JOINTS == 24
    assert len(SMPL24_PARENTS) == NUM_JOINTS
    assert SMPL24_PARENTS[0] == -1, "PELVIS must be the root"
    assert SMPL24_REST_POSE.shape == (NUM_JOINTS, 3)
    # parents always precede children (topological sanity)
    for j, p in enumerate(SMPL24_PARENTS):
        assert p < j, f"joint {j} has parent {p} >= itself (cycle/order)"
    # the rest pose has the root near (0, 0.9, 0) per brief
    assert abs(SMPL24_REST_POSE[0, 1] - 0.90) < 1e-9


_self_check()
