"""Format exporter: 3D positions -> Torch Monkey ``MotionData`` JSON + glTF/BVH.

This module is the bridge between the Python AI pipeline and the TypeScript
renderer. Its primary job is :meth:`FormatExporter.to_motion_data`, which:

* runs :func:`pipeline.ik_solver.positions_to_rotations` to turn the per-frame
  24-joint positions into per-joint **local** quaternions + a root trajectory,
* emits a JSON object that **exactly** matches the ``MotionData`` schema consumed
  by the renderer (see the project brief): camelCase keys, ``position`` only on
  joint 0 (PELVIS), ``beatMarkers`` from kime frames, etc.

It also offers :meth:`FormatExporter.export_to_gltf` (via ``pygltflib``, guarded
import) and :meth:`FormatExporter.export_to_bvh` (pure plain-text BVH) for
interop with external tools.

All numeric output is plain Python floats/lists so the result is JSON-serialisable
and deterministic.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from lib.skeleton_def import (
    NUM_JOINTS,
    SMPL24_NAMES,
    SMPL24_PARENTS,
    SMPL24_REST_POSE,
    UPPER_BODY_JOINTS,
)
from pipeline.ik_solver import positions_to_rotations

__all__ = ["FormatExporter", "MOTION_SCHEMA"]

_EPS = 1e-9

#: The skeleton type string used in every exported motion.
MOTION_SCHEMA = "smpl_24"


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string with timezone."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_quat(q: np.ndarray) -> List[float]:
    """Normalise a quaternion to unit length and return as a plain ``[x,y,z,w]`` list."""
    q = np.asarray(q, dtype=np.float64)
    n = float(np.linalg.norm(q))
    if n < _EPS:
        return [0.0, 0.0, 0.0, 1.0]
    q = q / n
    # Canonicalise sign (positive real part) for stable, comparable output.
    if q[3] < 0:
        q = -q
    return [float(q[0]), float(q[1]), float(q[2]), float(q[3])]


def _motion_intensity(poses_3d: np.ndarray, fps: float) -> float:
    """Mean per-joint speed (m/s) normalised to ``[0, 1]``.

    Uses a soft saturation (``tanh``) so even fast wotagei arm motion lands in a
    readable range rather than saturating hard at 1.
    """
    pos = np.asarray(poses_3d, dtype=np.float64)
    if pos.shape[0] < 2 or fps <= 0:
        return 0.0
    dt = 1.0 / fps
    velocity = np.diff(pos, axis=0) / dt            # (T-1, J, 3)
    speed = np.linalg.norm(velocity, axis=-1)       # (T-1, J)
    mean_speed = float(np.mean(speed))              # m/s
    # A very vigorous wotagei motion has wrists moving ~3-5 m/s; saturate around 4.
    return float(max(0.0, min(1.0, math.tanh(mean_speed / 4.0))))


def _primary_joints(poses_3d: np.ndarray, fps: float, top_k: int = 6) -> List[int]:
    """Return the indices of the joints that move the most (by total path length)."""
    pos = np.asarray(poses_3d, dtype=np.float64)
    if pos.shape[0] < 2:
        return list(UPPER_BODY_JOINTS[:top_k])
    velocity = np.diff(pos, axis=0)
    path = np.linalg.norm(velocity, axis=-1).sum(axis=0)   # (J,)
    order = np.argsort(path)[::-1]
    # Keep order stable: prefer upper-body joints on ties.
    out: List[int] = []
    for j in order:
        out.append(int(j))
        if len(out) >= top_k:
            break
    return out


def _is_loopable(poses_3d: np.ndarray, fps: float) -> bool:
    """True if the first and last frames are positionally similar.

    A motion is "loopable" if returning from the last frame to the first would
    not cause a visible pop. We compare the root and the extremities (hands,
    feet) within a small tolerance.
    """
    pos = np.asarray(poses_3d, dtype=np.float64)
    if pos.shape[0] < 2:
        return True
    check = [0, 10, 11, 22, 23]  # pelvis, feet, hands
    diff = np.linalg.norm(pos[-1, check] - pos[0, check], axis=-1)
    # Tolerance ~8 cm root/hand drift and ~6 cm feet; generous because mocap is
    # noisy and a small pop is acceptable for a loop preview.
    return bool(np.all(diff < 0.10))


def _beat_markers_from_kime(kime_frames: Sequence[int]) -> List[Dict[str, Any]]:
    """Build ``beatMarkers`` entries (type ``kime``) from kime frame indices."""
    markers: List[Dict[str, Any]] = []
    for i, kf in enumerate(kime_frames):
        markers.append(
            {
                "frame": int(kf),
                "beat": "",
                "type": "kime",
                "label": f"Kime {i + 1}",
            }
        )
    return markers


class FormatExporter:
    """Convert 24-joint 3D positions into Torch Monkey ``MotionData`` and files."""

    # ------------------------------------------------------------------
    # MotionData JSON.
    # ------------------------------------------------------------------
    @staticmethod
    def to_motion_data(
        poses_3d: np.ndarray,
        fps: float,
        source_video: str = "",
        kime_frames: Optional[Sequence[int]] = None,
        *,
        name: str = "",
        description: str = "",
        tags: Optional[Sequence[str]] = None,
        skeleton_type: str = MOTION_SCHEMA,
        use_real_root_height: bool = False,
        motion_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a complete ``MotionData`` dict matching the renderer schema.

        Parameters
        ----------
        poses_3d : np.ndarray
            World positions ``(T, 24, 3)`` meters.
        fps : float
            Frame rate of the capture.
        source_video : str
            Optional source video path (stored as ``sourceVideoPath``).
        kime_frames : sequence of int, optional
            Kime frame indices -> ``beatMarkers`` of type ``kime`` and
            ``keyframeFlags``.
        name, description, tags : optional
            Motion metadata.
        skeleton_type : str
            Always ``"smpl_24"`` for this pipeline.
        use_real_root_height : bool
            Forwarded to :func:`positions_to_rotations`. Default False pins root
            Y to the rest pelvis height (horizontal motion only).
        motion_id : str, optional
            Pre-assigned UUID. A fresh one is generated if omitted.

        Returns
        -------
        dict
            JSON-serialisable ``MotionData`` object (all numpy values converted
            to plain Python types).
        """
        poses_3d = np.asarray(poses_3d, dtype=np.float64)
        if poses_3d.ndim != 3 or poses_3d.shape[1] != NUM_JOINTS or poses_3d.shape[2] != 3:
            raise ValueError(f"poses_3d must be (T,24,3); got {poses_3d.shape}")
        T = int(poses_3d.shape[0])
        fps = float(fps)
        duration = float(T / fps) if fps > 0 else 0.0
        kime_frames = list(kime_frames) if kime_frames else []

        # IK: positions -> local quaternions + root trajectory.
        ik = positions_to_rotations(poses_3d, use_real_root_height=use_real_root_height)
        rotations = ik["rotations"]          # (T, 24, 4)
        root_positions = ik["root_positions"]  # (T, 3)

        # Build per-frame poses. position appears ONLY on joint 0.
        poses: List[Dict[str, Any]] = []
        for t in range(T):
            transforms: Dict[str, Dict[str, Any]] = {}
            for j in range(NUM_JOINTS):
                entry: Dict[str, Any] = {
                    "rotation": _normalize_quat(rotations[t, j]),
                }
                if j == 0:
                    entry["position"] = [
                        float(root_positions[t, 0]),
                        float(root_positions[t, 1]),
                        float(root_positions[t, 2]),
                    ]
                transforms[str(j)] = entry
            poses.append({"frame": t, "transforms": transforms})

        intensity = _motion_intensity(poses_3d, fps)
        primary = _primary_joints(poses_3d, fps)
        loopable = _is_loopable(poses_3d, fps)
        beat_markers = _beat_markers_from_kime(kime_frames)

        now = _now_iso()
        return {
            "id": motion_id or str(uuid.uuid4()),
            "name": name or (f"Captured from {source_video}" if source_video else "Untitled Motion"),
            "description": description or f"AI captured at {fps:g} fps, {T} frames",
            "tags": list(tags) if tags else ["ai-capture"],
            "fps": fps,
            "duration": duration,
            "frameCount": T,
            "skeletonType": skeleton_type,
            "poses": poses,
            "beatMarkers": beat_markers,
            "keyframeFlags": [int(k) for k in kime_frames],
            "motionIntensity": intensity,
            "primaryJoints": primary,
            "isLoopable": loopable,
            "source": "ai-capture",
            "sourceVideoPath": source_video or "",
            "createdAt": now,
            "updatedAt": now,
        }

    # ------------------------------------------------------------------
    # BVH (plain text).
    # ------------------------------------------------------------------
    @staticmethod
    def export_to_bvh(
        motion_data: Dict[str, Any],
        output_path: str,
        *,
        parents: Tuple[int, ...] = SMPL24_PARENTS,
        rest_pose: np.ndarray = SMPL24_REST_POSE,
    ) -> str:
        """Write a plain-text BVH file from a ``MotionData`` dict.

        The hierarchy uses the SMPL-24 names with rest offsets; each joint has
        three ``ZXY`` Euler rotation channels (in degrees), and the root also has
        three translation channels. Rotations are converted from the motion's
        local quaternions (xyzw) to Euler angles in the BVH channel order.

        Returns the path written.
        """
        rest_pose = np.asarray(rest_pose, dtype=np.float64)
        children = [[] for _ in range(NUM_JOINTS)]
        for j, p in enumerate(parents):
            if p >= 0:
                children[p].append(j)

        # Channel order: root = [Xpos,Ypos,Zpos, Zrot,Xrot,Yrot], joints = [Zrot,Xrot,Yrot].
        root_offset = rest_pose[0]

        def _bvh_block(j: int, indent: str, lines: List[str]) -> None:
            is_root = j == 0
            name = SMPL24_NAMES[j]
            parent = parents[j]
            offset = rest_pose[j] - rest_pose[parent] if parent >= 0 else rest_pose[j]
            if is_root:
                lines.append(f"{indent}ROOT {name}")
            else:
                lines.append(f"{indent}JOINT {name}")
            lines.append(f"{indent}{{")
            lines.append(
                f"{indent}\tOFFSET {offset[0]:.6f} {offset[1]:.6f} {offset[2]:.6f}"
            )
            if is_root:
                chans = "Xposition Yposition Zposition Zrotation Xrotation Yrotation"
            else:
                chans = "Zrotation Xrotation Yrotation"
            lines.append(f"{indent}\tCHANNELS {6 if is_root else 3} {chans}")
            kids = children[j]
            if kids:
                for c in kids:
                    if len(children[c]) > 0:
                        _bvh_block(c, indent + "\t", lines)
                    else:
                        # leaf -> End Site with a small offset along the bone.
                        leaf_off = rest_pose[c] - rest_pose[j]
                        lines.append(f"{indent}\tJOINT {SMPL24_NAMES[c]}")
                        lines.append(f"{indent}\t{{")
                        lines.append(
                            f"{indent}\t\tOFFSET {leaf_off[0]:.6f} {leaf_off[1]:.6f} {leaf_off[2]:.6f}"
                        )
                        lines.append(f"{indent}\t\tEnd Site")
                        lines.append(f"{indent}\t\t{{")
                        lines.append(f"{indent}\t\t\tOFFSET 0.0 0.0 0.0")
                        lines.append(f"{indent}\t\t}}")
                        lines.append(f"{indent}\t}}")
            else:
                lines.append(f"{indent}\tEnd Site")
                lines.append(f"{indent}\t{{")
                lines.append(f"{indent}\t\tOFFSET 0.0 0.0 0.0")
                lines.append(f"{indent}\t}}")
            lines.append(f"{indent}}}")

        header: List[str] = ["HIERARCHY"]
        _bvh_block(0, "", header)

        # Motion data.
        fps = float(motion_data.get("fps", 30.0))
        frame_time = 1.0 / fps if fps > 0 else 1.0 / 30.0
        poses = motion_data.get("poses", [])
        frames = len(poses)

        motion_lines: List[str] = [
            "MOTION",
            f"Frames: {frames}",
            f"Frame Time: {frame_time:.8f}",
        ]
        for pose in poses:
            transforms = pose["transforms"]
            row: List[float] = []
            for j in range(NUM_JOINTS):
                t = transforms[str(j)]
                if j == 0:
                    pos = t.get("position", [0.0, 0.0, 0.0])
                    row.extend([float(pos[0]), float(pos[1]), float(pos[2])])
                q = np.asarray(t["rotation"], dtype=np.float64)  # xyzw
                z, x, y = _quat_to_bvh_euler_zxy(q)
                row.extend([math.degrees(z), math.degrees(x), math.degrees(y)])
            motion_lines.append(" ".join(f"{v:.6f}" for v in row))

        text = "\n".join(header + motion_lines) + "\n"
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return output_path

    # ------------------------------------------------------------------
    # glTF / glB (via pygltflib).
    # ------------------------------------------------------------------
    @staticmethod
    def export_to_gltf(
        motion_data: Dict[str, Any],
        output_path: str,
        *,
        parents: Tuple[int, ...] = SMPL24_PARENTS,
        rest_pose: np.ndarray = SMPL24_REST_POSE,
    ) -> str:
        """Write a glTF/glB with 24 nodes and one animation.

        Each joint becomes a node with the rest offset as its translation; the
        animation has one rotation sampler (LINEAR) per joint and one root
        translation sampler. ``output_path`` ending in ``.glb`` writes a binary
        glb, otherwise a ``.gltf``.

        Requires ``pygltflib`` (see ``requirements.txt``). Raises a clear error
        if the package is not importable so the caller can degrade gracefully.

        Implementation note
        -------------------
        Per-bufferView data is embedded as a base64 *data URI* on a single shared
        buffer. This is robust across ``pygltflib`` versions (it does not depend
        on private ``_glb_data`` / ``set_binary_buffer`` helpers) and produces
        valid files for both ``.gltf`` (embedded JSON+data) and ``.glb`` (the
        library packs the data URIs into the binary chunk on save).
        """
        try:
            import base64
            from pygltflib import (
                GLTF2,
                Asset,
                Node,
                Scene,
                Animation,
                AnimationSampler,
                AnimationChannel,
                AnimationChannelTarget,
                Accessor,
                BufferView,
                Buffer,
            )
        except Exception as exc:  # pragma: no cover - import guard
            raise ImportError(
                "export_to_gltf requires the 'pygltflib' package. "
                "Install it with: pip install pygltflib"
            ) from exc

        # Component-type / accessor-type enums are integers in the glTF spec.
        # Resolve them defensively (pygltflib exposes short names in recent
        # versions and integer values always).
        try:
            from pygltflib import FLOAT as _COMP_FLOAT  # noqa: F401
        except Exception:
            _COMP_FLOAT = 5126
        _TYPE_SCALAR = "SCALAR"
        _TYPE_VEC3 = "VEC3"
        _TYPE_VEC4 = "VEC4"

        def _data_uri(blob: bytes) -> str:
            return "data:application/octet-stream;base64," + base64.b64encode(blob).decode("ascii")

        rest_pose = np.asarray(rest_pose, dtype=np.float64)
        fps = float(motion_data.get("fps", 30.0))
        poses = motion_data.get("poses", [])
        T = len(poses)
        frame_time = 1.0 / fps if fps > 0 else 1.0 / 30.0

        # Gather per-joint rotation (xyzw) and root translation arrays.
        rot = np.zeros((T, NUM_JOINTS, 4), dtype=np.float32)
        root_pos = np.zeros((T, 3), dtype=np.float32)
        for fi, pose in enumerate(poses):
            tr = pose["transforms"]
            for j in range(NUM_JOINTS):
                rot[fi, j] = np.asarray(tr[str(j)]["rotation"], dtype=np.float32)
                if j == 0:
                    p = tr["0"].get("position", [0.0, 0.0, 0.0])
                    root_pos[fi] = np.asarray(p, dtype=np.float32)

        accessors: List[Accessor] = []
        buffer_views: List[BufferView] = []
        total_bytes = 0

        def _add_array(arr: np.ndarray, type_str: str, count: int) -> int:
            nonlocal total_bytes
            arr = np.ascontiguousarray(arr, dtype=np.float32)
            blob = arr.tobytes()
            bv_idx = len(buffer_views)
            buffer_views.append(
                BufferView(
                    buffer=0,
                    byteOffset=total_bytes,
                    byteLength=len(blob),
                )
            )
            flat = arr.reshape(-1, arr.shape[-1]) if arr.size else arr
            max_v = flat.max(axis=0).tolist() if arr.size else [0.0] * arr.shape[-1]
            min_v = flat.min(axis=0).tolist() if arr.size else [0.0] * arr.shape[-1]
            acc_idx = len(accessors)
            accessors.append(
                Accessor(
                    bufferView=bv_idx,
                    componentType=_COMP_FLOAT,
                    count=count,
                    type=type_str,
                    max=max_v,
                    min=min_v,
                )
            )
            total_bytes += len(blob)
            return acc_idx

        # Time input accessor (shared by all channels).
        times = (np.arange(T, dtype=np.float32) * frame_time).reshape(T, 1)
        time_acc = _add_array(times, _TYPE_SCALAR, T)

        # Per-joint rotation accessors + root translation accessor.
        rot_accs = [_add_array(rot[:, j, :].reshape(T, 4), _TYPE_VEC4, T) for j in range(NUM_JOINTS)]
        root_acc = _add_array(root_pos.reshape(T, 3), _TYPE_VEC3, T)

        # Concatenate all float32 blobs in bufferView order to form the one buffer
        # (the byteOffsets assigned in _add_array must match this packing order:
        # times, then per-joint rotations, then root translation).
        packed = bytearray()
        packed += times.astype(np.float32).tobytes()
        for j in range(NUM_JOINTS):
            packed += np.ascontiguousarray(rot[:, j, :], dtype=np.float32).tobytes()
        packed += np.ascontiguousarray(root_pos, dtype=np.float32).tobytes()

        # Nodes (24), each referencing its parent.
        nodes: List[Node] = []
        for j in range(NUM_JOINTS):
            p = parents[j]
            off = rest_pose[j] - rest_pose[p] if p >= 0 else rest_pose[j]
            nodes.append(
                Node(
                    name=SMPL24_NAMES[j],
                    translation=[float(off[0]), float(off[1]), float(off[2])],
                    children=[],
                )
            )
        for j in range(NUM_JOINTS):
            p = parents[j]
            if p >= 0:
                nodes[p].children.append(j)

        # Animation channels: one rotation channel per joint + root translation.
        channels: List[AnimationChannel] = []
        samplers: List[AnimationSampler] = []
        for j in range(NUM_JOINTS):
            s_idx = len(samplers)
            samplers.append(AnimationSampler(input=time_acc, output=rot_accs[j], interpolation="LINEAR"))
            channels.append(
                AnimationChannel(
                    sampler=s_idx,
                    target=AnimationChannelTarget(node=j, path="rotation"),
                )
            )
        s_idx = len(samplers)
        samplers.append(AnimationSampler(input=time_acc, output=root_acc, interpolation="LINEAR"))
        channels.append(
            AnimationChannel(
                sampler=s_idx,
                target=AnimationChannelTarget(node=0, path="translation"),
            )
        )

        gltf = GLTF2(
            asset=Asset(version="2.0", generator="torch-monkey"),
            accessors=accessors,
            bufferViews=buffer_views,
            buffers=[Buffer(byteLength=len(packed), uri=_data_uri(bytes(packed)))],
            nodes=nodes,
            scenes=[Scene(nodes=[0])] if nodes else [],
            scene=0 if nodes else None,
            animations=[Animation(name="motion", samplers=samplers, channels=channels)],
        )

        # save() dispatches on extension: .glb -> binary, else embedded .gltf.
        gltf.save(output_path)
        return output_path


# ---------------------------------------------------------------------------
# Quaternion -> BVH Euler (ZXY).
# ---------------------------------------------------------------------------
def _quat_to_bvh_euler_zxy(q: np.ndarray) -> Tuple[float, float, float]:
    """Convert an xyzw quaternion to BVH ZXY Euler angles (radians).

    BVH's default rotation order for ``CHANNELS ... Zrotation Xrotation Yrotation``
    is intrinsic Z * X * Y. We decompose the quaternion accordingly so a viewer
    applying the listed Euler angles reconstructs the same orientation.
    """
    q = np.asarray(q, dtype=np.float64)
    n = float(np.linalg.norm(q))
    if n < _EPS:
        return (0.0, 0.0, 0.0)
    q = q / n
    x, y, z, w = q  # xyzw

    # Rotation matrix from quaternion.
    R = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    # Decompose R = Rz(z) * Rx(x) * Ry(y) (intrinsic ZXY).
    # R[0][2] = sin(x)*cos(y); R[1][2] = -cos(x)*sin(y); R[2][2] = cos(x)*cos(y)
    # R[2][0] = -sin(z)*cos(x); R[2][1] = cos(z)*cos(x)
    # Standard ZXY extraction:
    sy = math.sqrt(R[0, 0] * R[0, 0] + R[1, 0] * R[1, 0])
    if sy > 1e-6:  # not gimbal-locked
        z_ang = math.atan2(-R[2, 0], R[2, 1])
        x_ang = math.asin(max(-1.0, min(1.0, R[2, 2])))
        y_ang = math.atan2(-R[1, 2], R[0, 2])
    else:
        z_ang = math.atan2(R[1, 0], R[0, 0])
        x_ang = math.asin(max(-1.0, min(1.0, R[2, 2])))
        y_ang = 0.0
    return (z_ang, x_ang, y_ang)


# ---------------------------------------------------------------------------
# Self-check.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Tiny synthetic clip: arm raise, rest skeleton.
    rng = np.random.default_rng(1)
    rest = SMPL24_REST_POSE
    T = 20
    poses = np.tile(rest, (T, 1, 1)).astype(np.float64)
    for t in range(T):
        poses[t, 22] = rest[22] + np.array([0.0, 0.01 * t, 0.0])

    md = FormatExporter.to_motion_data(poses, fps=30.0, source_video="test.mp4", kime_frames=[5])
    assert md["skeletonType"] == "smpl_24"
    assert md["frameCount"] == T
    assert len(md["poses"]) == T
    # joint 0 must carry position; others must not.
    p0 = md["poses"][0]["transforms"]
    assert "position" in p0["0"]
    for j in range(1, NUM_JOINTS):
        assert "position" not in p0[str(j)], f"joint {j} should not have position"
    # kime -> beatMarkers + keyframeFlags
    assert len(md["beatMarkers"]) == 1 and md["beatMarkers"][0]["type"] == "kime"
    assert md["keyframeFlags"] == [5]
    # rotations are unit quaternions.
    for t in range(T):
        for j in range(NUM_JOINTS):
            qq = md["poses"][t]["transforms"][str(j)]["rotation"]
            assert abs(np.linalg.norm(qq) - 1.0) < 1e-6
    # JSON-serialisable.
    json.dumps(md)
    print(f"format_exporter self-check: PASS (intensity={md['motionIntensity']:.3f}, loopable={md['isLoopable']})")

    # BVH round-trip (pure text).
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".bvh"); os.close(fd)
    FormatExporter.export_to_bvh(md, path)
    with open(path) as fh:
        head = fh.read(200)
    assert "HIERARCHY" in head and "MOTION" in open(path).read()
    print("format_exporter BVH export: PASS")
