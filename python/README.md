# Torch Monkey — Python AI 动捕管线 / AI Mocap Pipeline

Torch Monkey 的第 4 阶段。一个本地 FastAPI 服务，把 Wota-艺（ヲタ芸 / wotagei）表演视频转换成 Torch Monkey 的 `MotionData` JSON（SMPL_24 骨架），供**桌面 App** 或**浏览器端**收入动作库。

> 本文档面向在服务器上部署/二次开发的人。新手安装指引见仓库根 [USAGE.md §2](../USAGE.md#2-linux-服务器从零环境到起服务手把手)。

## 它承担什么

两件事：

1. **AI 管线**（核心）：视频 → 动作（见下）。
2. **持久化 + 网页托管**（供浏览器端）：动作库 / 工程 / 设置的增删改查，以及把浏览器构建产物托管在 `/`，让"开网页即看"成立。

## 管线流程 / Pipeline

```
video ─► VideoProcessor.extract_frames    抽帧（OpenCV + ffprobe 元信息）
      ─► MediaPipeEstimator.process_batch 2D 关键点（BlazePose 33 关键点）
      ─► MotionBERTEstimator.infer        3D 提升（MotionBERT → SMPL_24，米）
      ─► WotageiOptimizer.optimize        打艺优化（滤波 + 卡点检测）
      ─► FormatExporter.to_motion_data    导出（MotionData JSON，局部四元数）
```

## 环境要求 / Requirements

- Python 3.10+（推荐 3.11）
- `ffmpeg` / `ffprobe` 在 PATH（或用 `TORCHMONKEY_FFPROBE` / `TORCHMONKEY_FFMPEG` 指向完整路径）。
- （可选）`yt-dlp` —— 仅 B 站动捕需要，已在 `requirements.txt`。

## 安装 / Setup

```bash
cd python

# 一键（自动探测 GPU 装 CUDA 版 torch；CPU 开发机也适用）：
bash ../scripts/setup.sh          # 或在仓库根 npm run setup
# 环境方式可选 / env backend: --venv（默认）| --conda（装进当前 conda 环境）| --uv（用 uv，快）
# 例：bash ../scripts/setup.sh --conda --cuda 118

# 或手动：
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
# GPU 机器先装 CUDA 版 torch，再装其余依赖（否则 pip 会降级回 CPU 版）：
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

## 下载模型权重 / Model weights

```bash
python scripts/download_models.py
```

下载到 `python/models/`：`pose_landmarker_heavy.task`（MediaPipe，Apache-2.0）、`mb3d.pth`（MotionBERT，MIT）。脚本幂等，缺失时 3D 提升器回退为几何提升器，服务仍可启动。

## 运行 / Run

```bash
python server.py                        # 默认 127.0.0.1:19876（仅回环，配 SSH 隧道）
python server.py --port 19877           # 自定义端口
python server.py --host 0.0.0.0         # 绑所有网卡（局域网直连）
TORCHMONKEY_HOST=0.0.0.0 python server.py   # 等价：环境变量
```

### 浏览器端托管 / Web client hosting

`server.py` 启动时若发现 `python/web_dist/`（由仓库根 `npm run build:web` 生成）存在，会自动把它托管在 `/`（`StaticFiles`，`html=True`）。此时直接用浏览器开 `http://<服务器>:19876/` 就是完整界面（与桌面 App 同源，无 CORS）。

- 没构建网页端时，`/` 返回一个说明性 JSON（提示去跑 `npm run build:web`），API 照常可用。
- 改默认目录：`TORCHMONKEY_WEB_DIST=/path python server.py`。

### 终端可视化 / Terminal dashboard

```bash
python tools/dashboard.py                                # 默认连 http://127.0.0.1:19876（SSH 隧道打开后，本机这个地址就是远程 GPU）
python tools/dashboard.py --url http://<服务器IP>:19876   # 局域网直连时指向服务器 IP
```

实时显示模型就绪、device/CUDA/GPU 显存、每任务进度与阶段。依赖 `rich`（缺失自动降级纯文本）。**它是监控面板，不是查看器。**

### 环境自检 / Doctor

```bash
python tools/check_env.py     # 秒级体检，退出码=问题数
```

## 接口 / Endpoints

### 管线与状态

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 就绪状态（`models`）+ `runtime`（device/CUDA/GPU/显存/torch/ffmpeg）。恒 200 |
| GET | `/api/tasks` | 未过期任务列表（dashboard 用） |
| GET | `/api/progress/{task_id}` | 单任务进度 |
| POST | `/api/preview-video` | ffprobe 元信息（multipart `file`），不做推理 |
| POST | `/api/process-video` | 完整管线；返回 `motion_data` + `stats` |
| POST | `/api/preview-bilibili` | 按 BV 号探测元信息（JSON body，不下载），需 yt-dlp |
| POST | `/api/process-bilibili` | 按 BV 号下载 + 完整管线 |

`/api/process-video` 查询参数：`fps`（默认 30）、`smooth`、`detect_kime`，请求体 multipart `file`。
`/api/preview|process-bilibili` 请求体 JSON：`{bvid, page?, fps?, smooth?, detect_kime?}`，`bvid` 接受 `BV1xx`、完整 bilibili.com / b23.tv 链接或 10 位主体。

### 持久化（浏览器端用；camelCase，契约见 `shared/types/motion.ts`、`project.ts`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/motions` | 动作列表（`search/source/tags/sortBy/sortOrder/limit/offset`），返回 `{motions, total}` |
| GET | `/api/motions/{id}` | 单条完整动作（含 poses） |
| POST | `/api/motions` | 创建/替换动作（body = MotionData） |
| PATCH | `/api/motions/{id}` | 部分更新 |
| DELETE | `/api/motions/{id}` | 删除 |
| GET | `/api/tags?limit=` | 热门标签 |
| GET / POST | `/api/projects`, `GET /api/projects/{id}` | 工程库 |
| GET / PUT | `/api/settings/{key}` | 键值设置（值为 JSON 字符串） |
| GET | `/api/stats` | `{motionCount, projectCount, totalStorageBytes}` |

> 存储层 `api/store.py` 用 stdlib `sqlite3`，逐字复用仓库根 `database/schema.sql`（与桌面端 Electron 的库结构一致），库文件位于 `TORCHMONKEY_DATA_DIR`。

### B 站动捕（BV 号）

`lib/bilibili_downloader.py` 用 yt-dlp 按 BV 号下载**单个**用户指定视频到 `_work/`，再交给与 `/api/process-video` 完全相同的管线。

- `TORCHMONKEY_BILI_MAX_DURATION`：时长上限（秒，默认 900；`0` 关闭）。
- `TORCHMONKEY_BILI_COOKIES`：可选 Netscape cookies 文件（高画质/会员内容）。

> ⚖️ 仅下载你指定且有权使用的视频用于本地动作分析；不做批量抓取或再分发。

## 准确率自检（无需 GPU/权重）

```bash
python tools/selftest_pipeline.py
```

合成已知动作 → 位置转旋转 → 正运动学重建 → 比对误差；打印 PASS/FAIL 与逐关节统计。平均重建误差 < 2 mm。

## 环境变量 / Env

| 变量 | 作用 | 默认 |
|---|---|---|
| `TORCHMONKEY_HOST` | 绑定地址（`0.0.0.0` 对局域网开放） | `127.0.0.1` |
| `TORCHMONKEY_DATA_DIR` | 存储库目录（SQLite） | `python/data` |
| `TORCHMONKEY_WEB_DIST` | 浏览器构建产物目录（托管在 `/`） | `python/web_dist` |
| `TORCHMONKEY_FFPROBE` / `TORCHMONKEY_FFMPEG` | ffmpeg/ffprobe 可执行文件路径 | 从 PATH |
| `TORCHMONKEY_BILI_MAX_DURATION` / `TORCHMONKEY_BILI_COOKIES` | B 站时长上限 / cookies | `900` / 空 |

## 目录结构 / Layout

```
python/
├── server.py                  # FastAPI 应用：管线 + 存储路由 + 网页托管
├── requirements.txt
├── config/settings.py         # 路径、默认值、环境变量
├── api/store.py               # sqlite3 存储层（复用 ../database/schema.sql）
├── pipeline/                  # video_processor / pose_estimator_2d|3d / ik_solver / wotagei_optimizer / format_exporter
├── lib/                       # skeleton_def / forward_kinematics / motionbert_model / blazepose_to_h36m / expand_joints / bilibili_downloader
├── tools/                     # selftest_pipeline / check_env / dashboard / forward_kinematics
├── scripts/download_models.py
├── models/                    # 下载的权重
├── data/                      # 存储库 SQLite（TORCHMONKEY_DATA_DIR）
└── web_dist/                  # 浏览器构建产物（npm run build:web 生成）
```
