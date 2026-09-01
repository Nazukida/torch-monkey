"""MotionBERT-based 3D pose estimator -> SMPL_24 meters.

Pipeline
--------
::

    keypoints_2d (T, 33, 4)  [BlazePose, normalized]
        |
        |  lib.blazepose_to_h36m.map_blazepose33_to_h36m17
        v
    h36m_2d (T, 17, 2)
        |
        |  normalize: subtract root(0), scale by mean bone-length (unit skeleton)
        v
    h36m_2d_norm (T, 17, 2)
        |
        |  sliding 243-frame windows, 50% overlap -> MotionBERT (torch)
        |  (or geometric anthropometric lifter if weights/torch are absent)
        v
    h36m_3d_norm (T, 17, 3)   [unit-skeleton, root-relative]
        |
        |  merge overlaps (average), denormalize to meters via skeleton scale
        v
    h36m_3d_m (T, 17, 3)
        |
        |  lib.expand_joints.expand_h36m17_to_smpl24_mm
        v
    smpl24_3d (T, 24, 3)      [meters, root-relative, Y-up, faces +Z]

GPU / robustness
----------------
* ``device = "cuda" if torch.cuda.is_available() else "cpu"``.
* Optional **half precision** on CUDA for speed (configurable).
* Weights are loaded defensively: if the checkpoint is missing *or* torch is
  absent, the estimator transparently falls back to the
  :class:`GeometricLifter` (an anthropometric 2D->3D lifter) so the server
  boots and the self-test passes on a CPU box with no weights.

Coordinate convention
---------------------
Output is **root-relative** (joint 0 PELVIS at origin), meters, Y-up, character
faces +Z. The horizontal (X, Z) motion follows the projected 2D displacement;
vertical (Y) comes from the lifter's depth/height estimate. The
``format_exporter``/``ik_solver`` layers downstream decide how much of the root
translation to keep.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

import numpy as np

from lib.blazepose_to_h36m import (
    map_blazepose33_to_h36m17,
    compute_visibility,
)
from lib.expand_joints import expand_h36m17_to_smpl24_mm

log = logging.getLogger(__name__)

__all__ = ["MotionBERTEstimator", "GeometricLifter"]

# MotionBERT uses 243-frame temporal windows with 50% overlap.
WINDOW = 243
STRIDE = WINDOW // 2  # 121


# ---------------------------------------------------------------------------
# Official MotionBERT input normalization (crop_scale) + output rescale.
# ---------------------------------------------------------------------------
def _crop_scale(motion: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Faithful port of MotionBERT's ``crop_scale`` (utils_data.py).

    Maps the pose bounding box (over all frames/joints with non-zero
    confidence) into ``[-1, 1]`` preserving aspect ratio, and keeps the
    confidence channel untouched. This is the exact input distribution the
    released DSTformer was trained on, so feeding it is essential for the
    learned weights to produce sane 3D.

    Parameters
    ----------
    motion : np.ndarray
        ``(T, 17, 3)`` — ``(x, y, confidence)``. x, y in image-normalized
        ``[0, 1]`` (BlazePose space) or pixels; scale-invariant either way.

    Returns
    -------
    np.ndarray
        ``(T, 17, 3)`` normalized to ``[-1, 1]`` (x, y), confidence preserved.
    """
    result = motion.copy()
    valid = motion[motion[..., 2] > 0][:, :2]
    if valid.shape[0] < 4:
        return np.zeros_like(motion)
    xmin, xmax = float(valid[:, 0].min()), float(valid[:, 0].max())
    ymin, ymax = float(valid[:, 1].min()), float(valid[:, 1].max())
    scale = max(xmax - xmin, ymax - ymin)
    if scale < eps:
        return np.zeros_like(motion)
    xs = (xmin + xmax - scale) / 2.0
    ys = (ymin + ymax - scale) / 2.0
    result[..., :2] = (motion[..., :2] - np.array([xs, ys], dtype=motion.dtype)) / scale
    result[..., :2] = (result[..., :2] - 0.5) * 2.0
    result[..., :2] = np.clip(result[..., :2], -1.0, 1.0)
    result[..., 2] = motion[..., 2]
    return result.astype(np.float32)


# ---------------------------------------------------------------------------
# H36M-17 joint-order bridge.
#
# lib/blazepose_to_h36m.py emits its own 17-joint layout (…7 spine, 8 neck,
# 9 head, 10-12 L-arm, 13-15 R-arm, 16 thorax). The released DSTformer was
# trained on the Human3.6M/VideoPose3D layout (…7 Spine, 8 Thorax, 9 Neck,
# 10 Head, 11-13 L-arm, 14-16 R-arm), so from index 8 up the two disagree and
# every upper-body joint lands in the wrong input slot.
#
# Measured on a 481-frame clip, 2D reprojection error (% of torso):
#   project layout  mean 17.08  median 13.15  p90 33.33
#   training layout mean 15.92  median 12.26  p90 30.21
#
# PROJ_FOR_STD[i] = project index whose joint belongs in training slot i.
PROJ_FOR_STD = (0, 1, 2, 3, 4, 5, 6, 7, 16, 8, 9, 10, 11, 12, 13, 14, 15)
# inverse: STD_FOR_PROJ[p] = training slot holding project joint p.
STD_FOR_PROJ = (0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 8)


# MotionBERT H36M output is root-relative in a normalized space where the full
# body spans ~2 units (roughly [-1, 1]). Scale so an adult is ~1.7 m tall.
MOTIONBERT_OUTPUT_SCALE_M = 0.85

# Approximate adult skeleton scale. MotionBERT was trained on Human3.6M where
# the root->thorax distance is ~0.5m for an average subject. We use a fixed
# *mean bone length* normalization so the unit skeleton maps back to a real
# human scale. This constant is the scale (meters per unit-skeleton-unit).
DEFAULT_SKELETON_SCALE_M = 0.95  # height-ish of unit-normalized skeleton, meters

# Mean bone length used for normalization (in normalized-image units). We use
# the average of the four proximal limbs + torso; computed per-frame and
# averaged over the clip for stability.
_TORSO_LIMB_PAIRS = [
    (0, 1), (1, 2), (2, 3),   # root->R-hip->R-knee->R-ankle
    (0, 4), (4, 5), (5, 6),   # root->L-hip->L-knee->L-ankle
    (0, 7), (7, 8),           # root->spine->neck
    (8, 10), (8, 13),         # neck->L/R-shoulder
]


# ---------------------------------------------------------------------------
# Normalization helpers (numpy)
# ---------------------------------------------------------------------------
def _bone_length_scale(kp2d: np.ndarray) -> np.ndarray:
    """Per-frame mean bone length (in normalized-image units), shape (T,).

    Used as the normalization denominator so the unit-skeleton has ~unit bones.
    """
    T = kp2d.shape[0]
    lengths = []
    for a, b in _TORSO_LIMB_PAIRS:
        d = np.linalg.norm(kp2d[:, a, :] - kp2d[:, b, :], axis=-1)  # (T,)
        lengths.append(d)
    mean_len = np.mean(np.stack(lengths, axis=0), axis=0)  # (T,)
    mean_len = np.maximum(mean_len, 1e-6)
    return mean_len


def _normalize_2d(kp2d: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Root-center + unit-bone-scale normalize 2D keypoints.

    Returns ``(normalized, root_xy, scale)`` so output can be denormalized.
    """
    root = kp2d[:, 0:1, :].copy()                       # (T,1,2)
    centered = kp2d - root                              # root at origin
    scale = _bone_length_scale(kp2d)                    # (T,)
    centered = centered / scale[:, None, None]
    return centered.astype(np.float32), root.squeeze(1).astype(np.float32), scale.astype(np.float32)


def _denormalize_3d(kp3d_norm: np.ndarray, scale: np.ndarray,
                    skeleton_scale_m: float = DEFAULT_SKELETON_SCALE_M) -> np.ndarray:
    """Scale a unit-skeleton 3D output back to meters (root-relative).

    MotionBERT outputs root-relative 3D in roughly the same units as the input
    2D normalization (i.e. "unit bones"). We multiply by the per-frame scale
    (image-units -> unit-skeleton) then by ``skeleton_scale_m``
    (unit-skeleton -> meters).
    """
    return (kp3d_norm * scale[:, None, None]) * skeleton_scale_m


# ---------------------------------------------------------------------------
# Geometric (no-torch) anthropometric 3D lifter -- always-available fallback.
# ---------------------------------------------------------------------------
class GeometricLifter:
    """Anthropometric 2D->3D lifter with no learned weights.

    Strategy
    --------
    For each frame we know the projected (x, y) of 17 H36M joints and the unit
    bone scale. We reconstruct 3D by:

    1. Setting ``Y`` (height) from the 2D *vertical* extent: the more a limb
       is foreshortened in 2D relative to its known rest length, the more it
       points along the camera axis -> we assign that "missing" length to the
       depth (Z) axis. This is the classic "2D length -> 3D via known rest
       length" geometric lift.
    2. Preserving the normalized 2D (x, y) as the (x, y) image-plane
       components of the 3D pose.
    3. Deriving per-joint depth by distributing the foreshortening residual
       along bones, accumulated root-down (so children inherit the parent's
       depth drift). The sign is resolved by the limb's vertical gradient: a
       limb pointing up in the image is assumed to recede into +Z if it is
       shorter than rest.

    This is deliberately simple and *plausible* (never NaN, always a valid
    human-shaped skeleton). It exists so the pipeline produces real output
    when MotionBERT weights / torch are unavailable.
    """

    # H36M-17 rest bone lengths on a unit skeleton (parent->child), used to
    # detect foreshortening. Parent indices (-1 = root).
    H36M_PARENTS = (-1, 0, 1, 2, 0, 4, 5, 0, 7, 8, 8, 10, 11, 8, 13, 14, 0)
    # approximate rest lengths (unit skeleton), parent->child:
    H36M_REST_LEN = np.array([
        0.0,    # 0 root
        0.50,   # 1 R-hip   (root->R-hip)
        0.45,   # 2 R-knee
        0.45,   # 3 R-ankle
        0.50,   # 4 L-hip
        0.45,   # 5 L-knee
        0.45,   # 6 L-ankle
        0.35,   # 7 spine  (root->spine)
        0.25,   # 8 neck   (spine->neck)
        0.30,   # 9 head   (neck->head)
        0.20,   # 10 L-shoulder (neck->L-sho)
        0.28,   # 11 L-elbow
        0.26,   # 12 L-wrist
        0.20,   # 13 R-shoulder
        0.28,   # 14 R-elbow
        0.26,   # 15 R-wrist
        0.20,   # 16 thorax (root->thorax)
    ], dtype=np.float64)

    def __init__(self):
        pass

    def lift(self, kp2d_norm: np.ndarray) -> np.ndarray:
        """Lift normalized 2D (T,17,2) -> unit-skeleton 3D (T,17,3).

        Output is root-relative (joint 0 at origin), with ``x, y`` equal to the
        normalized 2D coords and ``z`` a depth estimate from foreshortening.
        """
        T, J, _ = kp2d_norm.shape
        out = np.zeros((T, J, 3), dtype=np.float32)
        # x, y straight from 2D
        out[..., 0:2] = kp2d_norm
        # z from per-bone foreshortening, accumulated root-down.
        z = np.zeros((T, J), dtype=np.float32)
        for j in range(1, J):
            p = self.H36M_PARENTS[j]
            rest = self.H36M_REST_LEN[j]
            if rest <= 0:
                continue
            # projected length in 2D
            proj = np.linalg.norm(kp2d_norm[:, j, :] - kp2d_norm[:, p, :], axis=-1)
            proj = np.maximum(proj, 1e-6)
            # foreshortening ratio in [0,1]; <1 means limb points along Z
            ratio = np.clip(proj / rest, 0.0, 1.0)
            # depth magnitude = sqrt(rest^2 - proj^2)
            depth_mag = np.sqrt(np.maximum(rest ** 2 - proj ** 2, 0.0))
            # sign: limbs whose child is *above* parent in image (smaller y)
            # and foreshortened are treated as receding (+Z, toward camera-back);
            # otherwise -Z. This is a weak but stable prior.
            dy = kp2d_norm[:, p, 1] - kp2d_norm[:, j, 1]  # >0 if child above parent
            sign = np.where(dy >= 0, 1.0, -1.0)
            # only apply depth when meaningfully foreshortened
            active = ratio < 0.95
            dz = np.where(active, sign * depth_mag, 0.0)
            z[:, j] = z[:, p] + dz
        out[..., 2] = z
        return out


# ---------------------------------------------------------------------------
# Main estimator
# ---------------------------------------------------------------------------
class MotionBERTEstimator:
    """3D pose estimator: MotionBERT (weights optional) -> SMPL_24 meters.

    Parameters
    ----------
    model_path : str, optional
        Path to a MotionBERT MB_lite checkpoint. If absent, the geometric
        lifter is used.
    model_dir : str, optional
        Directory to search for the checkpoint if ``model_path`` is not given.
    use_half_precision_on_cuda : bool
        If True and on CUDA, run the model in float16 for speed.
    skeleton_scale_m : float
        Unit-skeleton -> meters scale used in denormalization.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        model_dir: Optional[str] = None,
        use_half_precision_on_cuda: bool = True,
        skeleton_scale_m: float = DEFAULT_SKELETON_SCALE_M,
    ):
        self.skeleton_scale_m = float(skeleton_scale_m)
        self.use_half = bool(use_half_precision_on_cuda)
        self.window = WINDOW
        self.stride = STRIDE

        self._torch = None
        self._device = "cpu"
        self._model = None
        self._weights_loaded = False
        self._lifter = GeometricLifter()

        resolved = self._resolve_model_path(model_path, model_dir)
        self._init_model(resolved)

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_model_path(model_path: Optional[str],
                            model_dir: Optional[str]) -> Optional[str]:
        candidates: List[str] = []
        if model_path:
            candidates.append(model_path)
        if model_dir:
            candidates.append(os.path.join(model_dir, "mb3d.pth"))
            candidates.append(os.path.join(model_dir, "motionbert_lite.pth"))
            candidates.append(os.path.join(model_dir, "motionbert_lite.ckpt"))
        candidates += [
            "models/mb3d.pth",
            "python/models/mb3d.pth",
            "models/motionbert_lite.pth",
            "pretrained/mb3d.pth",
            "python/pretrained/mb3d.pth",
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return None

    def _init_model(self, resolved_path: Optional[str]):
        """Try to build + load the MotionBERT model; fall back gracefully."""
        # 1) torch available?
        try:
            import torch
            self._torch = torch
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception as exc:
            log.warning("torch unavailable (%s); using geometric 3D lifter only.", exc)
            self._torch = None
            self._model = None
            return

        # 2) build + load weights?
        if resolved_path is None:
            log.info("No MotionBERT checkpoint found; using geometric 3D lifter "
                     "(plausible 3D, no learned weights).")
            return

        try:
            from lib.dstformer_model import load_dstformer
            self._model = load_dstformer(resolved_path, device=self._device)
            report = getattr(self._model, "_load_report", {})
            # Only trust the learned lifter when the weights actually mapped in
            # bulk — a near-empty match means the checkpoint didn't fit and we
            # are better off with the geometric fallback than a random net.
            matched = report.get("matched", 0)
            total = report.get("total_ckpt_keys", 1) or 1
            self._weights_loaded = matched > 0 and (matched / total) >= 0.9
            if self.use_half and self._device.startswith("cuda") and self._torch:
                try:
                    self._model = self._model.half()
                except Exception:
                    pass
            log.info("MotionBERT DSTformer ready on %s (weights_loaded=%s, "
                     "matched=%d/%d).", self._device, self._weights_loaded,
                     matched, total)
            if not self._weights_loaded:
                log.warning("DSTformer weights matched only %d/%d keys; using "
                            "geometric lifter instead.", matched, total)
                self._model = None
        except Exception as exc:
            log.warning("Failed to load MotionBERT weights from %s (%s); "
                        "falling back to geometric lifter.", resolved_path, exc)
            self._model = None
            self._weights_loaded = False

    # ------------------------------------------------------------------
    # public properties
    # ------------------------------------------------------------------
    @property
    def device(self) -> str:
        return self._device

    @property
    def has_motionbert(self) -> bool:
        """True iff the learned MotionBERT model is loaded and ready."""
        return self._model is not None and self._weights_loaded

    @property
    def is_available(self) -> bool:
        """Always True -- the estimator always produces output (lifter fallback)."""
        return True

    # ------------------------------------------------------------------
    # inference
    # ------------------------------------------------------------------
    def infer(self, keypoints_2d: np.ndarray) -> np.ndarray:
        """Estimate SMPL_24 3D positions (meters) from BlazePose 2D keypoints.

        Parameters
        ----------
        keypoints_2d : np.ndarray
            ``(T, 33, 4)`` BlazePose detections (normalized ``[x,y,z,vis]``).

        Returns
        -------
        np.ndarray
            ``(T, 24, 3)`` SMPL_24 positions, meters, root-relative, Y-up,
            faces +Z.
        """
        kp = np.asarray(keypoints_2d, dtype=np.float32)
        if kp.ndim != 3 or kp.shape[1] != NUM_BLAZEPOSE_JOINTS or kp.shape[2] < 2:
            raise ValueError(
                f"keypoints_2d must be (T, {NUM_BLAZEPOSE_JOINTS}, >=2); got {kp.shape}"
            )
        T = kp.shape[0]
        if T == 0:
            return np.zeros((0, 24, 3), dtype=np.float32)

        # 1) BlazePose 33 -> H36M 17 (2D)
        h36m_2d = map_blazepose33_to_h36m17(kp)  # (T, 17, 2)

        if self.has_motionbert and self._torch is not None:
            # --- Learned DSTformer path (official normalization) ------------
            # Build the 3-channel (x, y, confidence) input the release expects.
            vis = compute_visibility(kp)                      # (T, 17)
            motion = np.concatenate(
                [h36m_2d, vis[..., None]], axis=-1
            ).astype(np.float32)                              # (T, 17, 3)
            # Re-index into the layout the released weights were trained on,
            # run the lifter, then map the prediction back so everything
            # downstream keeps using the project's own joint order.
            motion_std = motion[:, list(PROJ_FOR_STD), :]     # (T,17,3)
            motion_norm = _crop_scale(motion_std)             # (T,17,3) in [-1,1]
            h36m_3d_std = self._infer_motionbert(motion_norm)  # (T,17,3) root-rel
            h36m_3d = h36m_3d_std[:, list(STD_FOR_PROJ), :]   # -> project layout
            # DSTformer output is a normalized, root-relative 3D pose; scale to
            # meters. expand_joints wants millimetres.
            h36m_3d_m = h36m_3d * MOTIONBERT_OUTPUT_SCALE_M
        else:
            # --- Geometric fallback (bone-length normalization) -------------
            h36m_2d_norm, root_xy, scale = _normalize_2d(h36m_2d)
            h36m_3d_norm = self._lifter.lift(h36m_2d_norm)    # (T,17,3)
            h36m_3d_m = _denormalize_3d(
                h36m_3d_norm, scale, self.skeleton_scale_m
            )

        # --- image frame (Y down) -> skeleton frame (Y up) ------------------
        # Both lifting paths inherit the 2D image convention, where +Y points
        # DOWN: MotionBERT is trained on image-space H36M, and the geometric
        # fallback builds depth on top of the same 2D coordinates. Measured on
        # the DSTformer release, relative to the pelvis: head dy = -0.64,
        # ankle dy = +0.95.
        #
        # `expand_joints` / `skeleton_def` are Y-UP (rest pose has HEAD at
        # y=1.55 and L_FOOT at y=0.02), so handing the lifter's output over
        # unconverted puts every captured performer on their head.
        #
        # Negating Y alone would also mirror the pose (it flips handedness and
        # swaps left/right). Rotating 180 deg about X -- (x, -y, -z) -- is a
        # proper rotation (det = +1), so chirality is preserved and the
        # character ends up upright and facing +Z as documented.
        h36m_3d_m = h36m_3d_m * np.array([1.0, -1.0, -1.0], dtype=h36m_3d_m.dtype)

        # H36M-17 -> SMPL-24 (expand_joints expects mm input -> m output)
        smpl24 = expand_h36m17_to_smpl24_mm(h36m_3d_m * 1000.0)   # (T,24,3)
        return smpl24.astype(np.float32, copy=False)

    # ------------------------------------------------------------------
    # MotionBERT windowed inference
    # ------------------------------------------------------------------
    def _infer_motionbert(self, h36m_2d_norm: np.ndarray) -> np.ndarray:
        """Run the learned lifter with 243-frame windows, 50% overlap, averaged."""
        torch = self._torch
        assert torch is not None and self._model is not None
        T = h36m_2d_norm.shape[0]

        # Tiny clip: pad to window with edge replication.
        if T <= self.window:
            clip = h36m_2d_norm[:T]
            out = self._forward_chunk(clip)  # (T,17,3)
            return out.astype(np.float32)

        # Sliding windows with overlap.
        acc = np.zeros((T, 17, 3), dtype=np.float64)
        cnt = np.zeros((T, 1, 1), dtype=np.float64)
        starts = list(range(0, max(1, T - self.window + 1), self.stride))
        # ensure the tail is covered
        if starts[-1] + self.window < T:
            starts.append(max(0, T - self.window))

        for s in starts:
            e = min(T, s + self.window)
            clip = h36m_2d_norm[s:e]
            chunk = self._forward_chunk(clip)  # (L,17,3)
            L = chunk.shape[0]
            acc[s:s + L] += chunk
            cnt[s:s + L] += 1.0

        cnt = np.maximum(cnt, 1.0)
        out = (acc / cnt).astype(np.float32)
        return out

    def _forward_chunk(self, clip_2d_norm: np.ndarray) -> np.ndarray:
        """Run the model on one clip ``(L, 17, 2)`` -> ``(L, 17, 3)``."""
        torch = self._torch
        L = clip_2d_norm.shape[0]
        if L == 0:
            return np.zeros((0, 17, 3), dtype=np.float32)

        # pad to a multiple-friendly length (the model accepts any T, but real
        # weights were trained at 243; for L<243 we still feed directly since
        # our positional embedding is sliced to T).
        x = torch.from_numpy(clip_2d_norm.astype(np.float32)).unsqueeze(0)  # (1,L,17,2)
        x = x.to(self._device)
        if self.use_half and self._device.startswith("cuda"):
            x = x.half()

        with torch.no_grad():
            y = self._model(x)  # (1, L, 17, 3)

        y = y.squeeze(0).float().cpu().numpy()  # (L, 17, 3)
        return y


# expose at module level for convenience
NUM_BLAZEPOSE_JOINTS = 33


if __name__ == "__main__":  # pragma: no cover - manual smoke (no weights, no torch)
    est = MotionBERTEstimator()
    # synthetic BlazePose detections: a roughly standing person, normalized
    rng = np.random.default_rng(0)
    demo = np.zeros((20, 33, 4), dtype=np.float32)
    demo[..., 0] = 0.5  # x center
    demo[..., 1] = 0.5  # y center
    demo[..., 2] = 0.0
    demo[..., 3] = 0.9
    # perturb to avoid degenerate bone lengths
    demo[..., :2] += rng.normal(0, 0.01, demo[..., :2].shape).astype(np.float32)
    out = est.infer(demo)
    assert out.shape == (20, 24, 3), out.shape
    assert np.all(np.isfinite(out)), "non-finite 3D joint"
    mode = "MotionBERT" if est.has_motionbert else "geometric-lifter"
    print(f"pose_estimator_3d smoke: mode={mode}, output {out.shape}, all finite. OK")
