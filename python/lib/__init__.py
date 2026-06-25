"""Torch Monkey Python pipeline library package.

Shared, low-dependency helpers for the AI mocap pipeline:

* :mod:`lib.blazepose_to_h36m` -- canonical BlazePose(33) -> Human3.6M(17) joint mapping.
* :mod:`lib.expand_joints`     -- Human3.6M(17) -> SMPL_24 (Torch Monkey internal) positions.
* :mod:`lib.motionbert_model`  -- vendored, faithful MotionBERT 'lite' 3D-lifting Transformer.

All modules import cleanly on a CPU-only machine without optional heavy
dependencies (``torch`` / ``mediapipe`` are imported lazily / guarded).
"""

__all__ = [
    "blazepose_to_h36m",
    "expand_joints",
    "motionbert_model",
]
