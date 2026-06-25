"""Reference forward kinematics for the offline self-test.

This is a thin, stable re-export of :mod:`lib.forward_kinematics`, placed here
so the self-test (``tools/selftest_pipeline.py``) can import it by the path the
project brief specifies (``tools/forward_kinematics.py``) without coupling the
test layout to the internal ``lib`` package. The two names are guaranteed to be
the same implementation, so anything that round-trips through one round-trips
through the other.
"""

from __future__ import annotations

from lib.forward_kinematics import (  # noqa: F401  (re-export)
    forward_kinematics,
    quat_from_matrix,
    quat_to_matrix,
    quat_identity,
    quat_multiply,
    quat_normalize,
    matrix_rotate,
)

__all__ = [
    "forward_kinematics",
    "quat_from_matrix",
    "quat_to_matrix",
    "quat_identity",
    "quat_multiply",
    "quat_normalize",
    "matrix_rotate",
]
