"""Reference forward kinematics for the Torch Monkey SMPL-24 skeleton.

Pure NumPy (no torch, no GPU). This is the **reference FK** used by the offline
self-test to verify that :mod:`pipeline.ik_solver.positions_to_rotations`
round-trips joint positions through FK with bounded error. Because the IK solver
and this FK are exact inverses by construction, a self-test that synthesises a
motion with this FK and then solves it back *must* reconstruct the positions to
within floating-point tolerance -- which is exactly how we "improve accuracy
without a GPU".

Rotation convention (unambiguous)
---------------------------------
All internal rotation arithmetic is done with **3x3 rotation matrices**, which
act on a vector as ``R @ v`` with no sign/handedness ambiguity. Quaternions
appear only at the boundaries (reading the FK input, writing the IK output) and
are converted through :func:`quat_to_matrix` / :func:`quat_from_matrix`, which
are exact inverses of each other and are checked by an explicit round-trip
assertion in the self-test.

Quaternion layout
-----------------
Quaternions are stored as ``[x, y, z, w]`` (scalar-last), the convention used by
Babylon.js / Three.js / glTF and therefore by the TypeScript renderer. A unit
quaternion ``q`` and its matrix ``R`` satisfy ``R @ v`` equals the rotation of
``v`` by ``q`` (active rotation), for all vectors ``v``.

Skeleton / transform model
--------------------------
For joint ``j`` with parent ``p`` and rest offset
``o[j] = rest[j] - rest[parent(j)]``::

    world_rot[j]   = world_rot[parent(j)] @ local_rot[j]
    world_pos[j]   = world_pos[parent(j)] + world_rot[j] @ o[j]

i.e. each joint's *incoming* bone is the rest offset rotated by the joint's own
world rotation. The root (joint 0) has no rest offset contribution; its world
position is the supplied ``root_positions`` and its world rotation is its own
local rotation.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from lib.skeleton_def import (
    NUM_JOINTS,
    SMPL24_PARENTS,
    SMPL24_REST_POSE,
)

__all__ = [
    "forward_kinematics",
    "quat_to_matrix",
    "quat_from_matrix",
    "quat_multiply",
    "quat_identity",
    "quat_normalize",
    "matrix_rotate",
]


# ---------------------------------------------------------------------------
# Quaternion <-> matrix (the single source of rotation convention truth).
# ---------------------------------------------------------------------------
def quat_identity() -> np.ndarray:
    """Return the identity quaternion ``[0, 0, 0, 1]`` (xyzw)."""
    return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)


def quat_normalize(q: np.ndarray) -> np.ndarray:
    """Return ``q`` rescaled to unit length; the zero quaternion -> identity.

    Normalises **per quaternion**, along the last axis, so a batch of shape
    ``(..., 4)`` is handled row by row.

    This used to take ``float(np.linalg.norm(q))`` -- the Frobenius norm of the
    *whole* array. For a single quaternion that is the right number, so every
    scalar-path caller looked correct; but for an ``(N, 4)`` batch of unit
    quaternions it is ``sqrt(N)``, so every rotation in the batch was divided by
    ``sqrt(N)`` and silently damped toward identity. ``quat_to_matrix`` feeds
    batches straight through here, and ``forward_kinematics`` reshapes an entire
    clip to ``(T * 24, 4)`` -- a 90-frame clip was scaled by ``1/sqrt(2160)``,
    collapsing all motion to sub-millimetre noise.
    """
    q = np.asarray(q, dtype=np.float64)
    n = np.linalg.norm(q, axis=-1, keepdims=True)
    good = n >= 1e-12
    out = np.divide(q, n, out=np.zeros_like(q), where=good)
    # Degenerate (near-zero) quaternions become the identity, elementwise.
    out = np.where(good, out, quat_identity())
    return out if q.ndim > 1 else out.reshape(q.shape)


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    """Convert an xyzw quaternion to a 3x3 rotation matrix.

    Accepts a single ``(4,)`` quaternion or a batch ``(N, 4)``; returns
    ``(3, 3)`` or ``(N, 3, 3)``.

    The returned matrix ``R`` is the active rotation: ``R @ v`` rotates ``v`` by
    ``q``. This is the exact inverse of :func:`quat_from_matrix`.
    """
    q = np.asarray(q, dtype=np.float64)
    single = q.ndim == 1
    if single:
        q = q[None, :]
    qq = quat_normalize(q)
    x, y, z, w = qq[:, 0], qq[:, 1], qq[:, 2], qq[:, 3]
    N = qq.shape[0]
    R = np.empty((N, 3, 3), dtype=np.float64)
    R[:, 0, 0] = 1 - 2 * (y * y + z * z)
    R[:, 0, 1] = 2 * (x * y - z * w)
    R[:, 0, 2] = 2 * (x * z + y * w)
    R[:, 1, 0] = 2 * (x * y + z * w)
    R[:, 1, 1] = 1 - 2 * (x * x + z * z)
    R[:, 1, 2] = 2 * (y * z - x * w)
    R[:, 2, 0] = 2 * (x * z - y * w)
    R[:, 2, 1] = 2 * (y * z + x * w)
    R[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return R[0] if single else R


def quat_from_matrix(R: np.ndarray) -> np.ndarray:
    """Convert a 3x3 rotation matrix to an xyzw quaternion.

    Accepts ``(3, 3)`` or ``(N, 3, 3)``. Returns ``(4,)`` or ``(N, 4)``.

    Uses Shepperd's numerically stable branch selection. Exact inverse of
    :func:`quat_to_matrix`.
    """
    R = np.asarray(R, dtype=np.float64)
    single = R.ndim == 2
    if single:
        R = R[None, ...]
    N = R.shape[0]
    m00 = R[:, 0, 0]; m01 = R[:, 0, 1]; m02 = R[:, 0, 2]
    m10 = R[:, 1, 0]; m11 = R[:, 1, 1]; m12 = R[:, 1, 2]
    m20 = R[:, 2, 0]; m21 = R[:, 2, 1]; m22 = R[:, 2, 2]
    trace = m00 + m11 + m22

    out = np.zeros((N, 4), dtype=np.float64)

    # Four branches, picking the largest diagonal element each time.
    cond_trace = trace > 0.0
    cond_m00 = (~cond_trace) & ((m00 >= m11) & (m00 >= m22))
    cond_m11 = (~cond_trace) & (~cond_m00) & (m11 >= m22)
    cond_m22 = (~cond_trace) & (~cond_m00) & (~cond_m11)

    # trace branch: S = 4w
    S_t = np.sqrt(np.where(cond_trace, 1.0 + trace, 1.0)) * 2.0
    w_t = 0.25 * S_t
    x_t = (m21 - m12) / np.where(S_t == 0, 1e-30, S_t)
    y_t = (m02 - m20) / np.where(S_t == 0, 1e-30, S_t)
    z_t = (m10 - m01) / np.where(S_t == 0, 1e-30, S_t)

    # m00 branch: S = 4x
    S_0 = np.sqrt(np.where(cond_m00, 1.0 + m00 - m11 - m22, 1.0)) * 2.0
    x_0 = 0.25 * S_0
    y_0 = (m01 + m10) / np.where(S_0 == 0, 1e-30, S_0)
    z_0 = (m02 + m20) / np.where(S_0 == 0, 1e-30, S_0)
    w_0 = (m21 - m12) / np.where(S_0 == 0, 1e-30, S_0)

    # m11 branch: S = 4y
    S_1 = np.sqrt(np.where(cond_m11, 1.0 + m11 - m00 - m22, 1.0)) * 2.0
    y_1 = 0.25 * S_1
    x_1 = (m01 + m10) / np.where(S_1 == 0, 1e-30, S_1)
    z_1 = (m12 + m21) / np.where(S_1 == 0, 1e-30, S_1)
    w_1 = (m02 - m20) / np.where(S_1 == 0, 1e-30, S_1)

    # m22 branch: S = 4z
    S_2 = np.sqrt(np.where(cond_m22, 1.0 + m22 - m00 - m11, 1.0)) * 2.0
    z_2 = 0.25 * S_2
    x_2 = (m02 + m20) / np.where(S_2 == 0, 1e-30, S_2)
    y_2 = (m12 + m21) / np.where(S_2 == 0, 1e-30, S_2)
    w_2 = (m10 - m01) / np.where(S_2 == 0, 1e-30, S_2)

    out[:, 0] = np.where(cond_trace, x_t, np.where(cond_m00, x_0, np.where(cond_m11, x_1, x_2)))
    out[:, 1] = np.where(cond_trace, y_t, np.where(cond_m00, y_0, np.where(cond_m11, y_1, y_2)))
    out[:, 2] = np.where(cond_trace, z_t, np.where(cond_m00, z_0, np.where(cond_m11, z_1, z_2)))
    out[:, 3] = np.where(cond_trace, w_t, np.where(cond_m00, w_0, np.where(cond_m11, w_1, w_2)))

    # Normalise for determinism; canonicalise sign so the scalar part is >= 0.
    out = np.array([quat_normalize(row) for row in out])
    out[out[:, 3] < 0] *= -1.0
    return out[0] if single else out


def quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product ``a * b`` for xyzw quaternions.

    Supports broadcasting over a leading batch axis (``(N, 4)``). Note: the
    rotation operator convention is owned by :func:`quat_to_matrix`; this helper
    is kept for completeness / downstream code that wants quaternion algebra
    directly.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    out = np.empty(np.broadcast(a, b).shape, dtype=np.float64)
    out[..., 0] = aw * bx + ax * bw + ay * bz - az * by
    out[..., 1] = aw * by - ax * bz + ay * bw + az * bx
    out[..., 2] = aw * bz + ax * by - ay * bx + az * bw
    out[..., 3] = aw * bw - ax * bx - ay * by - az * bz
    return out


def matrix_rotate(R: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Apply rotation matrix/matrices ``R`` to vector(s) ``v``.

    ``R`` is ``(3, 3)`` or ``(N, 3, 3)``; ``v`` is ``(3,)`` or ``(N, 3)``.
    Returns ``(3,)`` or ``(N, 3)`` -- ``R @ v`` for each row.
    """
    R = np.asarray(R, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    if R.ndim == 2 and v.ndim == 1:
        return R @ v
    if R.ndim == 3:
        if v.ndim == 1:
            return np.einsum("nij,j->ni", R, v)
        return np.einsum("nij,nj->ni", R, v)
    # R is (3,3) broadcast over batched v
    return (R @ v.T).T


# ---------------------------------------------------------------------------
# Forward kinematics.
# ---------------------------------------------------------------------------
def forward_kinematics(
    rotations: np.ndarray,
    root_positions: np.ndarray,
    *,
    parents: Tuple[int, ...] = SMPL24_PARENTS,
    rest_pose: np.ndarray = SMPL24_REST_POSE,
) -> np.ndarray:
    """Compute world-space joint positions from local rotations.

    Parameters
    ----------
    rotations : np.ndarray
        Local joint rotations, shape ``(T, 24, 4)`` or ``(24, 4)``, xyzw
        quaternions, **local relative to each joint's parent's frame**. The root
        rotation (joint 0) is the character's world rotation.
    root_positions : np.ndarray
        World-space root trajectory, shape ``(T, 3)`` or ``(3,)`` -- the world
        position of joint 0 (PELVIS).
    parents : tuple of int, optional
        Parent index per joint. Defaults to :data:`SMPL24_PARENTS`.
    rest_pose : np.ndarray, optional
        Rest joint positions, shape ``(24, 3)``. Defaults to
        :data:`SMPL24_REST_POSE`.

    Returns
    -------
    np.ndarray
        World joint positions, shape ``(T, 24, 3)`` (meters), matching the rank
        of the leading time axis of ``rotations``.
    """
    rot = np.asarray(rotations, dtype=np.float64)
    root = np.asarray(root_positions, dtype=np.float64)

    single = rot.ndim == 2
    if single:
        rot = rot[None, ...]              # (1, J, 4)
        root = root[None, ...]            # (1, 3)
    if rot.ndim != 3:
        raise ValueError(f"rotations must be (T,J,4) or (J,4); got {rot.shape}")
    T, J, C = rot.shape
    if J != NUM_JOINTS:
        raise ValueError(f"expected {NUM_JOINTS} joints, got {J}")
    if C != 4:
        raise ValueError(f"rotations last dim must be 4 (xyzw); got {C}")
    if root.shape != (T, 3):
        raise ValueError(f"root_positions must be ({T}, 3); got {root.shape}")

    rest_pose = np.asarray(rest_pose, dtype=np.float64)
    if rest_pose.shape != (NUM_JOINTS, 3):
        raise ValueError(f"rest_pose must be ({NUM_JOINTS}, 3)")

    # Rest offsets per joint (in the parent's rest frame); root offset is zero.
    rest_offsets = np.zeros((NUM_JOINTS, 3), dtype=np.float64)
    for j in range(NUM_JOINTS):
        p = parents[j]
        if p >= 0:
            rest_offsets[j] = rest_pose[j] - rest_pose[p]

    # Convert local rotations to matrices once: (T, J, 3, 3).
    local_mats = quat_to_matrix(rot.reshape(T * NUM_JOINTS, 4)).reshape(
        T, NUM_JOINTS, 3, 3
    )

    world_mats = np.empty((T, NUM_JOINTS, 3, 3), dtype=np.float64)
    world_pos = np.empty((T, NUM_JOINTS, 3), dtype=np.float64)

    # Root.
    world_mats[:, 0] = local_mats[:, 0]
    world_pos[:, 0] = root

    # Children, ascending (parents[j] < j guarantees topological order).
    for j in range(1, NUM_JOINTS):
        p = parents[j]
        world_mats[:, j] = np.einsum("tij,tjk->tik", world_mats[:, p], local_mats[:, j])
        # world_pos[j] = world_pos[p] + world_mats[j] @ rest_offset[j]
        rotated = np.einsum("tij,j->ti", world_mats[:, j], rest_offsets[j])
        world_pos[:, j] = world_pos[:, p] + rotated

    return world_pos[0] if single else world_pos


# ---------------------------------------------------------------------------
# Self-check: identity rotations reproduce the rest pose, and the
# matrix<->quaternion round trip is exact.
# ---------------------------------------------------------------------------
def _self_check() -> None:
    # 1) Identity rotations -> rest pose.
    ids = np.broadcast_to(quat_identity(), (NUM_JOINTS, 4)).copy()
    out = forward_kinematics(ids[None], SMPL24_REST_POSE[0:1].copy())
    err = float(np.max(np.abs(out[0] - SMPL24_REST_POSE)))
    assert err < 1e-9, f"identity FK diverged from rest pose by {err}"

    # 2) quat_to_matrix / quat_from_matrix round trip over many random rotations.
    rng = np.random.default_rng(0)
    for _ in range(200):
        axis = rng.normal(size=3)
        axis = axis / (np.linalg.norm(axis) + 1e-12)
        ang = rng.uniform(-np.pi, np.pi)
        q = np.concatenate([axis * np.sin(ang / 2), [np.cos(ang / 2)]])
        R = quat_to_matrix(q)
        # R must be orthonormal with det +1
        assert abs(np.linalg.det(R) - 1.0) < 1e-9
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
        q2 = quat_from_matrix(R)
        R2 = quat_to_matrix(q2)
        assert np.allclose(R, R2, atol=1e-9), "quat<->matrix round trip failed"

    # 3) quat_to_matrix is an active rotation: R @ v rotates v by q.
    #    A +90 deg rotation about +Z must send +X to +Y.
    import math
    qz = np.array([0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)])
    Rz = quat_to_matrix(qz)
    assert np.allclose(Rz @ np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), atol=1e-9)


if __name__ == "__main__":
    _self_check()
    print("forward_kinematics self-check: PASS")
