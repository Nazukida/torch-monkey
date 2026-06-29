#!/usr/bin/env python3
"""Torch Monkey — live terminal dashboard for the AI mocap pipeline.

A standalone viewer (no model deps, no venv required) that polls the running
``server.py`` and renders, once a second:

  * connection: endpoint, latency, server host bind;
  * models:     which subsystems are ready (mediapipe / motionbert / …);
  * runtime:    device / CUDA / GPU name / VRAM / torch / ffmpeg / yt-dlp;
  * tasks:      every active + recent task with a progress bar and stage.

It runs **wherever you can reach the server's HTTP port**:
  * on the Linux GPU box itself:        ``python tools/dashboard.py``
  * on the Windows client over a tunnel: ``python tools/dashboard.py``
                                            (after ``ssh -L 19876:127.0.0.1:19876 …``)
  * against a LAN-exposed server:        ``python tools/dashboard.py --url http://<ip>:19876``

Uses ``rich`` for a colour panel when available; otherwise degrades to a plain
plain-text table (``rich`` is optional). Ctrl-C exits cleanly.

This is the answer to "I want to watch each pipeline step from the terminal" —
especially useful when training on a remote GPU server.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# Force UTF-8 on Windows consoles so the block characters / Chinese render.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

try:  # optional dependency
    from rich.console import Console, Group  # type: ignore
    from rich.live import Live  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from rich.text import Text  # type: ignore
    HAVE_RICH = True
except Exception:  # pragma: no cover - optional
    HAVE_RICH = False

DEFAULT_URL = os.environ.get("TORCHMONKEY_DASHBOARD_URL", "http://127.0.0.1:19876")


def enable_vt() -> None:
    """Enable ANSI VT processing on the Windows console (no-op elsewhere).

    The plain-text fallback uses ``\\033[2J\\033[H`` to clear/refresh in place;
    modern Windows 10/11 consoles support it but only once VT mode is on. On
    non-Windows this does nothing.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            kernel32.SetConsoleMode(h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass

# Friendly bilingual labels for the pipeline stages emitted by ProgressBroker.
STAGE_LABELS: Dict[str, str] = {
    "init":           "初始化 init",
    "download":       "下载 download",
    "extract_frames": "抽帧 frames",
    "pose_2d":        "2D 关键点 pose2d",
    "pose_3d":        "3D 提升 MotionBERT",
    "optimize":       "打艺优化 optimize",
    "export":         "导出 export",
}


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------
def fetch_json(url: str, timeout: float = 3.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "torch-monkey-dashboard"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def poll(base_url: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Fetch health + tasks. Always returns a dict; ``ok`` indicates success.

    Never raises: any network or response-shape error is converted to an
    ``ok: False`` result so the live loop keeps running even against a stale or
    malformed server (e.g. a misrouted tunnel returning arbitrary JSON).
    """
    base = base_url.rstrip("/")
    try:
        t0 = time.time()
        health = fetch_json(base + "/api/health", timeout)
        if not isinstance(health, dict):
            raise ValueError(f"health: expected JSON object, got {type(health).__name__}")
        latency = (time.time() - t0) * 1000.0
        raw_tasks = fetch_json(base + "/api/tasks", timeout)
        if isinstance(raw_tasks, dict):
            tasks = raw_tasks.get("tasks", []) or []
        elif isinstance(raw_tasks, list):
            tasks = raw_tasks
        else:
            tasks = []
        if not isinstance(tasks, list):
            tasks = []
        return {"ok": True, "health": health, "tasks": tasks,
                "latency_ms": latency, "error": None}
    except Exception as exc:
        return {"ok": False, "health": None, "tasks": [],
                "latency_ms": None, "error": f"{type(exc).__name__}: {exc}"}


def bar(pct: Optional[float], width: int = 18) -> str:
    p = max(0.0, min(1.0, float(pct or 0.0)))
    filled = int(round(p * width))
    return "█" * filled + "░" * (width - filled)


def _yesno(v: Any) -> str:
    return "✅" if v else "❌"


# ---------------------------------------------------------------------------
# Rich rendering
# ---------------------------------------------------------------------------
def _rich_models(health: Dict[str, Any]) -> Table:
    models = health.get("models", {}) or {}
    table = Table(title="模型就绪 / Models", expand=True, box=None)
    table.add_column("子系统 subsystem", style="cyan", no_wrap=True)
    table.add_column("状态 status", justify="center")
    rows = [
        ("MediaPipe 2D", models.get("mediapipe")),
        ("MotionBERT 3D", models.get("motionbert")),
        ("WotageiOptimizer", models.get("optimizer")),
        ("FormatExporter", models.get("exporter")),
        ("Video decode (OpenCV)", models.get("video_decode")),
    ]
    for name, ok in rows:
        table.add_row(name, _yesno(ok))
    table.add_row("[bold]整体 ready[/bold]", _yesno(models.get("ready")))
    return table


def _rich_runtime(rt: Dict[str, Any]) -> Table:
    table = Table(title="运行时 / Runtime", expand=True, box=None)
    table.add_column("项 item", style="cyan", no_wrap=True)
    table.add_column("值 value")
    device = rt.get("device", "?")
    if rt.get("cuda_available"):
        vram = ""
        if rt.get("gpu_mem_total_mb") is not None:
            used = rt.get("gpu_mem_used_mb", 0) or 0
            total = rt.get("gpu_mem_total_mb", 0) or 0
            vram = f" · VRAM {used:.0f}/{total:.0f} MB"
        device_line = f"[bold green]cuda[/bold green] · {rt.get('device_name','?')}{vram}"
    elif rt.get("torch_installed"):
        device_line = "[yellow]cpu[/yellow] (无 CUDA / no CUDA)"
    else:
        device_line = "[red]torch 未安装 / torch not installed[/red]"
    table.add_row("Device", device_line)
    table.add_row("torch", str(rt.get("torch_version") or "—"))
    table.add_row("Python", str(rt.get("python") or "—"))
    table.add_row("Platform", str(rt.get("platform") or "—"))
    table.add_row("ffmpeg", _yesno(rt.get("ffmpeg")))
    table.add_row("ffprobe", _yesno(rt.get("ffprobe")))
    table.add_row("yt-dlp", _yesno(rt.get("yt_dlp")))
    return table


def _rich_tasks(tasks: List[Dict[str, Any]]) -> Table:
    table = Table(title="任务 / Tasks", expand=True, box=None)
    table.add_column("task", style="cyan", no_wrap=True)
    table.add_column("状态 status", justify="center")
    table.add_column("stage")
    table.add_column("进度 progress", ratio=1)
    if not tasks:
        table.add_row("[dim]（无任务 / idle）[/dim]", "", "", "")
        return table
    for t in tasks[:12]:
        status = t.get("status") or "?"
        pct = t.get("progress", 0.0)
        stage = STAGE_LABELS.get(t.get("stage", ""), t.get("stage") or "—")
        age = t.get("age")
        age_s = f"{age:.0f}s" if isinstance(age, (int, float)) else ""
        if status == "completed":
            color, mark = "green", "✅"
        elif status == "error":
            color, mark = "red", "❌"
        else:
            color, mark = "cyan", "▶"
        label = (t.get("message") or status)
        if len(label) > 26:
            label = label[:25] + "…"
        barcell = Text(f"{bar(pct)} {pct*100:5.1f}%", style=color)
        table.add_row(f"{mark} {label}\n   [dim]{age_s}[/dim]",
                      Text(status, style=color), stage, barcell)
    return table


def render_rich(state: Dict[str, Any], base_url: str) -> Any:
    if not state.get("ok"):
        return Panel(
            Text(f"连接中 / connecting…\n{base_url}\n{state.get('error','')}",
                 style="yellow"),
            title="Torch Monkey Pipeline — offline", border_style="yellow")

    h = state["health"] or {}
    rt = h.get("runtime", {}) or {}
    host = h.get("host", "?")
    latency = state.get("latency_ms")
    head = Text.assemble(
        ("Torch Monkey AI Pipeline", "bold white"),
        (f"   {base_url}", "cyan"),
        (f"   bind={host}", "dim"),
        (f"   {latency:.0f}ms" if latency else "", "green"),
    )
    body = Group(_rich_models(h), _rich_runtime(rt), _rich_tasks(state["tasks"]))
    title = "✅ online · " + ("CUDA" if rt.get("cuda_available") else "CPU")
    return Panel(body, title=title, subtitle="Ctrl-C 退出 / to exit", border_style="cyan")


# ---------------------------------------------------------------------------
# Plain-text rendering (rich absent)
# ---------------------------------------------------------------------------
def render_plain(state: Dict[str, Any], base_url: str) -> str:
    L: List[str] = []
    L.append("=" * 68)
    L.append(f"  Torch Monkey AI Pipeline   {base_url}")
    L.append("=" * 68)
    if not state.get("ok"):
        L.append(f"  [连接中 / connecting…] {state.get('error','')}")
        L.append("  确认 server.py 已启动 / make sure server.py is running.")
        return "\n".join(L)

    h = state["health"] or {}
    rt = h.get("runtime", {}) or {}
    models = h.get("models", {}) or {}
    latency = state.get("latency_ms")
    L.append(f"  bind={h.get('host','?')}   latency={latency:.0f}ms"
             + ("   [CUDA]" if rt.get("cuda_available") else "   [CPU]"))
    L.append("")
    L.append("  [模型 / Models]")
    for name, ok in [("MediaPipe", models.get("mediapipe")),
                     ("MotionBERT", models.get("motionbert")),
                     ("Optimizer", models.get("optimizer")),
                     ("Exporter", models.get("exporter")),
                     ("VideoDecode", models.get("video_decode"))]:
        L.append(f"    {_yesno(ok)} {name}")
    L.append("")
    L.append("  [运行时 / Runtime]")
    if rt.get("cuda_available"):
        vram = ""
        if rt.get("gpu_mem_total_mb") is not None:
            vram = f"  VRAM {rt.get('gpu_mem_used_mb',0):.0f}/{rt.get('gpu_mem_total_mb',0):.0f}MB"
        L.append(f"    device: cuda · {rt.get('device_name','?')}{vram}")
    else:
        L.append(f"    device: {rt.get('device','?')} (torch installed: {rt.get('torch_installed')})")
    L.append(f"    torch={rt.get('torch_version') or '—'}  python={rt.get('python') or '—'}")
    L.append(f"    ffmpeg={_yesno(rt.get('ffmpeg'))}  ffprobe={_yesno(rt.get('ffprobe'))}  yt-dlp={_yesno(rt.get('yt_dlp'))}")
    L.append("")
    L.append("  [任务 / Tasks]")
    tasks = state["tasks"]
    if not tasks:
        L.append("    （无任务 / idle）")
    for t in tasks[:12]:
        status = t.get("status") or "?"
        pct = t.get("progress", 0.0)
        stage = STAGE_LABELS.get(t.get("stage", ""), t.get("stage") or "—")
        msg = (t.get("message") or status)
        if len(msg) > 28:
            msg = msg[:27] + "…"
        L.append(f"    [{status:<9}] {bar(pct, 14)} {pct*100:5.1f}%  {msg}")
        L.append(f"                 stage: {stage}")
    L.append("")
    L.append("  Ctrl-C 退出 / to exit.   Refresh via /api/health + /api/tasks.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL,
                        help=f"Pipeline base URL (default {DEFAULT_URL}; "
                             "or env TORCHMONKEY_DASHBOARD_URL).")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Refresh interval in seconds (default 1.0).")
    parser.add_argument("--plain", action="store_true",
                        help="Force plain-text output even if rich is installed.")
    parser.add_argument("--once", action="store_true",
                        help="Render once and exit (handy for scripts / CI).")
    args = parser.parse_args(argv)

    use_rich = HAVE_RICH and not args.plain

    if args.once:
        state = poll(args.url)
        if use_rich:
            Console().print(render_rich(state, args.url))
        else:
            print(render_plain(state, args.url))
        return 0 if state.get("ok") else 1

    print("Torch Monkey dashboard — connecting to", args.url, "  (Ctrl-C 退出 / to exit)")
    enable_vt()
    try:
        if use_rich:
            console = Console()
            with Live(console=console, refresh_per_second=4) as live:
                while True:
                    live.update(render_rich(poll(args.url), args.url))
                    time.sleep(args.interval)
        else:
            clear = "\033[2J\033[H"
            while True:
                sys.stdout.write(clear)
                sys.stdout.write(render_plain(poll(args.url), args.url) + "\n")
                sys.stdout.flush()
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nbye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
