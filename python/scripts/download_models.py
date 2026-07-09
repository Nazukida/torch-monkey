#!/usr/bin/env python3
"""Download the AI model weights required by the Torch Monkey pipeline.

Fetches into ``python/models/``:

  1. MediaPipe Pose Landmarker ``pose_landmarker_heavy.task``
     - The most accurate BlazePose variant (Apache-2.0 / Google).
     - Canonical source (storage.googleapis.com).
     - Used by ``pipeline.pose_estimator_2d.MediaPipeEstimator``.

  2. MotionBERT 3D-lifting checkpoint (``mb3d.pth``)
     - Walter0807/MotionBERT on Hugging Face (MIT).
     - Vendored loader lives in ``lib.motionbert_model``; the pipeline expects
       one of the names in ``config.settings.MOTIONBERT_MODEL_FILENAMES``.

Design:
  * Pure urllib (no requests dependency at runtime) for portability; falls back
    to huggingface_hub if installed.
  * Idempotent: skips any file that already exists and is non-empty.
  * Verifies a minimum size after download to catch truncated transfers.
  * Prints clear next-step instructions at the end.

Run:
    python scripts/download_models.py
    python scripts/download_models.py --force
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

# Allow `python scripts/download_models.py` from the repo regardless of cwd.
_HERE = Path(__file__).resolve().parent
_PYTHON_ROOT = _HERE.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

from config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Canonical source URLs (documented, single source of truth)
# ---------------------------------------------------------------------------

# MediaPipe Pose Landmarker task bundle (heavy). Public Google storage URL.
# Reference: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
MEDIAPIPE_URLS = [
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task",
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
]

# MotionBERT 3D-lifting checkpoint. The canonical release is Walter0807/MotionBERT
# on Hugging Face (MIT license). The checkpoint is the full DSTformer (att_fuse)
# pose-lifting model trained on Human3.6M (input: 2D+conf 17-joint, output: 3D).
# Loader: lib.dstformer_model.load_dstformer
# Reference: https://github.com/Walter0807/MotionBERT
#            https://huggingface.co/Walter0807/MotionBERT
MOTIONBERT_URLS = [
    # Hugging Face resolve endpoints (LFS-backed raw file download).
    "https://huggingface.co/Walter0807/MotionBERT/resolve/main/checkpoint/mb3d.pth",
    "https://huggingface.co/Walter0807/MotionBERT/resolve/main/pose_lift/mb3d.pth",
    "https://huggingface.co/Walter0807/MotionBERT/resolve/main/mb3d.pth",
]

# Minimum plausible sizes to detect truncated downloads (bytes).
MIN_SIZE_BYTES = {
    "pose_landmarker_heavy.task": 5_000_000,    # ~9 MB heavy task
    "mb3d.pth": 5_000_000,                       # MotionBERT lite is ~10-50 MB
}


def _progress(block_num: int, block_size: int, total_size: int) -> None:
    """urllib reporthook callback: print a simple progress line."""
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100.0, downloaded * 100.0 / total_size)
        sys.stdout.write(
            f"\r  ... {downloaded / 1e6:7.2f} / {total_size / 1e6:7.2f} MB ({pct:5.1f}%)"
        )
        sys.stdout.flush()
    else:
        sys.stdout.write(f"\r  ... {downloaded / 1e6:7.2f} MB")
        sys.stdout.flush()


def _download_one(url: str, dest: Path, min_size: int, timeout: float = 60.0) -> bool:
    """Download ``url`` to ``dest``. Returns True on success."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "torch-monkey/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, \
                open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out, length=8 * 1024 * 1024)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"    failed: {exc}")
        tmp.unlink(missing_ok=True)
        return False

    actual = tmp.stat().st_size
    if actual < min_size:
        print(f"    truncated ({actual} < {min_size} bytes), discarding.")
        tmp.unlink(missing_ok=True)
        return False

    tmp.replace(dest)
    print(f"    ok ({actual / 1e6:.1f} MB) -> {dest.name}")
    return True


def download_from_candidates(
    urls: Iterable[str],
    dest: Path,
    min_size: int,
    force: bool,
) -> bool:
    """Try each URL in turn until one succeeds. Returns True if ``dest`` ends
    up populated."""
    if dest.is_file() and dest.stat().st_size >= min_size and not force:
        print(f"  [skip] {dest.name} already present ({dest.stat().st_size / 1e6:.1f} MB)")
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    for url in urls:
        if _download_one(url, dest, min_size):
            return True
    return False


def _try_hf_motionbert(dest: Path, force: bool) -> bool:
    """Optional fast path using huggingface_hub if the user has it installed."""
    if dest.is_file() and dest.stat().st_size >= MIN_SIZE_BYTES["mb3d.pth"] and not force:
        return True
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except Exception:
        return False
    print("  (using huggingface_hub)")
    for fname in ("checkpoint/mb3d.pth", "pose_lift/mb3d.pth", "mb3d.pth"):
        try:
            path = hf_hub_download(
                repo_id="Walter0807/MotionBERT",
                filename=fname,
                local_dir=str(dest.parent),
                local_dir_use_symlinks=False,
            )
            downloaded = Path(path)
            if downloaded.is_file() and downloaded.stat().st_size >= MIN_SIZE_BYTES["mb3d.pth"]:
                if downloaded.resolve() != dest.resolve():
                    shutil.move(str(downloaded), str(dest))
                print(f"    ok ({dest.stat().st_size / 1e6:.1f} MB) -> {dest.name}")
                return True
        except Exception as exc:
            print(f"    hf_hub_download({fname!r}) failed: {exc}")
    return False


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if files already exist.")
    parser.add_argument("--models-dir", default=str(settings.MODELS_DIR),
                        help="Override the models directory.")
    args = parser.parse_args(argv)

    models_dir = Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    print(f"Torch Monkey model downloader")
    print(f"  target dir: {models_dir}")
    print(f"  force: {args.force}")
    print()

    # ---- MediaPipe ---------------------------------------------------------
    print("[1/2] MediaPipe Pose Landmarker (heavy)")
    mp_dest = models_dir / settings.MEDIAPIPE_MODEL_FILENAME
    mp_ok = download_from_candidates(
        MEDIAPIPE_URLS, mp_dest,
        MIN_SIZE_BYTES["pose_landmarker_heavy.task"], args.force,
    )
    if not mp_ok:
        print(f"  !! Could not download {settings.MEDIAPIPE_MODEL_FILENAME}.")
        print("     Get it manually from:")
        print("     https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task")
        print(f"     and place it at: {mp_dest}")

    # ---- MotionBERT --------------------------------------------------------
    print()
    print("[2/2] MotionBERT 3D-lifting checkpoint (mb3d.pth)")
    mb_dest = models_dir / settings.MOTIONBERT_MODEL_FILENAMES[0]
    mb_ok = _try_hf_motionbert(mb_dest, args.force)
    if not mb_ok:
        mb_ok = download_from_candidates(
            MOTIONBERT_URLS, mb_dest,
            MIN_SIZE_BYTES["mb3d.pth"], args.force,
        )
    if not mb_ok:
        print(f"  !! Could not download the MotionBERT checkpoint.")
        print("     Get it manually from Hugging Face (Walter0807/MotionBERT):")
        print("     https://huggingface.co/Walter0807/MotionBERT")
        print("     and place 'mb3d.pth' at: " + str(mb_dest))

    # ---- Summary -----------------------------------------------------------
    print()
    print("Summary:")
    print(f"  MediaPipe  : {'OK ' if mp_ok else 'MISSING'}  {mp_dest}")
    print(f"  MotionBERT : {'OK ' if mb_ok else 'MISSING'}  {mb_dest}")
    print()
    if mp_ok and mb_ok:
        print("All models present. Start the server:")
        print("    python server.py")
    else:
        print("Some models are missing — see messages above. The server will")
        print("still boot and /api/health will report which subsystems are ready.")
        print("Without weights, 3D lifting falls back to an anthropometric lifter.")
    return 0 if (mp_ok and mb_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
