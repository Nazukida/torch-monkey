# Torch Monkey — Python AI Mocap Pipeline

Stage 4 of Torch Monkey. A local FastAPI service that turns a Wota-艺 performance
video into a Torch Monkey `MotionData` JSON (SMPL_24 skeleton) that the Electron
app drops straight into the motion library.

Pipeline:

```
video ─► VideoProcessor.extract_frames    (OpenCV, ffprobe metadata)
      ─► MediaPipeEstimator.process_batch (BlazePose 33 → 2D)
      ─► MotionBERTEstimator.infer        (MotionBERT → 3D → SMPL_24 metres)
      ─► WotageiOptimizer.optimize        (median/Butterworth + kime detection)
      ─► FormatExporter.to_motion_data    (MotionData JSON, local quaternions)
```

## Requirements

- Python 3.10+
- `ffmpeg` / `ffprobe` on `PATH` (used by `VideoProcessor` for metadata). On
  Windows add the `ffmpeg\bin` folder to your PATH, or set
  `TORCHMONKEY_FFPROBE` / `TORCHMONKEY_FFMPEG` to the full binary path.

## Setup

```bash
cd python

# 1. (CPU / dev machine) install dependencies
pip install -r requirements.txt

# 2. (GPU machine) install the CUDA build of torch FIRST, then the rest
#    CUDA 12.1 (most common on modern RTX cards):
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
#    CUDA 11.8:
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu118
pip install -r requirements.txt   # pip keeps the CUDA torch you just installed
```

> `requirements.txt` pins the CPU torch wheel. On a GPU machine, install the
> CUDA wheel from the index URL **before** running `pip install -r requirements.txt`
> so pip does not downgrade it.

## Download model weights

```bash
python scripts/download_models.py
```

This fetches into `python/models/`:

| File | Source |
|------|--------|
| `pose_landmarker_heavy.task` | Google MediaPipe storage (Apache-2.0) |
| `mb3d.pth` | `Walter0807/MotionBERT` on Hugging Face (MIT) |

The script is idempotent (skips files already present) and prints clear manual
fallback instructions if a URL is unreachable. If a weight is missing the
server still boots — `/api/health` reports which subsystems are ready, and the
3D lifter falls back to an anthropometric geometric lifter so the pipeline
produces plausible output.

## Run

```bash
python server.py                 # default 127.0.0.1:19876
python server.py --port 19877    # override port
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/health`             | Pipeline readiness (which models loaded). Always 200. |
| POST | `/api/preview-video`      | ffprobe metadata only (multipart `file`). No AI. |
| POST | `/api/process-video`      | Full pipeline. Returns `motion_data` + `stats`. |
| GET  | `/api/progress/{task_id}` | Per-task progress (status/progress/stage/message). |

`/api/process-video` query params: `fps` (default 30), `smooth` (bool),
`detect_kime` (bool). Body is a multipart `file` upload.

CORS allows `http(s)://localhost:*`, `127.0.0.1:*`, and the Electron `app://.`
scheme.

## Accuracy self-test (no GPU, no weights)

The IK solver is verified by a closed-loop test that needs only numpy:

```bash
python tools/selftest_pipeline.py
```

It synthesises known motions (a hand drawing a horizontal circle, a wave),
converts positions → per-joint local quaternions → Forward Kinematics, and
asserts the FK-reconstructed positions match the inputs within tolerance. Prints
a clear PASS/FAIL with per-joint error stats. See
[`tools/forward_kinematics.py`](tools/forward_kinematics.py) for the reference FK.

## Layout

```
python/
├── server.py                  # FastAPI app (this README's subject)
├── requirements.txt
├── config/settings.py         # paths, defaults, model filenames
├── pipeline/
│   ├── video_processor.py     # ffprobe + OpenCV frame extraction
│   ├── pose_estimator_2d.py   # MediaPipe BlazePose (33)
│   ├── pose_estimator_3d.py   # MotionBERT -> SMPL_24 (24 joints)
│   ├── ik_solver.py           # positions -> local quaternions + root
│   ├── wotagei_optimizer.py   # smoothing + kime detection
│   └── format_exporter.py     # -> MotionData JSON
├── lib/
│   ├── blazepose_to_h36m.py   # canonical BlazePose(33) -> H36M(17)
│   ├── expand_joints.py       # H36M(17) -> SMPL_24(24)
│   └── motionbert_model.py    # vendored MotionBERT 'lite' lifter
├── tools/
│   ├── forward_kinematics.py  # reference FK (numpy)
│   └── selftest_pipeline.py   # IK round-trip accuracy test
├── scripts/download_models.py
└── models/                    # downloaded weights land here
```
