# Torch Monkey — Python AI 动捕管线 / AI Mocap Pipeline

Torch Monkey 第 4 阶段（Stage 4）。一个本地 FastAPI 服务，把 Wota-艺（ヲタ芸 / wotagei）表演视频转换成 Torch Monkey 的 `MotionData` JSON（SMPL_24 骨架 / skeleton），由 Electron 应用直接收入动作库（モーションライブラリ / motion library）。

> 本文档以中文为主，关键名词附日语与英语标注。

## 管线流程 / Pipeline

```
video ─► VideoProcessor.extract_frames    抽帧（OpenCV + ffprobe 元信息）
      ─► MediaPipeEstimator.process_batch 2D 关键点检测（BlazePose 33 关键点）
      ─► MotionBERTEstimator.infer        3D 提升（MotionBERT → SMPL_24，单位米）
      ─► WotageiOptimizer.optimize        打艺优化（中值/巴特沃斯滤波 + 卡点检测）
      ─► FormatExporter.to_motion_data    导出（MotionData JSON，局部四元数）
```

> 关键名词：动作捕捉（モーションキャプチャ / motion capture, mocap）；卡点（キメ / kime）；四元数（クォータニオン / quaternion）；正运动学（フォワードキネマティクス / forward kinematics, FK）；逆运动学（インバースキネマティクス / inverse kinematics, IK）。

## 环境要求 / Requirements

- Python 3.10+（推荐 3.11）
- `ffmpeg` / `ffprobe` 在 `PATH` 中（`VideoProcessor` 用它读元信息）。Windows ���请把 `ffmpeg\bin` 加入 PATH，或设置环境变量 `TORCHMONKEY_FFPROBE` / `TORCHMONKEY_FFMPEG` 指向完整可执行文件路径。

## 安装 / Setup

```bash
cd python

# 1. CPU 环境（开发机）：直接安装依赖
pip install -r requirements.txt

# 2. GPU 环境（目标机）：先装 CUDA 版 torch，再装其余依赖
#    CUDA 12.1（现代 RTX 显卡最常见）：
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
#    CUDA 11.8：
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu118
pip install -r requirements.txt   # pip 会保留你刚装的 CUDA 版 torch
```

> `requirements.txt` 默认锁的是 CPU 版 torch wheel。GPU 机器上请**先**按上面的 CUDA index 装 torch，**再** `pip install -r requirements.txt`，否则 pip 会把 torch 降级回 CPU 版。

## 下载模型权重 / Download model weights

```bash
python scripts/download_models.py
```

下载到 `python/models/`：

| 文件 | 来源 |
|------|------|
| `pose_landmarker_heavy.task` | Google MediaPipe 存储（Apache-2.0） |
| `mb3d.pth` | Hugging Face 上的 `Walter0807/MotionBERT`（MIT） |

脚本幂等（已存在的文件会跳过）；若某个 URL 不可达会打印清晰的手动下载指引。即便权重缺失，服务端也能启动——`/api/health` 会报告各子系统就绪状态，3D 提升器（3D lifter）会回退到几何人体测量学（anthropometric）提升器，管线仍能产出合理结果。

## 运行 / Run

```bash
python server.py                 # 默认 127.0.0.1:19876
python server.py --port 19877    # 自定义端口
```

## 接口 / Endpoints

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/health`             | 管线就绪状态（哪些模型已加载）。恒返回 200。 |
| POST | `/api/preview-video`      | 仅返回 ffprobe 元信息（multipart `file`）。不做 AI 推理。 |
| POST | `/api/process-video`      | 完整管线。返回 `motion_data` + `stats`。 |
| GET  | `/api/progress/{task_id}` | 单任务进度（status/progress/stage/message）。 |

`/api/process-video` 查询参数：`fps`（默认 30）、`smooth`（布尔）、`detect_kime`（布尔）。请求体为 multipart `file` 上传。

CORS 允许 `http(s)://localhost:*`、`127.0.0.1:*` 以及 Electron 的 `app://.` 协议。

## 准确率自检（无需 GPU / 无需权重）/ Accuracy self-test

IK 求解器（位置→旋转）由一个闭环测试验证，只需 numpy：

```bash
python tools/selftest_pipeline.py
```

它会合成已知动作（一只手画水平圆、一次挥手），把关节位置 → 每关节局部四元数 → 正运动学（FK）重建，并断言重建位置与输入的误差在容差内；打印清晰的 PASS/FAIL 与逐关节误差统计。参考 FK 实现见 [`tools/forward_kinematics.py`](tools/forward_kinematics.py)。

## 目录结构 / Layout

```
python/
├── server.py                  # FastAPI 应用（本文档主题）
├── requirements.txt
├── config/settings.py         # 路径、默认值、模型文件名
├── pipeline/
│   ├── video_processor.py     # ffprobe + OpenCV 抽帧
│   ├── pose_estimator_2d.py   # MediaPipe BlazePose（33 关键点）
│   ├── pose_estimator_3d.py   # MotionBERT → SMPL_24（24 关节）
│   ├── ik_solver.py           # 位置 → 局部四元数 + 根轨迹
│   ├── wotagei_optimizer.py   # 平滑 + 卡点检测
│   └── format_exporter.py     # → MotionData JSON
├── lib/
│   ├── blazepose_to_h36m.py   # 规范映射 BlazePose(33) → H36M(17)
│   ├── expand_joints.py       # H36M(17) → SMPL_24(24)
│   └── motionbert_model.py    # 内置（vendored）MotionBERT 'lite' 提升器
├── tools/
│   ├── forward_kinematics.py  # 参考 FK（numpy）
│   └── selftest_pipeline.py   # IK 闭环准确率测试
├── scripts/download_models.py
└── models/                    # 下载的权重落在此处
```
