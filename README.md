# torch-monkey

> 🔥 Wota-艺（ヲタ芸）3D 编排与可视化软件 · A wotagei 3D choreography & visualization tool based on 3D reconstruction and rendering.

- 基于3D重建以及渲染，为解决想看到标准效果的编排而诞生的wota艺软件。
- Based on 3D reconstruction and rendering, the wotagei software was developed to address the issue of arranging content to achieve the desired standard effect.
- 3D再構築およびレンダリングを基に、標準的な効果を確認したい編成のため生まれたヲタ芸ソフトウェア。

## 快速开始 / Quick Start

桌面端：Electron + React 19 + Babylon.js 9；AI 动捕管线：Python + FastAPI + MediaPipe + MotionBERT。

```bash
# 1) 前端
npm install
npm run dev            # 开发模式（含自动拉起 Python 管线）

# 2) Python AI 管线（另开终端）
cd python
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt                   # GPU 用户先装 CUDA 版 torch，见下
python scripts/download_models.py                 # 下载 MediaPipe + MotionBERT 权重

# 3) 准确率自检（无需 GPU/模型，CPU 数秒完成）
python tools/selftest_pipeline.py
```

**GPU 用户**：先 `pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121`，再 `pip install -r requirements.txt`。

📘 **完整文档见 [USAGE.md](./USAGE.md)**（安装、运行、功能、AI 管线与准确率、快捷键、排错）。

## 功能 / 機能 / Features

- 🎬 自定义 3D 暗舞台（ステージ / stage）+ 聚光灯（スポットライト / spotlight）+ 轨道摄像机（カメラ / camera）
- 🧍 多角色程序化人形（SMPL-24 骨架 / スケルトン / skeleton）+ 自定义 `.glb` 重定向（リターゲット / retarget）
- 🎥 视频动捕（モーションキャプチャ / motion capture）：视频 → 2D → 3D → **位置转旋转 IK** → 打艺特化优化（卡点（キメ / kime）检测 / 零过渡刹车 / 受保护平滑）
- 🎚 多轨道时间线（タイムライン / timeline）+ 音频波形 + 节拍（ビート / beat）标记 + 拖拽编排
- ✨ 荧光棒（サイリウム / cyalume）光轨（トレイル / trail）+ 速度自适应残影 + Bloom 暗环境 + 卡点特效
- 💾 `.tmonkey` 工程持久化 + glTF / BVH 导出（エクスポート / export）

> 关键名词三语对照见 [USAGE.md 术语表](./USAGE.md#术语对照表--glossary)。

## 许可 / License

MIT。第三方组件（Babylon.js / Electron / React / MediaPipe / MotionBERT / FastAPI / scipy 等）均为 Apache-2.0 / MIT / BSD，可商用。
