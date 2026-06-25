"""Bilibili (哔哩哔哩 / Bilibili) video downloader — BV id -> local video file.

Turns a Bilibili video number (BV 号 / BV id) into a local video file on disk,
so the rest of the mocap pipeline (frame extraction → 2D → 3D → IK → optimise →
export) can ingest it exactly like a locally-uploaded video.

Implementation
--------------
* Uses **yt-dlp** (https://github.com/yt-dlp/yt-dlp), which speaks Bilibili's
  web API, resolves stream URLs, picks the best muxed/progressive format and
  merges to ``.mp4``. yt-dlp is imported **lazily** so this module imports fine
  even when yt-dlp is not installed — the server endpoint then surfaces a clean
  503 instead of crashing at import time.
* Accepts the BV id in many shapes: ``BV1xx411c7mD``, ``bv1xx...``, a full
  ``https://www.bilibili.com/video/BV...`` URL, or with a ``?p=N`` part index.
* Optional cookies file (env ``TORCHMONKEY_BILI_COOKIES``) for higher-quality /
  member-only content — left entirely to the user to supply if they need it.
* A duration ceiling protects against accidentally pulling a 2-hour video.

Responsibility note
-------------------
This fetches ONE video the user explicitly names by BV id, for local
motion-capture analysis only. The user is responsible for having the rights to
download and analyse the chosen content (e.g. their own performances, or content
they are authorised to use). It is **not** a bulk / mass scraper and does not
redistribute anything. Treat it like pointing yt-dlp at a single URL by hand.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

# A canonical Bilibili BV id: "BV"/"bv" + exactly 10 alphanumerics (case-insensitive
# prefix, because users frequently type lowercase). Capture group = the id.
_BV_RE = re.compile(r"([Bb][Vv][0-9A-Za-z]{10})")
# A bare 10-char id without the "BV" prefix (we will prepend "BV").
_BARE_RE = re.compile(r"^[0-9A-Za-z]{10}$")
# Hosts whose URLs yt-dlp can resolve for us directly (bilibili.com / b23.tv).
_BILI_HOST_RE = re.compile(r"^https?://([^/]*\b)(bilibili\.com|b23\.tv)", re.IGNORECASE)

# Media extensions we consider as the downloaded result, in preference order.
_MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".flv", ".avi", ".mov")


class BilibiliDownloadError(Exception):
    """Raised when a BV id / URL is invalid or the download/probe fails."""


def normalize_bvid(bvid: str) -> str:
    """Extract a canonical ``BV`` + 10 chars from a BV id or bilibili URL.

    Accepts ``BV1xx411c7mD`` / ``bv1xx411c7mD`` / a bilibili.com video URL
    containing a BV id / a bare 10-char id. Returns the upper-case canonical id.
    Raises :class:`BilibiliDownloadError` if no BV id is present (e.g. a b23.tv
    short link with no BV in it — those need :func:`resolve_target` instead).
    """
    if not bvid or not isinstance(bvid, str):
        raise BilibiliDownloadError("Empty BV id / URL.")
    s = bvid.strip()
    m = _BV_RE.search(s)
    if m:
        return m.group(1).upper()
    if _BARE_RE.match(s):
        return ("BV" + s).upper()
    raise BilibiliDownloadError(
        f"Could not extract a Bilibili BV id from: {bvid!r}. "
        "Expected e.g. 'BV1xx411c7mD', 'bv...', or a bilibili.com video URL."
    )


def resolve_target(bvid_or_url: str, page: Optional[int] = None) -> tuple[str, str]:
    """Resolve user input to ``(url_for_yt_dlp, canonical_label)``.

    Handles, in order:
      1. A bilibili.com / b23.tv **URL** → passed straight to yt-dlp (which
         follows b23.tv redirects). Label = the BV id if one is embedded, else
         ``"bilibili"``.
      2. A BV id (``BV``/``bv`` + 10) → canonical bilibili.com watch URL.
      3. A bare 10-char id → ``BV`` prepended, then watch URL.

    ``page`` (1-based multi-part index) is appended as ``?p=N`` when meaningful.
    """
    if not bvid_or_url or not isinstance(bvid_or_url, str):
        raise BilibiliDownloadError("Empty BV id / URL.")
    s = bvid_or_url.strip()

    page_q = f"?p={int(page)}" if (page is not None and int(page) > 1) else ""

    # 1) Full URL on a bilibili host -> pass through to yt-dlp verbatim.
    if s.lower().startswith(("http://", "https://")) and _BILI_HOST_RE.search(s):
        url = s
        # If the user also gave a page and the URL has no ?p yet, append it.
        if page_q and "?p=" not in url:
            url += page_q
        bv = _BV_RE.search(s)
        label = bv.group(1).upper() if bv else "bilibili"
        return url, label

    # 2) Bare BV id (case-insensitive prefix).
    m = _BV_RE.search(s)
    if m:
        canon = m.group(1).upper()
        return f"https://www.bilibili.com/video/{canon}{page_q}", canon

    # 3) Bare 10-char id without prefix.
    if _BARE_RE.match(s):
        canon = ("BV" + s).upper()
        return f"https://www.bilibili.com/video/{canon}{page_q}", canon

    raise BilibiliDownloadError(
        f"Unrecognised Bilibili input: {bvid_or_url!r}. "
        "Expected a BV id (e.g. BV1xx411c7mD) or a bilibili.com / b23.tv URL."
    )



def _resolve_cookies(cookies_path: Optional[str]) -> Optional[str]:
    return cookies_path or os.environ.get("TORCHMONKEY_BILI_COOKIES") or None


def _resolve_downloaded(out_dir: Path, stem: str) -> Path:
    """Find the file yt-dlp actually wrote, given the outtmpl ``{stem}.%(ext)s``.

    Prefers ``.mp4`` (the merge target), then falls back to any other media
    extension. Picks the largest matching file to be safe.
    """
    candidates: list[Path] = []
    for ext in _MEDIA_EXTS:
        candidates.extend(out_dir.glob(f"{stem}{ext}"))
        candidates.extend(out_dir.glob(f"{stem}.*{ext}"))
    # Also catch yt-dlp's temporary ".part"/".webp" leftovers is NOT wanted; only
    # finished media. If nothing matched, broaden to any file starting with stem.
    if not candidates:
        candidates = [p for p in out_dir.glob(f"{stem}*") if p.is_file()]
    candidates = [p for p in candidates if p.is_file() and p.stat().st_size > 0]
    if not candidates:
        raise BilibiliDownloadError(
            f"Download finished but no output file found for stem '{stem}' in {out_dir}."
        )
    candidates.sort(key=lambda p: (p.suffix.lower() != ".mp4", -p.stat().st_size))
    return candidates[0]


def probe_bilibili(
    bvid: str,
    page: Optional[int] = None,
    cookies_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve metadata (title / duration / uploader / BV id) **without** downloading.

    Cheap probe used by the preview endpoint so the UI can show the user what
    they are about to capture before committing to a download.
    """
    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise BilibiliDownloadError(
            "yt-dlp is not installed. Install it with:  pip install yt-dlp"
        ) from exc

    url, label = resolve_target(bvid, page)
    cookies = _resolve_cookies(cookies_path)

    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    if cookies:
        opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[name-defined]
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt-dlp raises various exception types
        raise BilibiliDownloadError(f"yt-dlp probe failed for {label}: {exc}") from exc

    if not isinstance(info, dict):
        raise BilibiliDownloadError(f"Unexpected probe result for {label}.")
    return {
        "bvid": label,
        "url": url,
        "title": info.get("title", label),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": float(info.get("duration") or 0.0),
        "page": int(page) if page else 1,
    }


def download_bilibili(
    bvid: str,
    out_dir: Path,
    page: Optional[int] = None,
    cookies_path: Optional[str] = None,
    max_duration_sec: float = 900.0,
) -> Dict[str, Any]:
    """Download a single Bilibili video and return its local path + metadata.

    Parameters
    ----------
    bvid
        BV id, bare id, or full bilibili.com URL.
    out_dir
        Directory to write the downloaded ``.mp4`` into (created if missing).
    page
        Optional multi-part (P) index, 1-based. ``None`` or ``1`` = the main video.
    cookies_path
        Optional path to a Netscape cookies file (e.g. exported from the user's
        browser). Falls back to the ``TORCHMONKEY_BILI_COOKIES`` env var.
    max_duration_sec
        Refuse videos longer than this (default 15 min) to avoid accidental huge
        downloads. Set to 0 / negative to disable the cap.

    Returns
    -------
    dict with keys: ``video_path`` (str), ``title`` (str), ``duration`` (float,
    seconds), ``url`` (str), ``bvid`` (canonical), ``page`` (int).

    Raises
    ------
    BilibiliDownloadError
        on invalid id, missing yt-dlp, over-duration content, or download failure.
    """
    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise BilibiliDownloadError(
            "yt-dlp is not installed. Install it with:  pip install yt-dlp"
        ) from exc

    url, label = resolve_target(bvid, page)
    cookies = _resolve_cookies(cookies_path)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Safe stem for the output file: BV id if known, else a sanitized label.
    safe_label = label if label.startswith("BV") else "bilibili"
    stem = safe_label if (page is None or int(page) <= 1) else f"{safe_label}_p{int(page)}"

    opts: Dict[str, Any] = {
        "outtmpl": str(out_dir / f"{stem}.%(ext)s"),
        "merge_output_format": "mp4",
        # Prefer a single progressive mp4; fall back to best A/V merge.
        "format": "bestvideo*+bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
    }
    if cookies:
        opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[name-defined]
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise BilibiliDownloadError(f"yt-dlp download failed for {label}: {exc}") from exc

    if not isinstance(info, dict):
        raise BilibiliDownloadError(f"Unexpected download result for {label}.")

    duration = float(info.get("duration") or 0.0)
    if max_duration_sec and duration > max_duration_sec and duration > 0:
        # Clean up any partial file before refusing.
        for p in out_dir.glob(f"{stem}*"):
            try:
                p.unlink()
            except OSError:
                pass
        raise BilibiliDownloadError(
            f"Video is {duration:.0f}s long (>{max_duration_sec:.0f}s cap). "
            "Trim it first or raise the duration cap."
        )

    video_path = _resolve_downloaded(out_dir, stem)
    return {
        "video_path": str(video_path),
        "title": info.get("title", label),
        "duration": duration,
        "url": url,
        "bvid": label,
        "page": int(page) if page else 1,
    }
