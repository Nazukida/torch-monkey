#!/usr/bin/env python3
"""Torch Monkey environment doctor — one command to see what's wrong.

Prints a green/red table of everything the AI mocap pipeline needs:

  * interpreter (Python >= 3.10), pip
  * ffmpeg / ffprobe on PATH (or via TORCHMONKEY_FFPROBE / TORCHMONKEY_FFMPEG)
  * Python deps: torch (+ CUDA / device / VRAM), mediapipe, opencv, numpy,
    scipy, yt-dlp, rich
  * model weights under ``python/models/`` (MediaPipe + MotionBERT)
  * GPU presence (nvidia-smi)

Exit code = number of *problems* (a missing hard dependency or model weight).
Soft/optional items (ffmpeg, yt-dlp, rich, torch-on-CPU) are reported as
warnings but do not change the exit code, so a pure-CPU dev machine that can
still run the IK self-test passes cleanly.

Run (no venv required):
    python tools/check_env.py
    python tools/check_env.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from importlib import util as importlib_util
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow running from anywhere (like download_models.py).
_HERE = Path(__file__).resolve().parent
_PYTHON_ROOT = _HERE.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

try:
    from config import settings  # noqa: E402
except Exception:  # pragma: no cover - config always present in-tree
    settings = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Individual probes. Each returns (status, detail). status in {ok, warn, fail}.
# ---------------------------------------------------------------------------
def _ver_tuple(v: str) -> Tuple[int, ...]:
    out: List[int] = []
    for part in v.split("."):
        try:
            out.append(int(part))
        except ValueError:
            break
    return tuple(out)


def probe_python() -> Tuple[str, str]:
    v = platform.python_version()
    impl = platform.python_implementation()
    if _ver_tuple(v) >= (3, 10):
        return "ok", f"{impl} {v}"
    return "fail", f"{impl} {v} (需要 >= 3.10 / requires >= 3.10)"


def probe_pip() -> Tuple[str, str]:
    if importlib_util.find_spec("pip"):
        try:
            return "ok", f"pip {metadata.version('pip')}"
        except Exception:
            return "ok", "pip (版本未知 / version unknown)"
    return "warn", "pip 未找到 / pip not found"


def _dep(name: str, display: Optional[str] = None, dist: Optional[str] = None,
         optional: bool = False) -> Tuple[str, str]:
    """Probe an importable Python package; return its version.

    ``name`` is the *import* name (e.g. ``cv2``); ``dist`` is the optional
    *distribution* name used to look up the version (e.g. ``opencv-python``)
    when it differs from the import name.
    """
    label = display or name
    if not importlib_util.find_spec(name):
        if optional:
            return "warn", f"{label}: 未安装 / not installed (可选 / optional)"
        return "fail", f"{label}: 未安装 / not installed"
    ver: Any = "已安装 / installed"
    for candidate in (dist, name):
        if not candidate:
            continue
        try:
            ver = metadata.version(candidate)
            break
        except Exception:
            continue
    return "ok", f"{label} {ver}"


def probe_torch() -> Tuple[str, str]:
    if not importlib_util.find_spec("torch"):
        return "warn", "torch: 未安装（CPU 几何提升器仍可用 / CPU geometric lifter still works)"
    try:
        import torch  # type: ignore
        ver = getattr(torch, "__version__", "?")
        if torch.cuda.is_available():
            try:
                name = torch.cuda.get_device_name(0)
            except Exception:
                name = "cuda"
            try:
                free, total = torch.cuda.mem_get_info()
                vram = f"{total / 1048576.0:.0f}MB"
            except Exception:
                vram = "?"
            return "ok", f"torch {ver} · CUDA · {name} · VRAM {vram}"
        return "ok", f"torch {ver} · CPU (无 CUDA / no CUDA)"
    except Exception as exc:  # corrupted install
        return "fail", f"torch: 导入失败 / import failed: {exc}"


def probe_bin(env_var: str, default: str, label: str) -> Tuple[str, str]:
    name = os.environ.get(env_var, default)
    p = Path(name)
    try:
        if p.is_file():
            return "ok", f"{label}: {p}"
    except Exception:
        pass
    found = shutil.which(name)
    if found:
        return "ok", f"{label}: {found}"
    return "warn", f"{label}: 未找到 / not found (设置 {env_var} 或加入 PATH / set {env_var} or add to PATH)"


def probe_gpu() -> Tuple[str, str]:
    nvidia = shutil.which("nvidia-smi")
    if not nvidia:
        return "warn", "GPU: 未检测到 nvidia-smi (CPU 推理 / CPU inference)"
    try:
        out = subprocess.run(
            [nvidia, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        line = (out.stdout or "").strip().splitlines()
        if line:
            return "ok", f"GPU: {line[0]}"
    except Exception:
        pass
    return "warn", "GPU: nvidia-smi 存在但无法查询 / nvidia-smi present but not queryable"


def _model_status(filename: str, min_bytes: int) -> Tuple[str, str]:
    if settings is None:
        return "fail", f"{filename}: config 未加载 / config not loaded"
    p = settings.MODELS_DIR / filename
    if not p.is_file():
        return "fail", f"{filename}: 缺失 / missing"
    size = p.stat().st_size
    if size < min_bytes:
        return "fail", f"{filename}: 过小 / truncated ({size} bytes)"
    return "ok", f"{filename}: {size / 1e6:.1f} MB"


def probe_models() -> List[Tuple[str, str, str]]:
    """Returns a list of (name, status, detail) for each model weight."""
    return [
        ("MediaPipe (pose_landmarker_heavy.task)",
         *_model_status("pose_landmarker_heavy.task", 5_000_000)),
        ("MotionBERT (mb3d.pth)",
         *_model_status("mb3d.pth", 5_000_000)),
    ]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def collect() -> Dict[str, Any]:
    """Run every probe and return a structured report."""
    checks: List[Dict[str, str]] = []

    def add(section: str, name: str, result: Tuple[str, str]) -> None:
        status, detail = result
        checks.append({"section": section, "name": name,
                       "status": status, "detail": detail})

    add("解释器 / Interpreter", "Python", probe_python())
    add("解释器 / Interpreter", "pip", probe_pip())

    add("外部二进制 / Binaries", "ffmpeg", probe_bin("TORCHMONKEY_FFMPEG", "ffmpeg", "ffmpeg"))
    add("外部二进制 / Binaries", "ffprobe", probe_bin("TORCHMONKEY_FFPROBE", "ffprobe", "ffprobe"))

    add("Python 依赖 / Deps", "torch", probe_torch())
    # opencv ships under the cv2 import name.
    add("Python 依赖 / Deps", "opencv", _dep("cv2", "opencv-python", dist="opencv-python"))
    add("Python 依赖 / Deps", "mediapipe", _dep("mediapipe"))
    add("Python 依赖 / Deps", "numpy", _dep("numpy"))
    add("Python 依赖 / Deps", "scipy", _dep("scipy"))
    add("Python 依赖 / Deps", "yt-dlp", _dep("yt_dlp", "yt-dlp", optional=True))
    add("Python 依赖 / Deps", "rich", _dep("rich", optional=True))

    add("硬件 / Hardware", "GPU", probe_gpu())

    for name, status, detail in probe_models():
        add("模型权重 / Models", name, (status, detail))

    problems = sum(1 for c in checks if c["status"] == "fail")
    return {"checks": checks, "problems": problems}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
_SYMBOL = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}


def render_text(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Torch Monkey — 环境自检 / Environment check")
    lines.append("=" * 64)
    last_section = ""
    for c in report["checks"]:
        if c["section"] != last_section:
            lines.append("")
            lines.append(f"[{c['section']}]")
            last_section = c["section"]
        lines.append(f"  {_SYMBOL[c['status']]} {c['name']:<10}  {c['detail']}")
    lines.append("")
    lines.append("=" * 64)
    n = report["problems"]
    if n == 0:
        lines.append("结果 / Result: 全部就绪 / all green ✅")
    else:
        lines.append(f"结果 / Result: {n} 项问题 / problem(s) — 见上方 ❌ 标记。")
        lines.append("  一键修复 / fix in one command:  npm run setup")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    # Windows consoles default to a legacy code page (e.g. GBK) that cannot
    # encode the check/cross symbols below. Force UTF-8 so the table renders.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON instead of a table.")
    args = parser.parse_args(argv)

    report = collect()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return report["problems"]


if __name__ == "__main__":
    raise SystemExit(main())
