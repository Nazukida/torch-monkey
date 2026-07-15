# torch-monkey

> 🔥 Wota-艺（ヲタ芸）3D 编排与可视化软件 · 把表演视频变成 3D 动作，在舞台上编排、预览。

基于 3D 重建与渲染，为"想看到标准效果"的 Wota-艺编排而生。AI 动作捕捉（重建）可以跑在有 GPU 的 Linux 服务器上加速，**查看/编排可以用 Windows 桌面 App，也可以直接用浏览器**。

📘 **完整文档见 [USAGE.md](./USAGE.md)**（两种查看端怎么选、Linux 服务器从零搭建、连接两台电脑、排错、原理）。

---

## 两种查看端，任选其一

| 方式 | 适合 | 一句话 |
|---|---|---|
| **桌面 App**（Electron + React + Babylon.js） | Windows，功能最全 | `npm install && npm run dev` |
| **浏览器**（同一个界面，开网页即看） | 远端 GPU 场景、不想在 Windows 装东西 | `npm run build:web` 后开 `http://<服务器>:19876/` |

> 两种查看端连的是**同一个 Python AI 服务器**（`python/server.py`，默认端口 19876）。AI 管线：Python + FastAPI + MediaPipe + MotionBERT。

---

## 快速开始

### A. 桌面 App（Windows）

```bash
npm install
npm run dev            # 开发模式（本地模式会自动拉起 Python 管线）
```

想连远端 GPU：启动后在顶栏 ⚙ 里切"远程·SSH 隧道"或"远程·局域网"。详见 [USAGE §3](./USAGE.md#3-把两台电脑连起来ssh-隧道--局域网--测试连接)。

### B. 浏览器（任意系统）

```bash
npm run build:web      # 构建网页端 → python/web_dist/
python python/server.py
# 浏览器打开 http://127.0.0.1:19876/
```

> ⚠️ 首次必须先跑 `npm run build:web`，否则打开页面只会看到一段说明性 JSON（网页还没构建）。

远端 GPU：服务器在 Linux，Windows 上 `ssh -L 19876:127.0.0.1:19876 user@server`，浏览器同样开 `http://127.0.0.1:19876/`。详见 [USAGE §4.2](./USAGE.md#42-浏览器开网页即看推荐远端场景)。

### Python AI 管线（服务器侧，两种查看端都需要）

```bash
bash scripts/setup.sh                # 一键：建 venv、探测 GPU 装 CUDA 版 torch、下模型、自检（Win: npm run setup）
python python/tools/check_env.py     # 体检（退出码=问题数）
python python/server.py              # 起 AI 服务（:19876）
```

**GPU 用户**：`setup.sh` 会自动探测 `nvidia-smi` 装 CUDA 版 torch；手动则先 `pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121`，再 `pip install -r python/requirements.txt`。

🖥️ **远程 GPU 重建**：重建（AI 算动作）在 Linux 服务器、查看/编排在 Windows —— 见 [USAGE §1–§3](./USAGE.md#1-两台电脑怎么分工心智模型)。

---

## 功能

- 🎬 自定义 3D 暗舞台 + 聚光灯 + 轨道摄像机
- 🧍 多角色程序化人形（SMPL-24 骨架）+ 自定义 `.glb` 重定向
- 🎥 视频动捕：视频 → 2D → 3D → **位置转旋转 IK** → 打艺特化优化（卡点检测 / 零过渡刹车 / 受保护平滑）
- 📺 **B 站动捕**：给一个 BV 号，自动下载并送入管线（[USAGE §5.7](./USAGE.md#57-b-站动捕bilibili-bv-号)）
- 🎚 多轨道时间线 + 音频波形 + 节拍标记 + 拖拽编排 + **🧲 磁吸** + 每角色独立轨道
- 🖱 **直接拖拽**表演者在 3D 视口里调整站位；无动作时缓慢复位到待机姿态
- ✨ 荧光棒光轨 + 速度自适应残影 + Bloom 暗环境 + 卡点特效
- ✨ 荧光棒光轨 + 速度自适应残影 + Bloom 暗环境 + 卡点特效
- 💾 `.tmonkey` 工程持久化 + glTF / BVH 导出

> 关键名词三语对照见 [USAGE 术语表](./USAGE.md#72-术语对照表)。

## 许可 / License

MIT。第三方组件（Babylon.js / Electron / React / MediaPipe / MotionBERT / FastAPI / scipy 等）均为 Apache-2.0 / MIT / BSD，可商用。
