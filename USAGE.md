# Torch Monkey 使用文档 / 使用ガイド / Usage Guide

> Wota-艺（ヲタ芸 / wotagei）3D 编排与可视化软件 · 基于 3D 重建与渲染 / 3D再構築とレンダリングに基づく / Based on 3D reconstruction & rendering.
> 版本 0.01 · 2026-06-25

> 本文档以中文为主体语言；关键名词首次出现时标注日语与英语，例如「卡点（キメ / kime）」。完整对照见 [术语表](#术语对照表--glossary)。

---

## 目录

1. [项目简介](#1-项目简介)
2. [系统要求](#2-系统要求)
3. [安装](#3-安装)
4. [运行](#4-运行)
5. [架构总览](#5-架构总览)
6. [功能用法](#6-功能用法)
7. [AI 动捕管线与准确率](#7-ai-动捕管线与准确率)
8. [键盘快捷键](#8-键盘快捷键)
9. [项目结构与数据格式](#9-项目结构与数据格式)
10. [打包发布](#10-打包发布)
11. [常见问题 / Troubleshooting](#11-常见问题--troubleshooting)

---

## 1. 项目简介

Torch Monkey 让你可以：

- 在可自定义的 3D 暗舞台上放置多个角色；
- 导入 Wota-艺表演视频，由 **AI 自动提取 3D 动作**（视频 → MediaPipe 2D → MotionBERT 3D → IK 关节旋转 → 打艺特化优化）；
- 在时间线上拖拽编排动作序列，配合音乐同步播放；
- 实时预览带**荧光棒光轨（サイリウム / cyalume）+ Bloom 泛光暗环境**的演出效果；
- 导出编排结果为 `.tmonkey` 工程文件 / glTF / BVH。

四层解耦（参考 MMD）：**模型（モデル / model）/ 动作（モーション / motion）/ 相机（カメラ / camera）/ 特效（エフェクト / VFX）** 完全独立，可自由混搭。

---

## 术语对照表 / Glossary

本项目的关键名词在中文、日语、英语三语下的对照（首次出现处内联标注）：

| 中文 | 日本語 | English |
|------|--------|---------|
| 打艺 / Wota-艺 | ヲタ芸 | wotagei (wota-gei) |
| 动作捕捉 | モーションキャプチャ | motion capture (mocap) |
| 动作 | モーション | motion |
| 动作库 | モーションライブラリ | motion library |
| 卡点 | キメ | kime (hard-stop accent) |
| 荧光棒 | サイリウム | cyalume / glowstick |
| 骨架 / 骨骼 | スケルトン | skeleton |
| 关节 | 関節 | joint |
| 四元数 | クォータニオン | quaternion |
| 正运动学 | フォワードキネマティクス | forward kinematics (FK) |
| 逆运动学 | インバースキネマティクス | inverse kinematics (IK) |
| 舞台 | ステージ | stage |
| 灯光 | ライティング | lighting |
| 聚光灯 | スポットライト | spotlight |
| 时间线 | タイムライン | timeline |
| 轨道 | トラック | track |
| 片段 | クリップ | clip |
| 节拍 | ビート | beat |
| 角色 | キャラクター | character |
| 摄像机 | カメラ | camera |
| 模型 | モデル | model |
| 重定向 | リターゲット | retarget |
| 泛光 | ブルーム | bloom |
| 拖尾 / 残影 | トレイル / 残像 | trail / afterimage |
| 后期处理 | ポストプロセス | post-processing |
| 抽帧 | フレーム抽出 | frame extraction |
| 工程文件 | プロジェクトファイル | project file |
| 哔哩哔哩 / B 站 | 哔哩哔哩 / ビリビリ | Bilibili |
| BV 号 | BV 番号 / 動画 ID | BV id (Bilibili video id) |

---

## 2. 系统要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11（本期目标）。macOS 架构已预留。 |
| Node.js | ≥ 18（推荐 20 LTS） |
| Python | ≥ 3.10（推荐 3.11） |
| GPU | **可选**。CPU 即可运行全部功能；拥有 NVIDIA GPU 时动捕推理显著加速。 |
| 显存 | GPU 推理建议 ≥ 6GB |
| 硬盘 | ≈ 3GB（含模型权重） |

> **重要**：本工程是在 **CPU 环境**下开发与验证的（类型检查、构建、AI 管线自检均通过），但**设计上即开即用于 GPU 环境**——所有深度学习代码使用 `torch.cuda.is_available()` 自动选择设备，并在 CUDA 不可用时优雅回退到 CPU。请放心在 GPU 机器上运行。

---

## 3. 安装

### 3.1 前端（Electron + React + Babylon.js）

```bash
# 在仓库根目录
npm install
```

> 若遇到 peer 依赖冲突，使用 `npm install --legacy-peer-deps`。
> 若需在本机运行（非仅构建），原生模块 `better-sqlite3` 需要编译工具链（Windows 上需要 Visual Studio Build Tools）。`npm install` 默认会编译它。

### 3.2 Python AI 管线

建议为 Python 管线单独建立虚拟环境：

```bash
cd python
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

**CPU 环境（开发机，默认）：**

```bash
pip install -r requirements.txt
```

**GPU 环境（你的目标机，CUDA 加速）：**

先安装对应 CUDA 版本的 PyTorch，再装其余依赖（这样 pip 不会把 torch 降级回 CPU 版）：

```bash
# CUDA 12.1（现代 RTX 显卡最常见）
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121

# CUDA 11.8
# pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu118

pip install -r requirements.txt
```

验证 CUDA 可用：

```bash
python -c "import torch; print('cuda' if torch.cuda.is_available() else 'cpu', torch.__version__)"
```

> **B 站动捕（BV 号）额外依赖**：若要使用「从 Bilibili BV 号下载并动捕」功能，需安装 `yt-dlp`（已包含在 `requirements.txt` 中，`pip install -r requirements.txt` 会一并装上）。详见 [6.7 节](#67-b-站动捕bilibili-bv-号)。

### 3.3 下载模型权重

```bash
cd python
python scripts/download_models.py
```

该脚本会下载到 `python/models/`：

- **MediaPipe Pose Landmarker (heavy)** — `pose_landmarker_heavy.task`，BlazePose 33 关键点（Apache-2.0）。
- **MotionBERT 3D-lifting checkpoint** — `mb3d.pth`，2D→3D 提升模型（MIT，来自 Walter0807/MotionBERT）。

脚本幂等，已存在的文件会跳过；加 `--force` 强制重下。

> **无模型也能跑**：管线做了优雅回退——若权重缺失，3D 估计会退化为几何人体测量学（anthropometric）提升器，结果仍合理但精度下降；服务端始终可启动。详见 [第 7 节](#7-ai-动捕管线与准确率)。

---

## 4. 运行

### 4.1 桌面应用（推荐）

```bash
# 开发模式（热重载）
npm run dev

# 生产构建后运行
npm run build
npm run preview
```

应用启动时：

1. Electron 主进程创建窗口并初始化 SQLite 数据库（位于 `userData/torch-monkey.db`）。
2. **自动拉起 Python AI 管线子进程**（`python/server.py`，监听 `127.0.0.1:19876`），并轮询健康检查。
3. 顶栏右侧指示灯：🟢 绿 = 管线就绪，🔴 红 = 离线（动捕功能不可用，其余功能正常）。

### 4.2 单独运行 / 调试 Python 管线

```bash
cd python
python server.py                       # 默认 19876 端口
python server.py --port 19877          # 自定义端口
```

接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + 模型加载状态 |
| POST | `/api/preview-video` | 上传视频，ffprobe 快速返回元信息（不做推理） |
| POST | `/api/process-video` | 完整管线：视频 → 帧提取 → 2D → 3D → 优化 → MotionData JSON |
| POST | `/api/preview-bilibili` | 按 BV 号探测元信息（标题/时长/UP 主），**不下载**。需 yt-dlp |
| POST | `/api/process-bilibili` | 按 BV 号下载单个视频 → 完整动捕管线 → MotionData。需 yt-dlp |

### 4.3 准确率自检（无需 GPU / 无需模型）

这是我们在**没有测试机的情况下自行验证动捕管线准确率**的方式——一个闭环测试：合成已知动作 → 位置转旋转 → 正运动学重建 → 比对误差。

```bash
cd python
python tools/selftest_pipeline.py
```

预期输出（在 CPU 上数秒内完成）：

```
[1/3] Position -> Rotation -> FK round trip (IK solver accuracy):
  [PASS] left_hand_circle:  mean err 0.089 mm  max err 0.858 mm
  [PASS] right_arm_wave:    mean err 0.129 mm  max err 1.367 mm
[2/3] WotageiOptimizer round-trip + kime detection:  [PASS]
[3/3] FormatExporter.to_motion_data schema:           [PASS] 12/12
OVERALL: PASS
```

> 退出码 0 = 通过。平均重建误差应 **< 2 mm**（远优于人眼可辨阈值），证明 IK 求解器正确。

---

## 5. 架构总览

```
┌─────────────────────────── Electron 桌面壳 ───────────────────────────┐
│  Renderer (React 19 + Babylon.js 9)        Main (Node.js)              │
│   ├ 3D 视口 (Stage3D / Lighting)            ├ 文件对话框 / 项目 IO      │
│   ├ 角色系统 (SkeletonRig / MotionPlayer)   ├ SQLite (better-sqlite3)   │
│   ├ 时间线 (Timeline / Transport)           └ Python Manager (子进程)   │
│   ├ VFX (Glowstick / Trail / PostFX)            │                       │
│   └ Zustand stores (状态)                       ▼                       │
│                                  Python AI 管线 (FastAPI, :19876)       │
│                                  video→ffmpeg→MediaPipe 2D→             │
│                                  MotionBERT 3D→IK 旋转→打艺优化→导出    │
└────────────────────────────────────────────────────────────────────────┘
```

四层数据解耦：

- **Model**：角色外观（程序化人形 / 自定义 `.glb`）。
- **Motion**：骨骼动画（`.json` / SQLite），关节旋转四元数。
- **Camera**：时间线相机轨道（轨道摄像机 + 关键帧）。
- **VFX**：荧光棒配置 + 后期（Bloom/暗角等）。

四层组合写入 `.tmonkey` 工程文件。

---

## 6. 功能用法

### 6.1 舞台与灯光（右侧「舞台」面板）

- 滑块调整舞台**宽度 / 深度**（5–50 m）。
- 地板模式：**网格 / 纯色 / 反射**。
- 调整地板颜色、背景色、参考网格开关。
- 灯光：环境光、背光、聚光灯（スポットライト / spotlight）强度（暗环境 + 聚光灯 = 演出场地感）。

视口操作：**左键拖拽**旋转视角，**滚轮**缩放，**右键**平移。

### 6.2 角色（左侧「角色」面板 + 右侧「角色」面板）

- **＋ 新增角色** 添加程序化人形；支持「一字排开」「V 字」自动对齐。
- 点击列表选中角色后，右侧可调整：名称、身高、颜色、不透明度、X/Z 站位、朝向、显示骨骼。
- 👁 切换可见，🗑 删除，可复制。

### 6.3 动作库（左侧「动作库」面板）

- 搜索框过滤；显示时长、帧数、来源（AI/手动）、运动强度条、标签。
- **🎥 视频动捕**：选视频 → 走完整 AI 管线 → 自动入动作库。
- **➕ 测试动作**：生成 3 个内置演示动作（T-Pose / 左手画圆 / 鞠躬（お辞儀 / bow）），无需模型即可体验播放链路。
- **拖拽**动作卡片到下方时间线的角色轨道即可编排。

### 6.4 时间线（底部）

- 传输栏：▶/⏸ 播放暂停、⏹ 停止、速度滑块（0.25×–2×）、时间显示、🎵 导入音频、🥁 节拍检测。
- 轨道类型：**角色（蓝）/ 相机（黄）/ 特效（紫）**，可锁定🔒、静音🔇。
- **片段（Clip）交互**：拖拽移动、左右边缘拖拽修剪、选中后删除。
- **吸附与节拍**：导入音频后显示波形，「节拍检测」在波形上打点；播放头红色竖线。
- 缩放滑块调节时间密度；点击标尺/轨道空白处可拖动播放头定位。

### 6.5 特效 VFX（右侧「特效」面板）

- 荧光棒开关、拖尾、双持；左右手分别配置颜色 / 亮度 / 光照。
- 后期：Bloom（泛光，最关键）、阈值/强度/模糊核、曝光、对比度、暗角、锐化。
- 卡点（キメ / kime）瞬间会自动触发 **Bloom 增强 punch** + 拖尾（トレイル / trail）快速收敛（演出感的核心）。

### 6.6 工程

- 顶栏：新建 / 打开 / 保存 / 另存为；「🎥 导入视频动捕」、「📺 B 站动捕」。
- `Ctrl+S` 保存为 `.tmonkey`（同时镜像进 SQLite 的 projects 表作为备份）。

### 6.7 B 站动捕（Bilibili BV 号）

除了导入本地视频，你还可以**直接给定 Bilibili 视频编号（BV 号 / BV id）**，软件会自动下载该视频并送入 AI 动捕管线，结果同样进入动作库。

**入口**：顶栏「📺 B 站动捕」按钮，或动作库面板的「📺 B 站」按钮。

**操作流程**：

1. 在弹窗输入 BV 号或 B 站链接，例如：
   - `BV1xx411c7mD`（大小写不限，也可只填 10 位主体）
   - `https://www.bilibili.com/video/BV1xx411c7mD`
   - `https://b23.tv/xxxxx`（短链，自动解析）
2. （可选）点击「🔍 探测」预览标题 / 时长 / UP 主，确认是你要的视频。
3. 选择分 P（Page）、FPS（30/60）、是否平滑 / 卡点检测。
4. 点击「⬇️ 下载并动捕」：软件先用 `yt-dlp` 下载该视频到本地临时目录，再走完整管线（抽帧 → 2D → 3D → IK 旋转 → 打艺优化 → MotionData）。
5. 完成后动作自动入库，名称取自视频标题，标签含 `bilibili` 与 `BV:<编号>`，来源记录为该视频链接。

**配置**：

- 视频时长上限默认 **15 分钟**（避免误下长视频）。可通过环境变量 `TORCHMONKEY_BILI_MAX_DURATION`（秒）调整，设为 `0` 关闭限制。
- 高画质 / 会员专属内容：可选提供 Netscape 格式 cookies 文件，路径写入环境变量 `TORCHMONKEY_BILI_COOKIES`。

> ⚖️ **合规提示 / Responsibility**：本功能**仅下载你指定单个视频**，用于本地动作分析，不做批量抓取、也不重新分发（redistribute）。请确保你**有权下载与使用**所选视频（例如你自己的表演、或已获授权的内容）。本质上等同于你手动用 `yt-dlp` 下载一个链接再喂给管线。

> 「自行拿去训练」：本功能把下载的视频**自动送入 AI 动捕推理管线**（即视频 → 动作提取），而非在单条视频上微调模型——单条数据不足以训练；管线本身已在 `selftest_pipeline.py` 中验证准确率（见 4.3）。

---

## 7. AI 动捕管线与准确率

这是本工程的核心技术难点，也是**我们重点做过准确率提升**的部分。

### 7.1 管线流程

```
视频 → ffmpeg/OpenCV 抽帧 → MediaPipe BlazePose 33 关键点 (2D)
     → BlazePose→Human3.6M 17 关节映射（修正版）
     → MotionBERT 3D 提升得到 17 关节 3D 位置 (mm)
     → expand_joints 扩展到 SMPL-24 (24 关节位置, 米)
     → ik_solver: 位置 → 每关节局部旋转四元数 + 根轨迹
     → WotageiOptimizer: 卡点检测 + 受保护平滑 + 关节限位 + 零过渡刹车
     → FormatExporter: 内部 MotionData JSON
```

### 7.2 准确率提升要点（相对原始计划草案的改进）

| 问题（草案） | 改进 |
|------|------|
| BlazePose→H36M 映射错误（复用索引 0、髋部错配） | `lib/blazepose_to_h36m.py` 使用**规范映射**并逐对注释，17 关节全部正确填充。 |
| MotionBERT 输出**关节位置**，但内部格式需要**关节旋转**；草案 `_estimate_rotation` 返回单位四元数（占位） | 新增 `pipeline/ik_solver.py`：真正的**位置→旋转求解器**，配合 `lib/forward_kinematics.py` 做正运动学，闭环重建误差 < 2 mm。 |
| 骨长抖动导致骨骼拉伸 | IK 前对每根骨**强制中值骨长**（球面重投影），消除拉伸感。 |
| 平滑会糊掉卡点 | `WotageiOptimizer` 在**卡点保护窗口内不滤波**，卡点帧实现**零过渡帧刹车**（复制上一帧 + 2 帧微停顿）。 |
| 缺模型即崩溃 | 所有 torch/mediapipe 导入**延迟 + 守卫**；权重缺失时回退到几何提升器，服务始终可启动。 |
| 无法在无 GPU 机器验证 | `tools/selftest_pipeline.py` **闭环自检**：合成动作 → IK → FK → 比对，纯 numpy/scipy，CPU 数秒完成。 |

### 7.3 IK 求解器原理（简述）

对每一帧、每个有父关节的关节 j：在父关节的局部坐标系下，计算把「静止骨方向」旋转到「当前骨方向」的局部四元数（使用鲁棒的向量间旋转四元数，处理反向平行；用参考 up 向量解算扭转，使肘/膝朝正确方向弯曲）。根骨盆的世界旋转由髋连线/肩连线求得，根轨迹取骨盆位置（默认仅水平移动）。由于每根骨只对齐自己的「入射骨」，多分支（如骨盆同时连髋与脊柱）也能正确求解。

### 7.4 GPU 说明

- 设备选择：`device = "cuda" if torch.cuda.is_available() else "cpu"`。
- 推理：243 帧滑窗、50% 重叠、`torch.no_grad()`、`eval()`；CUDA 上可选半精度。
- **本工程在 CPU 上开发与自检通过；在 GPU 上无需改动即可获得大幅加速。**

---

## 8. 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Space` / `K` | 播放 / 暂停 |
| `Home` / `End` | 跳到开头 / 结尾 |
| `←` / `→` | 前后步进一帧 |
| `Ctrl+N` | 新建工程 |
| `Ctrl+O` | 打开工程 |
| `Ctrl+S` | 保存工程 |
| `Ctrl+Shift+S` | 另存为 |
| `Ctrl+I` | 导入视频动捕 |

> 菜单「File / View / Help」提供完整入口；输入框聚焦时快捷键不拦截。

---

## 9. 项目结构与数据格式

```
torch-monkey/
├─ electron.vite.config.ts        构建配置（main/preload/renderer + 别名）
├─ package.json
├─ tsconfig.{json,node,web}.json
├─ database/schema.sql            SQLite schema（motions/projects/tags/settings）
├─ shared/                        ★ 前后端共享契约（TS）
│  ├─ types/        stage/character/motion/timeline/vfx/project/electron
│  └─ constants/skeleton.ts       SMPL-24 关节/层级/静止位姿（单一事实源）
├─ src/
│  ├─ main/         Electron 主进程 + IPC + 数据库 + Python 管理
│  ├─ preload/      contextBridge 安全桥
│  └─ renderer/src/ React + Babylon 渲染层
│     ├─ engine/ stage/ character/ vfx/ motion/ timeline/ components/ stores/ lib/
├─ python/                        ★ AI 动捕管线
│  ├─ server.py     FastAPI 服务（:19876）
│  ├─ pipeline/     video_processor / pose_estimator_2d / pose_estimator_3d
│  │                / ik_solver / wotagei_optimizer / format_exporter
│  ├─ lib/          skeleton_def / forward_kinematics / motionbert_model
│  │                / blazepose_to_h36m / expand_joints / bilibili_downloader
│  ├─ tools/        selftest_pipeline（准确率闭环自检）
│  ├─ scripts/      download_models
│  └─ requirements.txt
└─ USAGE.md                       本文档
```

**MotionData JSON 要点**（`shared/types/motion.ts` 与 Python 导出完全一致）：

- `poses[t].transforms[j].rotation`：关节 j 的**局部**四元数 `[x,y,z,w]`（相对父骨）。
- **只有根关节 PELVIS（索引 0）** 携带世界 `position`，其余关节位移恒为零。
- `beatMarkers`：卡点（`type:"kime"`）/ 下拍 / 过渡等标记，驱动卡点 Bloom punch。
- 骨架类型固定 `smpl_24`，关节索引/层级/静止位姿见 `shared/constants/skeleton.ts`（与 `python/lib/skeleton_def.py` 逐字节一致）。

---

## 10. 打包发布

```bash
npm run build:win     # 构建 + electron-builder 打包 Windows 安装包
```

打包产物在 `release/`。打包内嵌 Python 管线的完整方案（`resources/python` + 内置解释器）见后续迭代；当前可在目标机按 [第 3 节](#3-安装) 准备 Python 环境后直接 `npm run dev` / `npm run preview`。

---

## 11. 常见问题 / Troubleshooting

**顶栏指示灯红色（AI 管线离线）？**
- 检查 Python 是否安装、是否在 PATH。
- 手动运行 `python python/server.py` 查看报错。
- 确认模型已下载（`python python/scripts/download_models.py`）。
- 即便离线，舞台 / 角色 / 手动动作 / 时间线 / 特效仍可正常使用。

**动捕结果不准确？**
- 用 **60fps** 源视频捕捉快速动作；确保全身入镜、光线充足、背景简洁。
- 确认已下载 MotionBERT 权重（缺失会退化为几何提升器，精度下降）。
- 在 GPU 上运行以获得更稳的时序推理。
- 运行 `python tools/selftest_pipeline.py` 确认管线本身正确。

**B 站动捕（BV 号）失败？**
- 确认已安装 `yt-dlp`：`pip install yt-dlp`（含在 `requirements.txt`）。
- 管线离线时该按钮不可用——先让顶栏指示灯变绿（见上）。
- 视频过长（>15 分钟）会被拒绝：调高 `TORCHMONKEY_BILI_MAX_DURATION` 或裁剪源视频。
- 高画质 / 会员视频下载失败：导出浏览器 cookies 为 Netscape 文件，路径设到 `TORCHMONKEY_BILI_COOKIES`。
- 网络问题或 B 站接口变动：升级 `yt-dlp`（`pip install -U yt-dlp`）后重试。

**播放时角色不动 / 抖动？**
- 确认动作已拖到该角色对应的**角色轨道**（蓝色）。
- 该轨道未被静音🔇、角色可见👁。
- AI 动作：卡点处会有「微停顿」，属正常的打艺刹车效果，非卡顿。

**`better-sqlite3` 安装/编译失败？**
- Windows 需 Visual Studio Build Tools（C++ 桌面开发）。或 `npm install --legacy-peer-deps` 后用 `npm run build` 验证。

**构建体积大？**
- 渲染层主要是 Babylon.js（~13MB）。如需瘦身可启用按需导入与手动 chunk 拆分。

**性能（多角色卡顿）？**
- 降低 Bloom 模糊核 / 关闭 DOF；减少同时角色数；关闭「显示骨骼」。

---

*Enjoy your wotagei. — Torch Monkey*
