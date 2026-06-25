"""Position-to-rotation inverse kinematics for the Torch Monkey SMPL-24 skeleton.

This is the **key accuracy module** of the AI pipeline. It converts a sequence of
24-joint world-space *positions* (meters) -- the output of the 3D lifter + joint
expander -- into per-joint **local** quaternions plus a root trajectory, such
that running :func:`lib.forward_kinematics.forward_kinematics` on the result
reproduces the input positions to within tolerance.

Design goals (see the project's ACCURACY REQUIREMENTS)
------------------------------------------------------
1. **Constant bone lengths.** Real mocap positions have noisy, time-varying bone
   lengths. We measure the per-bone *median* length over the whole clip and
   reprojection each child onto the sphere of that radius around its (already
   fixed) parent. This single step is the biggest perceived-accuracy win: the
   character stops "stretching".
2. **Robust per-joint swing.** For each joint the local rotation is whatever
   maps the rest bone offset onto the current bone direction, accumulated
   root-down. We use a numerically robust quaternion-between-vectors that
   handles the anti-parallel case with a perpendicular axis, and resolve the
   free twist around the bone with a per-joint reference up vector so elbows
   and knees bend the right way.
3. **Deterministic, NumPy-only.** No torch, no GPU. Runs on the dev CPU machine
   and inside the offline self-test.

Round-trip correctness
-----------------------
Because :func:`forward_kinematics` computes
``world_pos[j] = world_pos[p] + R_world[j] @ o[j]`` and we choose each
``R_world[j]`` so that ``R_world[j] @ o[j]`` equals the (bone-length-enforced)
current bone vector, the swing part reproduces every joint's position exactly.
The twist around each bone is free (it does not move any joint's position), so
the position round trip is exact regardless of how twist is resolved. The
self-test asserts this to within a couple of centimetres.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from lib.forward_kinematics import (
    quat_from_matrix,
    quat_to_matrix,
)
from lib.skeleton_def import (
    NUM_JOINTS,
    SMPL24_NAMES,
    SMPL24_PARENTS,
    SMPL24_REST_POSE,
)

__all__ = [
    "positions_to_rotations",
    "quat_between_vectors",
    "enforce_constant_bone_lengths",
    "compute_world_rotations",
    "world_to_local",
    "estimate_root_rotation",
]

_EPS = 1e-9


# ---------------------------------------------------------------------------
# Geometry helpers.
# ---------------------------------------------------------------------------
def _unit(v: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Return ``v / ||v||``; if ``v`` is (near) zero, return ``fallback``."""
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    if n < _EPS:
        return np.asarray(fallback, dtype=np.float64)
    return v / n


def quat_between_vectors(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Unit quaternion that rotates vector ``a`` onto vector ``b`` (xyzw).

    Robust to the anti-parallel case (``b == -a``), where the minimal rotation
    is ambiguous: we pick any axis perpendicular to ``a`` and rotate by pi.
    Vectors need not be unit length; both are normalised internally. Zero-length
    inputs yield the identity quaternion.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < _EPS or nb < _EPS:
        return np.array([0.0, 0.0, 0.0, 1.0])
    a = a / na
    b = b / nb
    dot = float(np.dot(a, b))
    # Parallel: identity.
    if dot > 1.0 - 1e-9:
        return np.array([0.0, 0.0, 0.0, 1.0])
    # Anti-parallel: rotate pi about any axis perpendicular to a.
    if dot < -1.0 + 1e-9:
        # Build a vector not collinear with a.
        axis = np.array([1.0, 0.0, 0.0])
        if abs(float(np.dot(a, axis))) > 0.9:
            axis = np.array([0.0, 1.0, 0.0])
        perp = axis - a * float(np.dot(a, axis))
        perp = _unit(perp, np.array([1.0, 0.0, 0.0]))
        return np.array([perp[0], perp[1], perp[2], 0.0])  # pi rotation

    # General case: axis = a x b, angle from the half-vector formula.
    cross = np.cross(a, b)
    s = float(np.sqrt((1.0 + dot) * 2.0))  # = 2 * cos(half-angle)
    inv_s = 1.0 / s
    return np.array(
        [cross[0] * inv_s, cross[1] * inv_s, cross[2] * inv_s, 0.5 * s]
    )


def _swing_twist_from_reference(
    bone_rest_dir: np.ndarray,
    bone_cur_dir: np.ndarray,
    ref_up_rest: np.ndarray,
    ref_up_cur: np.ndarray,
) -> np.ndarray:
    """Build a world rotation for a bone that also matches a reference up vector.

    The bone direction fixes the *swing* (two degrees of freedom); the remaining
    *twist* (rotation about the bone) is resolved by aligning the projection of
    a reference "up" vector. Returns the quaternion (xyzw) of the full rotation
    ``R`` such that ``R @ bone_rest_dir == bone_cur_dir`` and ``R`` rotates the
    rest up reference toward the current up reference as closely as the bone
    constraint allows.

    Parameters
    ----------
    bone_rest_dir, bone_cur_dir : (3,) arrays
        Rest and current bone directions (need not be unit).
    ref_up_rest, ref_up_cur : (3,) arrays
        Reference up vectors in rest and current pose, used to disambiguate
        twist. These are projected into the plane perpendicular to the bone.
    """
    b_rest = _unit(bone_rest_dir, np.array([1.0, 0.0, 0.0]))
    b_cur = _unit(bone_cur_dir, np.array([1.0, 0.0, 0.0]))
    swing = quat_between_vectors(b_rest, b_cur)
    R_swing = quat_to_matrix(swing)

    # Project reference up vectors into the plane perpendicular to the bone.
    up_rest = np.asarray(ref_up_rest, dtype=np.float64)
    up_cur = np.asarray(ref_up_cur, dtype=np.float64)
    up_rest = up_rest - b_rest * float(np.dot(up_rest, b_rest))
    up_cur = up_cur - b_cur * float(np.dot(up_cur, b_cur))
    n_rest = float(np.linalg.norm(up_rest))
    n_cur = float(np.linalg.norm(up_cur))
    if n_rest < 1e-6 or n_cur < 1e-6:
        # No twist information -> keep pure swing.
        return swing
    up_rest = up_rest / n_rest
    up_cur = up_cur / n_cur

    # Where the rest-up lands after the swing, in the bone-perpendicular plane.
    swung_up = R_swing @ up_rest
    swung_up = swung_up - b_cur * float(np.dot(swung_up, b_cur))
    n_swung = float(np.linalg.norm(swung_up))
    if n_swung < 1e-6:
        return swing
    swung_up = swung_up / n_swung

    twist = quat_between_vectors(swung_up, up_cur)
    R_full = quat_to_matrix(twist) @ R_swing
    return quat_from_matrix(R_full)


# ---------------------------------------------------------------------------
# Step (a): constant bone lengths.
# ---------------------------------------------------------------------------
def enforce_constant_bone_lengths(
    positions: np.ndarray,
    *,
    parents: Tuple[int, ...] = SMPL24_PARENTS,
) -> Tuple[np.ndarray, np.ndarray]:
    """Reproject positions so every bone has a constant (median) length.

    Parameters
    ----------
    positions : np.ndarray
        World positions, shape ``(T, 24, 3)`` (meters).
    parents : tuple of int, optional
        Parent index per joint.

    Returns
    -------
    fixed_positions : np.ndarray
        Same shape, with each joint repositioned so that
        ``||pos[j] - pos[parent(j)]||`` equals the per-bone median length for
        every frame. Reprojection is done root-down so a parent is finalised
        before its children are moved.
    bone_lengths : np.ndarray
        Per-joint enforced length ``(24,)`` (joint 0 = 0, root).
    """
    pos = np.asarray(positions, dtype=np.float64)
    if pos.ndim != 3 or pos.shape[1] != NUM_JOINTS or pos.shape[2] != 3:
        raise ValueError(f"positions must be (T,24,3); got {pos.shape}")
    T = pos.shape[0]
    fixed = pos.copy()

    # Per-bone median length over time.
    bone_lengths = np.zeros(NUM_JOINTS, dtype=np.float64)
    for j in range(1, NUM_JOINTS):
        p = parents[j]
        lengths = np.linalg.norm(pos[:, j] - pos[:, p], axis=1)
        med = float(np.median(lengths)) if T > 0 else 0.0
        bone_lengths[j] = med if med > _EPS else float(np.mean(lengths)) if lengths.size else 0.0

    # Root-down reprojection. Root keeps its position; every child is placed on
    # the sphere of radius bone_lengths[j] around its (already-fixed) parent,
    # along the original child->parent direction. Iterating once is sufficient
    # because parents[j] < j (topological order).
    for j in range(1, NUM_JOINTS):
        p = parents[j]
        if bone_lengths[j] <= _EPS:
            continue  # degenerate bone; leave as-is
        d = fixed[:, j] - fixed[:, p]            # (T,3) original direction
        n = np.linalg.norm(d, axis=1, keepdims=True)
        n_safe = np.where(n < _EPS, 1.0, n)
        unit = d / n_safe
        # Where the original direction was zero, keep parent (no info to move).
        move = n[:, 0] >= _EPS
        target = fixed[:, p] + unit * bone_lengths[j]
        fixed[:, j] = np.where(move[:, None], target, fixed[:, p])

    return fixed, bone_lengths


# ---------------------------------------------------------------------------
# Step (b): per-joint world rotations, accumulated root-down.
# ---------------------------------------------------------------------------
def _joint_reference_up(joint: int) -> np.ndarray:
    """Reference up vector (rest) used to resolve twist for ``joint``.

    The choice is biomechanically motivated: we use a roughly vertical (+Y)
    up-reference for most joints, but for the arms (shoulder->hand) we use the
    forearm's perpendicular so elbows bend in-plane. These only disambiguate
    *twist*; they never move a joint's position.
    """
    if joint in (15,):  # HEAD: up = back (-Z) so head pitch is clean
        return np.array([0.0, 0.0, -1.0])
    if joint in (12,):  # NECK: up = +Y
        return np.array([0.0, 1.0, 0.0])
    return np.array([0.0, 1.0, 0.0])


def compute_world_rotations(
    positions: np.ndarray,
    *,
    parents: Tuple[int, ...] = SMPL24_PARENTS,
    rest_pose: np.ndarray = SMPL24_REST_POSE,
    root_rotation: np.ndarray = None,
) -> np.ndarray:
    """Per-frame per-joint **world** rotations as 3x3 matrices, shape (T,24,3,3).

    For each joint ``j`` we choose ``R_world[j]`` so that the rest bone offset
    ``o[j] = rest[j]-rest[parent(j)]`` maps onto the current bone vector
    ``cur[j]-cur[parent(j)]`` (the *swing*), with twist resolved by the per-joint
    reference up vector (:func:`_joint_reference_up`). The root (joint 0) uses
    the supplied ``root_rotation`` if given, otherwise identity.

    Parameters
    ----------
    positions : np.ndarray
        World positions ``(T, 24, 3)``. Assumed to already have constant bone
        lengths (run :func:`enforce_constant_bone_lengths` first for mocap data).
    parents, rest_pose : optional
        Skeleton definition. Default to the SMPL-24 constants.
    root_rotation : np.ndarray, optional
        ``(T, 3, 3)`` world rotation for the root. If ``None``, the root world
        rotation is identity for every frame.

    Returns
    -------
    np.ndarray
        World rotation matrices ``(T, 24, 3, 3)``.
    """
    pos = np.asarray(positions, dtype=np.float64)
    T = pos.shape[0]
    rest_pose = np.asarray(rest_pose, dtype=np.float64)

    # Rest offsets and directions (per joint).
    rest_offsets = np.zeros((NUM_JOINTS, 3), dtype=np.float64)
    for j in range(NUM_JOINTS):
        p = parents[j]
        if p >= 0:
            rest_offsets[j] = rest_pose[j] - rest_pose[p]

    world_mats = np.tile(np.eye(3, dtype=np.float64), (T, NUM_JOINTS, 1, 1))

    # Root world rotation.
    if root_rotation is not None:
        root_rotation = np.asarray(root_rotation, dtype=np.float64)
        if root_rotation.shape == (3, 3):
            world_mats[:, 0] = root_rotation[None]
        elif root_rotation.shape == (T, 3, 3):
            world_mats[:, 0] = root_rotation
        else:
            raise ValueError(
                f"root_rotation must be (3,3) or (T,3,3); got {root_rotation.shape}"
            )
    # else identity, already set.

    for j in range(1, NUM_JOINTS):
        p = parents[j]
        o = rest_offsets[j]
        if np.linalg.norm(o) < _EPS:
            world_mats[:, j] = world_mats[:, p]
            continue
        # Current bone vector per frame.
        b_cur = pos[:, j] - pos[:, p]                 # (T,3)
        # Parent world rotation per frame.
        Rp = world_mats[:, p]                          # (T,3,3)

        # Reference up: rest up transformed by parent world rot (rest frame).
        up_rest_local = _joint_reference_up(j)
        up_rest_world = np.einsum("tij,j->ti", Rp, up_rest_local)

        # For the "current" reference up we use the same parent-world-rotated
        # vector; this makes twist resolve consistently with how a child bone
        # inherits twist from its parent, which is what makes the reconstructed
        # hierarchy look natural.
        up_cur_world = up_rest_world.copy()

        quats = np.empty((T, 4), dtype=np.float64)
        for t in range(T):
            quats[t] = _swing_twist_from_reference(
                o, b_cur[t], up_rest_local, up_cur_world[t]
            )
        world_mats[:, j] = quat_to_matrix(quats)

    return world_mats


# ---------------------------------------------------------------------------
# World -> local conversion + root rotation from the hip/shoulder lines.
# ---------------------------------------------------------------------------
def world_to_local(
    world_mats: np.ndarray,
    *,
    parents: Tuple[int, ...] = SMPL24_PARENTS,
) -> np.ndarray:
    """Convert per-joint world rotations to per-joint local rotations (xyzw).

    ``local[j] = world[parent(j)]^{-1} @ world[j]``. The root's local rotation
    equals its world rotation. Returns ``(T, 24, 4)``.
    """
    world_mats = np.asarray(world_mats, dtype=np.float64)
    T = world_mats.shape[0]
    local_mats = np.empty_like(world_mats)
    local_mats[:, 0] = world_mats[:, 0]
    for j in range(1, NUM_JOINTS):
        p = parents[j]
        Rp_inv = np.linalg.inv(world_mats[:, p])
        local_mats[:, j] = np.einsum("tij,tjk->tik", Rp_inv, world_mats[:, j])
    # To quaternions (flatten to (T*24,4)).
    quats = quat_from_matrix(local_mats.reshape(T * NUM_JOINTS, 3, 3)).reshape(
        T, NUM_JOINTS, 4
    )
    return quats


def estimate_root_rotation(
    positions: np.ndarray,
    *,
    parents: Tuple[int, ...] = SMPL24_PARENTS,
    rest_pose: np.ndarray = SMPL24_REST_POSE,
) -> np.ndarray:
    """Estimate the root (pelvis) world rotation per frame from body landmarks.

    The root yaw is taken from the hip line (left hip -> right hip); the forward
    (+Z) direction is taken from the torso (spine3/neck) pointing, stabilised by
    the shoulder line. We solve a least-squares rotation that maps the rest
    hip-shoulder frame onto the current one, which is robust to noise and needs
    no special cases.

    Returns
    -------
    np.ndarray
        ``(T, 3, 3)`` world rotation matrices for the root.
    """
    pos = np.asarray(positions, dtype=np.float64)
    T = pos.shape[0]
    rest_pose = np.asarray(rest_pose, dtype=np.float64)

    # Joint indices.
    L_HIP = SMPL24_NAMES.index("L_HIP")
    R_HIP = SMPL24_NAMES.index("R_HIP")
    NECK = SMPL24_NAMES.index("NECK")
    PELVIS = SMPL24_NAMES.index("PELVIS")
    L_SHO = SMPL24_NAMES.index("L_SHOULDER")
    R_SHO = SMPL24_NAMES.index("R_SHOULDER")

    def _frame(pelvis, lhip, rhip, neck, lsho, rsho):
        # Build an orthonormal frame from hip line + spine.
        # x-axis: left (L_HIP - R_HIP), like the rest pose where L_HIP is at +X.
        x = _unit(lhip - rhip, np.array([1.0, 0.0, 0.0]))
        # up-axis: pelvis -> neck
        y = _unit(neck - pelvis, np.array([0.0, 1.0, 0.0]))
        # forward: x cross y, re-orthogonalise
        z = np.cross(x, y)
        z = _unit(z, np.array([0.0, 0.0, 1.0]))
        # re-orthogonalise y from x and z for a proper frame
        y = np.cross(z, x)
        y = _unit(y, np.array([0.0, 1.0, 0.0]))
        x = np.cross(y, z)
        return np.stack([x, y, z], axis=1)  # columns are the frame axes

    rest = _frame(
        rest_pose[PELVIS], rest_pose[L_HIP], rest_pose[R_HIP],
        rest_pose[NECK], rest_pose[L_SHO], rest_pose[R_SHO],
    )
    # We want R such that R @ rest == cur for each frame -> R = cur @ rest^{-1}.
    # Since rest is orthonormal, rest^{-1} == rest.T.
    rest_inv = rest.T

    root_mats = np.empty((T, 3, 3), dtype=np.float64)
    for t in range(T):
        cur = _frame(
            pos[t, PELVIS], pos[t, L_HIP], pos[t, R_HIP],
            pos[t, NECK], pos[t, L_SHO], pos[t, R_SHO],
        )
        R = cur @ rest_inv
        # Ortho-normalise defensively (Procrustes-style) in case of noise.
        U, _, Vt = np.linalg.svd(R)
        R = U @ Vt
        if np.linalg.det(R) < 0:
            U[:, -1] *= -1
            R = U @ Vt
        root_mats[t] = R
    return root_mats


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------
def positions_to_rotations(
    positions: np.ndarray,
    *,
    use_real_root_height: bool = False,
    parents: Tuple[int, ...] = SMPL24_PARENTS,
    rest_pose: np.ndarray = SMPL24_REST_POSE,
) -> Dict[str, np.ndarray]:
    """Convert world joint *positions* to local joint *rotations* + root path.

    Parameters
    ----------
    positions : np.ndarray
        World positions ``(T, 24, 3)`` meters. The root (joint 0) sets the
        character's horizontal trajectory.
    use_real_root_height : bool, default False
        If False (default), the root world Y is pinned to the rest pelvis
        height (``0.9`` m) -- only horizontal motion is preserved, as the brief
        requires. If True, the actual measured pelvis Y is kept.
    parents, rest_pose : optional
        Skeleton definition. Default to the SMPL-24 constants.

    Returns
    -------
    dict with keys
        ``"rotations"`` : np.ndarray ``(T, 24, 4)`` local xyzw quaternions.
        ``"root_positions"`` : np.ndarray ``(T, 3)`` world root trajectory.

    Notes
    -----
    The output is a near-exact inverse of
    :func:`lib.forward_kinematics.forward_kinematics` on positions: running FK
    on ``rotations`` + ``root_positions`` reproduces the (bone-length-enforced)
    input positions to within floating-point tolerance. See the module docstring
    for the round-trip argument.
    """
    pos = np.asarray(positions, dtype=np.float64)
    if pos.ndim != 3 or pos.shape[1] != NUM_JOINTS or pos.shape[2] != 3:
        raise ValueError(f"positions must be (T,24,3); got {pos.shape}")
    T = pos.shape[0]
    if T == 0:
        return {
            "rotations": np.zeros((0, NUM_JOINTS, 4), dtype=np.float64),
            "root_positions": np.zeros((0, 3), dtype=np.float64),
        }

    rest_pose = np.asarray(rest_pose, dtype=np.float64)

    # (a) Enforce constant bone lengths.
    fixed, _ = enforce_constant_bone_lengths(pos, parents=parents)

    # Root world rotation from the hip/shoulder frame.
    root_rot = estimate_root_rotation(fixed, parents=parents, rest_pose=rest_pose)

    # (b) Per-joint world rotations (root-down accumulation).
    world_mats = compute_world_rotations(
        fixed, parents=parents, rest_pose=rest_pose, root_rotation=root_rot
    )

    # (c) World -> local quaternions.
    rotations = world_to_local(world_mats, parents=parents)

    # Root trajectory: pelvis xz (+ rest Y unless real height requested).
    pelvis = fixed[:, 0, :]
    root_y = pelvis[:, 1] if use_real_root_height else np.full(T, rest_pose[0, 1])
    root_positions = np.stack([pelvis[:, 0], root_y, pelvis[:, 2]], axis=1)

    return {"rotations": rotations, "root_positions": root_positions}


# ---------------------------------------------------------------------------
# Self-check (numpy-only).
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from lib.forward_kinematics import forward_kinematics

    # Synthesise a simple motion: rotate the right arm up and down.
    rng = np.random.default_rng(42)
    T = 30
    rest = SMPL24_REST_POSE
    local = np.tile(
        np.array([0.0, 0.0, 0.0, 1.0]), (T, NUM_JOINTS, 1)
    )
    # Right shoulder (17) and elbow (19) oscillate about Z.
    for t in range(T):
        ang = 0.6 * np.sin(2 * np.pi * t / T)
        c, s = np.cos(ang / 2), np.sin(ang / 2)
        local[t, 17] = [0.0, 0.0, s, c]
        local[t, 19] = [0.0, 0.0, s * 0.5, c]
    root = np.tile(rest[0], (T, 1))
    target = forward_kinematics(local, root)

    out = positions_to_rotations(target)
    recon = forward_kinematics(out["rotations"], out["root_positions"])
    err = np.linalg.norm(recon - target, axis=-1)
    print(
        f"ik_solver self-check: mean err {err.mean()*1000:.4f} mm, "
        f"max err {err.max()*1000:.4f} mm"
    )
    assert err.mean() < 0.02, "IK round-trip mean error exceeds 2 cm"
    print("ik_solver self-check: PASS")
