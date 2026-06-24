# Wota 艺 3D 编排软件 — "Torch Monkey" 技术方案

> 版本: 1.0 | 日期: 2026-06-24 | 作者: AI 辅助规划

---

## 目录

1. [项目概述](#1-项目概述)
2. [总体架构](#2-总体架构)
3. [阶段 1: 基础框架搭建](#3-阶段-1-基础框架搭建)
4. [阶段 2: 角色系统](#4-阶段-2-角色系统)
5. [阶段 3: 动作数据系统](#5-阶段-3-动作数据系统)
6. [阶段 4: AI 视频动捕管线](#6-阶段-4-ai-视频动捕管线)
7. [阶段 5: 时间线编排器](#7-阶段-5-时间线编排器)
8. [阶段 6: VFX 荧光棒特效](#8-阶段-6-vfx-荧光棒特效)
9. [阶段 7: 打磨与导出](#9-阶段-7-打磨与导出)
10. [附录](#10-附录)

---

## 1. 项目概述

### 1.1 项目定位

Torch Monkey 是一款面向 Wota 艺（ヲタ芸）爱好者的 **3D 编排与可视化工具**。用户可以：

- 在可自定义的 3D 舞台上放置多个角色
- 导入 Wota 艺表演视频，**AI 自动提取 3D 动作**
- 在时间线上拖拽编排动作序列，配合音乐同步
- 实时预览带荧光棒光轨特效的暗环境渲染
- 导出编排结果为视频或标准动作文件

### 1.2 设计原则

1. **四层解耦**: 模型 / 动作 / 相机 / 特效完全独立，可自由混搭
2. **离线优先**: 所有数据本地存储，无需网络
3. **渐进式精度**: AI 动捕先快速预览后高精度离线重建
4. **Wota 艺原生**: 卡点检测、关节锁死、节拍标记等特化功能内置

### 1.3 目标平台

| 阶段 | 平台 |
|------|------|
| 第一期 (本项目) | Windows 10/11 桌面 |
| 第二期 (预留架构) | macOS 桌面 |
| 第三期 (预留架构) | Android (通过 React Native / PWA) |

---

## 2. 总体架构

### 2.1 架构全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                     Electron 桌面壳                               │
│                                                                   │
│  ┌─────────────────────────────┐  ┌────────────────────────────┐ │
│  │   Renderer Process          │  │   Main Process (Node.js)   │ │
│  │   (React 19 + Babylon.js)   │  │                            │ │
│  │                             │  │  ┌──────────────────────┐  │ │
│  │  ┌───────────────────────┐  │  │  │ File System Handler  │  │ │
│  │  │ 3D Viewport           │  │  │  │ - 文件打开/保存对话框 │  │ │
│  │  │ - Stage3D             │  │  │  │ - 项目 JSON 序列化   │  │ │
│  │  │ - CharacterModel      │  │  │  │ - 视频/音频文件导入  │  │ │
│  │  │ - GlowstickVFX        │  │  │  └──────────────────────┘  │ │
│  │  │ - PostProcessing      │  │  │                            │ │
│  │  └───────────────────────┘  │  │  ┌──────────────────────┐  │ │
│  │                             │  │  │ Database Handler     │  │ │
│  │  ┌───────────────────────┐  │  │  │ - better-sqlite3     │  │ │
│  │  │ Timeline Editor       │  │  │  │ - CRUD 封装           │  │ │
│  │  │ - TrackList           │  │  │  │ - 迁移管理            │  │ │
│  │  │ - ClipItem (draggable) │  │  │  └──────────────────────┘  │ │
│  │  │ - WaveformView        │  │  │                            │ │
│  │  │ - BeatMarker          │  │  │  ┌──────────────────────┐  │ │
│  │  └───────────────────────┘  │  │  │ Python Manager       │  │ │
│  │                             │  │  │ - child_process.spawn │  │ │
│  │  ┌───────────────────────┐  │  │  │ - 健康检查/自动重启   │  │ │
│  │  │ Motion Library        │  │  │  │ - 进度 IPC 转发      │  │ │
│  │  │ - 列表/标签/搜索       │  │  │  └──────────────────────┘  │ │
│  │  │ - 预览缩略图           │  │  │                            │ │
│  │  └───────────────────────┘  │  │  ┌──────────────────────┐  │ │
│  │                             │  │  │ Project Handler      │  │ │
│  │  ┌───────────────────────┐  │  │  │ - 项目创建/加载/保存  │  │ │
│  │  │ Property Panel        │  │  │  │ - 最近项目列表        │  │ │
│  │  │ - 舞台/角色/特效属性   │  │  │  └──────────────────────┘  │ │
│  │  └───────────────────────┘  │  │                            │ │
│  │                             │  │                            │ │
│  │  Zustand Stores            │  │         IPC Bridge          │ │
│  │  - projectStore            │  │  contextBridge.exposeInMainWorld │
│  │  - stageStore              │  │                            │ │
│  │  - characterStore          │  └────────────────────────────┘ │
│  │  - timelineStore           │              │                  │
│  │  - motionStore             │              │ child_process    │
│  │  - playbackStore           │              │                  │
│  └─────────────────────────────┘              │                  │
│                                               ▼                  │
│                        ┌──────────────────────────────────────┐ │
│                        │     Python AI 管线 (FastAPI)          │ │
│                        │  Port: 19876 (localhost only)         │ │
│                        │                                       │ │
│                        │  POST /api/process-video             │ │
│                        │  WS   /ws/progress/{task_id}          │ │
│                        │  GET  /api/health                     │ │
│                        │                                       │ │
│                        │  Pipeline:                            │ │
│                        │  video → ffmpeg → MediaPipe 2D       │ │
│                        │       → MotionBERT 3D                │ │
│                        │       → WotageiOptimizer             │ │
│                        │       → FormatExporter               │ │
│                        └──────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 数据解耦架构 (参考 MMD)

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Model      │   │   Motion     │   │   Camera     │   │    VFX       │
│   (.glb)     │   │   (.json)    │   │   (内嵌)      │   │   (配置)      │
├──────────────┤   ├──────────────┤   ├──────────────┤   ├──────────────┤
│ • Mesh 几何  │   │ • 骨骼动画    │   │ • 运镜轨道    │   │ • 荧光棒配置  │
│ • 骨骼层级   │   │ • 关键帧      │   │ • FOV/焦点   │   │ • 拖尾参数    │
│ • 材质/PBR   │   │ • 节拍标记    │   │ • 震动/缓动  │   │ • Bloom 参数  │
│ • 可替换     │   │ • 可复用      │   │ • 可复用      │   │ • 可复用      │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
        │                  │                  │                  │
        └──────────────────┴──────────────────┴──────────────────┘
                                    │
                          ┌─────────────────┐
                          │   Project File  │
                          │   (.tmonkey)    │
                          │   组合以上四层   │
                          └─────────────────┘
```

### 2.3 关键数据流

#### 流 A: 视频 → 动作 (AI 动捕)

```
用户拖入 .mp4 文件
       │
       ▼
[Main] 文件路径 → IPC → Python Manager → spawn Python
       │
       ▼
[Python /api/process-video] 
       │
       ├─→ Step 1: ffmpeg 提取视频帧 (可配置 FPS: 30/60)
       │       输出: List[np.ndarray] shape=(H, W, 3), count=T
       │
       ├─→ Step 2: MediaPipe Pose 2D 关键点提取
       │       输入: 单帧 RGB
       │       输出: (33, 3)  [x, y, visibility] 归一化坐标
       │       聚合: (T, 33, 3) numpy array
       │
       ├─→ Step 3: MotionBERT 3D 姿态估计
       │       输入: (T, 33, 3) 2D 关键点序列
       │       输出: (T, 33, 3) 3D 世界坐标 (mm)
       │       模型: motionbert_lite (Apache 2.0)
       │
       ├─→ Step 4: WotageiOptimizer 特化优化
       │       子步骤:
       │       4a. Butterworth 低通滤波 (4阶, 截止 3Hz, fs=30)
       │       4b. 卡点检测: 计算手部加速度 → 突变帧标记 kime
       │       4c. 关节锁死保护: kime 帧前后 ±2 帧不做平滑
       │       4d. 速度曲线调整: kime 帧应用 Linear tangent
       │
       ├─→ Step 5: FormatExporter 格式转换
       │       输出: 内部 MotionData JSON
       │
       └─→ WebSocket 实时推送进度百分比
               │
               ▼
[Main] IPC → [Renderer] motionStore.addMotion(json)
       │
       ▼
[Renderer] 动作库面板刷新，新动作可见
```

#### 流 B: 编排播放

```
用户操作: 拖 MotionClip 到角色轨道 → 点击播放
       │
       ▼
[timelineStore] 记录: {
    trackId: "character-1",
    clips: [{ motionId, startTime, endTime, loop }]
}
       │
       ▼
[playbackStore] 状态 → "playing", 开始 requestAnimationFrame 计时
       │
       ▼
每帧 (60fps):
  ├─→ 查询当前时间 t 所在的 clip
  ├─→ 计算帧偏移: frameIndex = (t - clip.startTime) * motion.fps
  ├─→ MotionPlayer.getPoseAt(motionId, frameIndex)
  │     ├─→ 查找前后关键帧
  │     ├─→ 四元数球面线性插值 (slerp)
  │     └─→ 返回 { boneName: { rotation: Quat, position: Vec3 } }
  │
  ├─→ 应用骨骼变换到 SkeletonRig (Babylon.js Bone.setRotation/setPosition)
  │
  ├─→ GlowstickVFX.update()
  │     ├─→ 读取手掌骨骼世界坐标
  │     ├─→ 更新 TrailRenderer 顶点缓冲 (追加当前点, 淘汰过期点)
  │     └─→ 更新粒子发射器位置
  │
  └─→ Babylon.js scene.render() (PBR + Bloom + 粒子)
```

---

## 3. 阶段 1: 基础框架搭建

> **目标**: Electron + React + Babylon.js 可运行，看到 3D 暗舞台，摄像机可控
> **工期**: 2 周
> **依赖**: 无

### 3.1 步骤 1.1: 项目脚手架初始化

**操作:**
1. 使用 `npm create electron-vite@latest torch-monkey -- --template react-ts` 创建项目
2. 安装核心依赖

**依赖清单:**
```json
{
  "dependencies": {
    "@babylonjs/core": "^9.0.0",
    "@babylonjs/materials": "^9.0.0",
    "@babylonjs/post-processes": "^9.0.0",
    "@babylonjs/loaders": "^9.0.0",
    "@babylonjs/gui": "^9.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "zustand": "^5.0.0",
    "better-sqlite3": "^11.0.0",
    "uuid": "^10.0.0"
  },
  "devDependencies": {
    "@types/better-sqlite3": "^7.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@types/uuid": "^10.0.0",
    "electron": "^33.0.0",
    "electron-builder": "^25.0.0",
    "electron-vite": "^2.0.0",
    "typescript": "^5.6.0",
    "tailwindcss": "^4.0.0",
    "vite": "^6.0.0"
  }
}
```

**项目配置文件:**

`electron-vite.config.ts` (关键配置):
```typescript
// 关键点:
// - renderer 使用 React plugin
// - main 和 preload 使用 externalizeDepsPlugin
// - 共享类型通过 tsconfig paths 引用
```

**目录结构 (阶段 1 产出):**
```
torch-monkey/
├── electron/
│   ├── main.ts          ← 窗口创建、菜单
│   └── preload.ts       ← contextBridge 暴露 API
├── src/
│   ├── main.tsx          ← React 入口
│   ├── App.tsx           ← 主布局 (Viewport + Panel)
│   ├── engine/
│   │   └── BabylonEngine.ts  ← 引擎单例
│   ├── stage/
│   │   ├── Stage3D.ts        ← 场景搭建
│   │   └── Lighting.ts       ← 暗环境光照
│   ├── components/
│   │   ├── ViewportContainer.tsx  ← 3D Canvas 容器
│   │   └── StageConfigPanel.tsx   ← 舞台配置面板
│   └── stores/
│       └── stageStore.ts     ← 舞台状态
├── shared/
│   └── types/
│       └── stage.ts          ← StageConfig 类型
├── package.json
└── tsconfig.json
```

### 3.2 步骤 1.2: Electron 主进程 — 窗口管理

**文件: `electron/main.ts`**

核心逻辑:
1. 创建 BrowserWindow，尺寸 1600×900，最小 1280×720
2. 设置 `webPreferences.preload` 指向 preload.ts
3. 注册 IPC handler: `dialog:openFile`, `dialog:saveFile`, `app:getPath`
4. 开发模式加载 `http://localhost:5173`，生产模式加载 `dist/renderer/index.html`
5. 注册应用菜单 (File/Edit/View/Help 基础菜单)

**文件: `electron/preload.ts`**

通过 `contextBridge.exposeInMainWorld` 暴露:
```typescript
// 暴露给 Renderer 的安全 API
window.electronAPI = {
  // 文件对话框
  openFileDialog: (options: OpenDialogOptions) => ipcRenderer.invoke('dialog:openFile', options),
  saveFileDialog: (options: SaveDialogOptions) => ipcRenderer.invoke('dialog:saveFile', options),
  
  // 应用信息
  getAppPath: (name: 'userData' | 'appData' | 'documents') => ipcRenderer.invoke('app:getPath', name),
  
  // 平台检测
  platform: process.platform,
};
```

### 3.3 步骤 1.3: Babylon.js 引擎集成

**文件: `src/engine/BabylonEngine.ts`**

设计为单例模式:

```typescript
class BabylonEngine {
  private static instance: BabylonEngine;
  
  engine: Engine;           // Babylon.js Engine
  scene: Scene;             // 主场景
  canvas: HTMLCanvasElement; // 绑定的 Canvas
  
  static getInstance(): BabylonEngine;
  
  // 初始化: 绑定 Canvas → 创建 Engine → 创建 Scene
  async initialize(canvas: HTMLCanvasElement): Promise<void>;
  
  // 渲染循环
  private renderLoop(): void;
  
  // 窗口大小调整
  resize(): void;
  
  // 销毁清理
  dispose(): void;
}
```

**初始化序列:**
1. `new Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true })`
   - `preserveDrawingBuffer: true` 用于后续视频导出截图
   - `stencil: true` 用于高级阴影
2. 创建 Scene: `new Scene(engine)`
3. 设置清除色: `scene.clearColor = new Color4(0.02, 0.02, 0.05, 1.0)` — 极暗蓝调
4. 开启物理基础 (用于后续可能的碰撞): `scene.collisionsEnabled = true`
5. 设置环境光强度为极低: `scene.ambientColor = new Color3(0.05, 0.05, 0.08)`
6. 启动渲染循环: `engine.runRenderLoop(() => scene.render())`

**文件: `src/components/ViewportContainer.tsx`**

React 组件，负责:
1. `useRef<HTMLCanvasElement>` 持有 Canvas 引用
2. `useEffect` 中调用 `BabylonEngine.getInstance().initialize(canvasRef.current!)`
3. 监听窗口 resize 事件，调用 `engine.resize()`
4. 渲染一个全屏 Canvas，CSS: `width: 100%; height: 100%; outline: none;`

### 3.4 步骤 1.4: 3D 舞台搭建

**文件: `src/stage/Stage3D.ts`**

```typescript
class Stage3D {
  private scene: Scene;
  private floor: Mesh;
  private grid: GridMaterial;
  
  constructor(scene: Scene);
  
  // 创建舞台
  createStage(config: StageConfig): void {
    // 1. 创建地板平面 (宽度 × 深度)
    this.floor = MeshBuilder.CreateGround("stageFloor", {
      width: config.width,   // 默认 10m
      height: config.depth   // 默认 10m
    }, this.scene);
    
    // 2. 应用网格材质 (便于感知空间)
    this.grid = new GridMaterial("stageGrid", this.scene);
    this.grid.majorUnitFrequency = 1;    // 每米主线
    this.grid.minorUnitVisibility = 0.3; // 次线半透明
    this.grid.gridRatio = 1;
    this.grid.mainColor = new Color3(0.15, 0.15, 0.2);
    this.grid.lineColor = new Color3(0.3, 0.3, 0.5);
    this.grid.opacity = 0.6;
    this.floor.material = this.grid;
    
    // 3. 地板接收阴影
    this.floor.receiveShadows = true;
  }
  
  // 更新舞台尺寸
  updateSize(width: number, depth: number): void;
  
  // 切换地板显示 (网格/纯色/反射)
  setFloorMode(mode: 'grid' | 'solid' | 'reflective'): void;
}
```

**舞台尺寸参数 (`shared/types/stage.ts`):**
```typescript
interface StageConfig {
  width: number;        // 舞台宽度 (米), 默认 10, 范围 5~50
  depth: number;        // 舞台深度 (米), 默认 10, 范围 5~50
  floorMode: 'grid' | 'solid' | 'reflective';
  floorColor: string;   // Hex color
  showGrid: boolean;    // 是否显示参考网格
  backgroundColor: string; // 背景色 (场景 clearColor)
}
```

### 3.5 步骤 1.5: 暗环境舞台光照

**文件: `src/stage/Lighting.ts`**

Wota 艺的核心视觉特征: **极暗环境 + 聚光灯 + 荧光棒自身发光**。因此光照设计为:

```typescript
class StageLighting {
  private scene: Scene;
  
  // 灯光层次:
  // Layer 1: 极低环境光 (模拟暗场)
  private ambientLight: HemisphericLight;
  
  // Layer 2: 顶部聚光灯 (舞台主光源, 模拟现场演出)
  private spotLights: SpotLight[];  // 可配置 1~4 盏
  
  // Layer 3: 角色补光 (微弱的背光, 勾勒轮廓)
  private rimLight: DirectionalLight;
  
  constructor(scene: Scene);
  
  setupDefaultLighting(): void {
    // 1. 环境光 — 极暗
    this.ambientLight = new HemisphericLight("ambient", 
      new Vector3(0, 1, 0), this.scene);
    this.ambientLight.intensity = 0.05;  // 极低
    this.ambientLight.diffuse = new Color3(0.1, 0.1, 0.15);
    this.ambientLight.groundColor = new Color3(0.02, 0.02, 0.03);
    
    // 2. 主聚光灯 — 从上方斜45度照射
    const spot = new SpotLight("mainSpot",
      new Vector3(0, 8, 5),      // 光源位置 (上方偏前)
      new Vector3(0, -1, -0.5),   // 照射方向 (向下偏后)
      Math.PI / 4,                // 锥角 45°
      0.1,                        // 指数
      this.scene);
    spot.intensity = 2.0;
    spot.diffuse = new Color3(1.0, 0.95, 0.8);  // 暖色
    spot.shadowEnabled = true;
    spot.shadowMinZ = 1;
    spot.shadowMaxZ = 30;
    
    // 3. 轮廓光 — 从后方低位照射
    this.rimLight = new DirectionalLight("rim",
      new Vector3(0, 0.3, -1), this.scene);
    this.rimLight.intensity = 0.3;
    this.rimLight.diffuse = new Color3(0.3, 0.4, 0.6); // 冷色背光
  }
  
  // 动态更新灯光配置
  updateFromConfig(config: LightConfig): void;
}
```

**灯光配置类型:**
```typescript
interface LightConfig {
  ambientIntensity: number;        // 0~1, 默认 0.05
  spotLights: SpotLightConfig[];   // 聚光灯数组
  rimLightIntensity: number;       // 0~1, 默认 0.3
}

interface SpotLightConfig {
  position: [number, number, number];
  direction: [number, number, number];
  angle: number;           // 弧度, 默认 π/4
  intensity: number;
  color: string;           // Hex
  shadowEnabled: boolean;
}
```

### 3.6 步骤 1.6: 轨道摄像机控制

使用 Babylon.js 内置的 `ArcRotateCamera`:

```typescript
// 在 Stage3D 中初始化摄像机
private setupCamera(): void {
  const camera = new ArcRotateCamera(
    "mainCamera",
    -Math.PI / 4,     // alpha: 水平旋转角 (45°)
    Math.PI / 3,      // beta: 垂直仰角 (60°)
    15,               // radius: 距离焦点
    Vector3.Zero(),   // target: 看向舞台中心
    this.scene
  );
  
  camera.lowerRadiusLimit = 3;     // 最近缩放
  camera.upperRadiusLimit = 50;    // 最远缩放
  camera.lowerBetaLimit = 0.1;     // 最低角度 (几乎水平)
  camera.upperBetaLimit = Math.PI / 2 - 0.1; // 最高角度 (几乎垂直)
  
  // 滚轮缩放、右键旋转、中键平移
  camera.attachControl(this.canvas, true);
  
  // 惯性缓动
  camera.inertia = 0.85;
  camera.panningInertia = 0.5;
}
```

### 3.7 步骤 1.7: 舞台配置面板 UI

**文件: `src/components/StageConfigPanel.tsx`**

React 组件，与 `stageStore` 双向绑定:

```
┌─────────────────────────┐
│ 🎬 舞台配置              │
├─────────────────────────┤
│ 宽度: [====|====] 10m   │  ← 滑块
│ 深度: [====|====] 10m   │
│ 地板模式: [网格 ▼]       │  ← 下拉: 网格/纯色/反射
│ 地板颜色: [■] #222244   │  ← 颜色选择器
│ 背景颜色: [■] #050510   │
│ 显示网格: [✓]            │  ← 开关
│                         │
│ 💡 灯光                 │
│ 环境光: [=] 0.05       │
│ 聚光灯亮度: [===] 2.0  │
│ 背光亮度: [=] 0.3      │
└─────────────────────────┘
```

**Zustand Store (`src/stores/stageStore.ts`):**
```typescript
interface StageState {
  config: StageConfig;
  lightConfig: LightConfig;
  
  // Actions
  setWidth: (width: number) => void;
  setDepth: (depth: number) => void;
  setFloorMode: (mode: 'grid' | 'solid' | 'reflective') => void;
  updateLightConfig: (partial: Partial<LightConfig>) => void;
  
  // 从项目文件加载
  loadFromProject: (data: ProjectStageData) => void;
  
  // 序列化为项目数据
  toJSON: () => ProjectStageData;
}
```

### 3.8 阶段 1 验证清单

- [ ] `npm run dev` 启动后看到 Electron 窗口
- [ ] 窗口中有 3D 暗色舞台，可见网格地面
- [ ] 鼠标左键拖拽旋转视角、滚轮缩放、右键平移
- [ ] 右侧面板拖动滑块 → 舞台尺寸实时变化
- [ ] 切换地板模式 → 网格/纯色切换生效
- [ ] 聚光灯在地板上投射可见阴影区域
- [ ] 窗口缩放 → Canvas 自适应

---

## 4. 阶段 2: 角色系统

> **目标**: 舞台上有可配置的人形角色，骨骼绑定完成，支持多角色
> **工期**: 2 周
> **依赖**: 阶段 1

### 4.1 步骤 2.1: 标准骨骼层级定义

Wota 艺动作的核心在于上肢（手臂、手掌）和躯干扭转。采用 SMPL 24 关节作为内部标准骨骼。

**文件: `shared/constants/skeleton.ts`**

```typescript
// SMPL 24 关节索引与名称映射
enum SkeletonJoint {
  PELVIS = 0,
  LEFT_HIP = 1,
  RIGHT_HIP = 2,
  SPINE_1 = 3,
  LEFT_KNEE = 4,
  RIGHT_KNEE = 5,
  SPINE_2 = 6,
  LEFT_ANKLE = 7,
  RIGHT_ANKLE = 8,
  SPINE_3 = 9,
  LEFT_FOOT = 10,
  RIGHT_FOOT = 11,
  NECK = 12,
  LEFT_COLLAR = 13,
  RIGHT_COLLAR = 14,
  HEAD = 15,
  LEFT_SHOULDER = 16,
  RIGHT_SHOULDER = 17,
  LEFT_ELBOW = 18,
  RIGHT_ELBOW = 19,
  LEFT_WRIST = 20,
  RIGHT_WRIST = 21,
  // 扩展关节 (用于荧光棒绑定)
  LEFT_HAND = 22,   // 左手掌中心 (SMPL 无此关节, 从 WRIST 推算)
  RIGHT_HAND = 23,  // 右手掌中心
}

// 骨骼父子关系 (用于构造层级)
const SKELETON_HIERARCHY: Record<SkeletonJoint, SkeletonJoint | null> = {
  [SkeletonJoint.PELVIS]: null,        // 根节点
  [SkeletonJoint.LEFT_HIP]: SkeletonJoint.PELVIS,
  [SkeletonJoint.RIGHT_HIP]: SkeletonJoint.PELVIS,
  [SkeletonJoint.SPINE_1]: SkeletonJoint.PELVIS,
  [SkeletonJoint.LEFT_KNEE]: SkeletonJoint.LEFT_HIP,
  [SkeletonJoint.RIGHT_KNEE]: SkeletonJoint.RIGHT_HIP,
  [SkeletonJoint.SPINE_2]: SkeletonJoint.SPINE_1,
  [SkeletonJoint.LEFT_ANKLE]: SkeletonJoint.LEFT_KNEE,
  [SkeletonJoint.RIGHT_ANKLE]: SkeletonJoint.RIGHT_KNEE,
  [SkeletonJoint.SPINE_3]: SkeletonJoint.SPINE_2,
  [SkeletonJoint.LEFT_FOOT]: SkeletonJoint.LEFT_ANKLE,
  [SkeletonJoint.RIGHT_FOOT]: SkeletonJoint.RIGHT_ANKLE,
  [SkeletonJoint.NECK]: SkeletonJoint.SPINE_3,
  [SkeletonJoint.LEFT_COLLAR]: SkeletonJoint.SPINE_3,
  [SkeletonJoint.RIGHT_COLLAR]: SkeletonJoint.SPINE_3,
  [SkeletonJoint.HEAD]: SkeletonJoint.NECK,
  [SkeletonJoint.LEFT_SHOULDER]: SkeletonJoint.LEFT_COLLAR,
  [SkeletonJoint.RIGHT_SHOULDER]: SkeletonJoint.RIGHT_COLLAR,
  [SkeletonJoint.LEFT_ELBOW]: SkeletonJoint.LEFT_SHOULDER,
  [SkeletonJoint.RIGHT_ELBOW]: SkeletonJoint.RIGHT_SHOULDER,
  [SkeletonJoint.LEFT_WRIST]: SkeletonJoint.LEFT_ELBOW,
  [SkeletonJoint.RIGHT_WRIST]: SkeletonJoint.RIGHT_ELBOW,
  [SkeletonJoint.LEFT_HAND]: SkeletonJoint.LEFT_WRIST,
  [SkeletonJoint.RIGHT_HAND]: SkeletonJoint.RIGHT_WRIST,
};

// 关节名称 (日/英/中 三语, 方便 Wota 艺社区使用)
const JOINT_NAMES: Record<SkeletonJoint, { ja: string; en: string; zh: string }> = {
  // ...
};
```

### 4.2 步骤 2.2: 默认角色模型方案

**方案: Mixamo 免费模型 + 程序化骨骼回退**

1. **首选**: 内置 1 个 Mixamo 人形模型 (如 "Y Bot" 简化版)，导出为 `.glb`，骨骼已符合 Mixamo 65 关节标准
2. **回退**: 如果 Mixamo 模型不可用，用 Babylon.js 程序化生成简易人形:
   - 每个骨骼段用 `Cylinder` + `Sphere` 组合
   - 材质用纯色半透明，标记为 "开发者模式"
3. **扩展**: 支持用户导入自定义 `.glb` 模型，通过骨骼映射表适配

**文件: `src/character/CharacterModel.ts`**

```typescript
class CharacterModel {
  id: string;
  name: string;
  
  // Babylon.js 对象
  rootMesh: TransformNode;        // 角色根节点 (控制世界位置/旋转)
  skeleton: Skeleton;             // Babylon.js Skeleton
  meshes: AbstractMesh[];         // 所有蒙皮 Mesh
  boneMap: Map<string, Bone>;     // 骨骼名称 → Bone 对象
  
  // 配置
  config: CharacterConfig;
  
  // 从 glTF 加载
  static async loadFromGLTF(
    url: string, 
    scene: Scene, 
    config: CharacterConfig
  ): Promise<CharacterModel>;
  
  // 程序化生成简易人形
  static createProcedural(
    scene: Scene, 
    config: CharacterConfig
  ): CharacterModel;
  
  // 应用体型缩放 (不影响动画数据)
  applyScale(scale: number): void;
  
  // 获取指定关节的世界坐标 (用于 VFX)
  getJointWorldPosition(joint: SkeletonJoint): Vector3;
  
  // 获取指定关节的世界旋转
  getJointWorldRotation(joint: SkeletonJoint): Quaternion;
}
```

### 4.3 步骤 2.3: 骨骼层级构造

**文件: `src/character/SkeletonRig.ts`**

```typescript
class SkeletonRig {
  bones: Bone[];                   // 按 SkeletonJoint 顺序
  boneIndexMap: Map<SkeletonJoint, number>; // 关节枚举 → 数组索引
  
  constructor(name: string, scene: Scene);
  
  // 根据 SKELETON_HIERARCHY 递归创建 Bone 层级
  buildHierarchy(): void {
    // 1. 创建根 Bone (PELVIS)
    // 2. 遍历 HIERARCHY，为每个子关节创建 Bone
    // 3. 设置每个 Bone 的初始 rest pose (T-Pose)
    // 4. link bone with parent
  }
  
  // 将 MotionData 应用到骨骼
  applyPose(pose: FramePose): void {
    for (const [jointIndex, transform] of pose.transforms) {
      const bone = this.bones[jointIndex];
      bone.setRotation(transform.rotation);
      // 根骨骼 (PELVIS) 才有位移
      if (jointIndex === SkeletonJoint.PELVIS) {
        bone.setPosition(transform.position);
      }
    }
  }
  
  // 重置为 T-Pose
  resetToRestPose(): void;
  
  // 在开发模式下可视化骨骼 (画线连接关节)
  visualizeDebug(scene: Scene): void;
}
```

### 4.4 步骤 2.4: 角色配置

**类型定义 (`shared/types/character.ts`):**
```typescript
interface CharacterConfig {
  id: string;
  name: string;              // 角色名称, 如 "Player 1"
  
  // 外观
  modelSource: 'default' | 'procedural' | 'custom';
  customModelPath?: string;  // 自定义 .glb 路径
  skeletonMapping?: Record<string, string>; // 自定义模型骨骼 → 标准关节映射
  
  // 体型 (不影响骨骼动画数据)
  height: number;            // 身高 (m), 默认 1.7, 范围 1.0~2.5
  bodyScale: number;         // 整体缩放, 与 height 联动
  
  // 舞台站位
  position: [number, number, number];  // 世界坐标 [x, y, z]
  rotation: number;          // Y 轴旋转 (度)
  
  // 显示
  visible: boolean;
  showSkeleton: boolean;     // 开发者模式骨骼可视化
  opacity: number;           // 0~1
}
```

### 4.5 步骤 2.5: 多角色管理

**文件: `src/stores/characterStore.ts`**

```typescript
interface CharacterState {
  characters: Map<string, CharacterModel>;  // id → 模型实例
  configs: Map<string, CharacterConfig>;     // id → 配置
  selectedId: string | null;                 // 当前选中角色
  
  // Actions
  addCharacter: (config?: Partial<CharacterConfig>) => string; // 返回 id
  removeCharacter: (id: string) => void;
  selectCharacter: (id: string) => void;
  updateConfig: (id: string, partial: Partial<CharacterConfig>) => void;
  duplicateCharacter: (id: string) => string;
  
  // 批量操作
  selectAll: () => void;
  alignCharacters: (mode: 'row' | 'v-formation' | 'custom') => void;
}
```

**角色列表面板 UI:**
```
┌─────────────────────────┐
│ 👥 角色列表         [+新增]│
├─────────────────────────┤
│ ● Player 1         [👁] │  ← 点击选中, 眼睛图标切换可见
│ ○ Player 2         [👁] │
│ ○ Player 3         [👁] │
├─────────────────────────┤
│ 选中角色: Player 1       │
│ 模型: [默认模型 ▼]      │
│ 身高: [======|] 1.7m   │
│ X: [===|] 0.0          │
│ Z: [===|] 0.0          │
│ 旋转: [=|] 0°          │
│ 显示骨骼: [ ]           │
└─────────────────────────┘
```

### 4.6 阶段 2 验证清单

- [ ] 舞台上默认站立一个人形角色 (T-Pose)
- [ ] 角色脚下有阴影
- [ ] 面板可调身高 → 角色等比缩放
- [ ] 面板可调站位 → 角色移动到指定位置
- [ ] 点击 "+" 新增角色 → 两个角色并排
- [ ] 勾选 "显示骨骼" → 角色身上出现骨骼线段
- [ ] 选中不同角色 → 属性面板切换
- [ ] 缩放摄像机 → 不影响角色实际大小

---

## 5. 阶段 3: 动作数据系统

> **目标**: 完整的动作数据模型、SQLite 持久化、动作库 UI、骨骼动画播放
> **工期**: 2 周
> **依赖**: 阶段 2

### 5.1 步骤 3.1: 内部动作数据格式设计

**文件: `shared/types/motion.ts`**

```typescript
// ========== 核心数据结构 ==========

/** 单帧中单个关节的变换 */
interface JointTransform {
  /** 旋转 (四元数, [x, y, z, w]) */
  rotation: [number, number, number, number];
  /** 位移 (仅根骨骼 PELVIS 使用, 其余骨骼位移恒为零) */
  position?: [number, number, number];
}

/** 单帧中所有关节的变换集合 */
interface FramePose {
  /** frame 索引 (从 0 开始) */
  frame: number;
  /** 关节变换映射: 关节索引 → 变换 */
  transforms: Record<number, JointTransform>;
  /** 该帧的置信度 (0~1) */
  confidence?: number;
}

/** Wota 艺节拍标记 */
interface BeatMarker {
  frame: number;
  /** 音乐节拍位置, 如 "1-1-1" (第1小节第1拍第1子拍) */
  beat: string;
  /** 标记类型 */
  type: 'kime' | 'downbeat' | 'transition' | 'custom';
  label?: string;  // 如 "サビ開始", "雷蛇后半段"
}

/** 完整动作数据 */
interface MotionData {
  // 元数据
  id: string;                    // UUID
  name: string;                  // 动作名称, 如 "Thunder Snake 完整版"
  description?: string;         // 描述
  tags: string[];               // 标签: ["sabi", "thunder-snake", "高速技"]
  
  // 技术参数
  fps: number;                   // 帧率 (默认 30)
  duration: number;              // 时长 (秒)
  frameCount: number;            // 总帧数
  skeletonType: 'smpl_24';      // 骨架类型
  
  // 数据
  poses: FramePose[];            // 逐帧姿态
  
  // 标记
  beatMarkers: BeatMarker[];     // 节拍标记
  keyframeFlags: number[];       // 关键帧标记 (帧索引数组)
  
  // 统计 (便于搜索和排序)
  motionIntensity: number;       // 运动强度 0~1 (基于速度方差)
  primaryJoints: number[];       // 主要运动关节索引
  isLoopable: boolean;           // 是否可循环
  
  // 来源
  source: 'ai-capture' | 'manual' | 'imported';
  sourceVideoPath?: string;      // 如果是 AI 提取的, 记录源视频
  createdAt: string;             // ISO 8601
  updatedAt: string;
}

// ========== 播放运行时类型 ==========

/** 动作片段 (时间线上的一小段) */
interface MotionClip {
  id: string;
  motionId: string;             // 引用 MotionData.id
  startFrame: number;           // 从动作的第几帧开始
  endFrame: number;             // 到动作的第几帧结束
  speed: number;                // 播放速度倍率 (默认 1.0)
  loop: boolean;                // 是否循环
}
```

**文件大小估算:**
- 单帧: 24 关节 × 4 float32 (四元数) × 4 bytes = 384 bytes
- 3 分钟动作 @ 30fps: 5400 帧 × 384 bytes ≈ 2 MB
- 10 个动作: ~20 MB (完全可接受)

### 5.2 步骤 3.2: SQLite 数据库设计

**文件: `database/schema.sql`**

```sql
-- ========== 动作表 ==========
CREATE TABLE motions (
    id              TEXT PRIMARY KEY,           -- UUID
    name            TEXT NOT NULL,              -- 动作名称
    description     TEXT DEFAULT '',
    tags            TEXT DEFAULT '[]',          -- JSON 数组
    fps             REAL NOT NULL DEFAULT 30.0,
    duration        REAL NOT NULL,             -- 秒
    frame_count     INTEGER NOT NULL,
    skeleton_type   TEXT NOT NULL DEFAULT 'smpl_24',
    
    -- 动作数据存储为 JSON (SQLite 5+ 支持 JSON 函数查询)
    poses_json      TEXT NOT NULL,             -- JSON: FramePose[]
    beat_markers_json TEXT DEFAULT '[]',       -- JSON: BeatMarker[]
    keyframe_flags  TEXT DEFAULT '[]',         -- JSON: number[]
    
    -- 统计
    motion_intensity REAL DEFAULT 0.0,
    primary_joints  TEXT DEFAULT '[]',
    is_loopable     INTEGER DEFAULT 0,
    
    -- 来源
    source          TEXT NOT NULL DEFAULT 'manual',
    source_video_path TEXT,
    
    -- 缩略图 (Base64 编码的小图, 用于动作库预览)
    thumbnail       TEXT,                      -- Base64 PNG
    
    -- 时间戳
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_motions_name ON motions(name);
CREATE INDEX idx_motions_tags ON motions(tags);  -- JSON 索引
CREATE INDEX idx_motions_source ON motions(source);
CREATE INDEX idx_motions_intensity ON motions(motion_intensity);

-- ========== 标签表 (用于自动补全) ==========
CREATE TABLE tags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    usage_count     INTEGER DEFAULT 1
);

-- ========== 项目表 ==========
CREATE TABLE projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    project_json    TEXT NOT NULL,             -- 完整项目序列化
    thumbnail       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ========== 用户设置表 ==========
CREATE TABLE settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL              -- JSON
);

-- 插入默认设置
INSERT OR IGNORE INTO settings (key, value) VALUES 
    ('stage_defaults', '{"width":10,"depth":10,"floorMode":"grid"}'),
    ('render_quality', '"high"'),
    ('language', '"zh-CN"'),
    ('auto_save_interval', '300');
```

### 5.3 步骤 3.3: 数据库 IPC 层

**文件: `electron/ipc/database-handler.ts`**

```typescript
import Database from 'better-sqlite3';
import path from 'path';
import { app } from 'electron';

class DatabaseHandler {
  private db: Database.Database;
  
  constructor() {
    const dbPath = path.join(app.getPath('userData'), 'torch-monkey.db');
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');       // 写性能优化
    this.db.pragma('foreign_keys = ON');
    this.initialize();
  }
  
  private initialize(): void {
    // 读取 schema.sql 并执行
    const schema = readSchemaFile();
    this.db.exec(schema);
  }
  
  // ===== Motion CRUD =====
  
  createMotion(data: MotionData): void {
    const stmt = this.db.prepare(`
      INSERT INTO motions (id, name, description, tags, fps, duration, 
        frame_count, skeleton_type, poses_json, beat_markers_json,
        keyframe_flags, motion_intensity, primary_joints, is_loopable,
        source, source_video_path, thumbnail)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(/* ... */);
  }
  
  getMotion(id: string): MotionData | null {
    const row = this.db.prepare('SELECT * FROM motions WHERE id = ?').get(id);
    if (!row) return null;
    return this.rowToMotionData(row);
  }
  
  listMotions(options: {
    search?: string;
    tags?: string[];
    source?: string;
    sortBy?: 'name' | 'created_at' | 'intensity';
    sortOrder?: 'asc' | 'desc';
    limit?: number;
    offset?: number;
  }): { motions: MotionData[]; total: number } {
    // 构建动态 SQL 查询
    // 使用 JSON 函数过滤 tags: json_extract(tags, '$') LIKE '%tag%'
  }
  
  updateMotion(id: string, partial: Partial<MotionData>): void;
  deleteMotion(id: string): void;
  
  // ===== Tag CRUD =====
  
  getPopularTags(limit?: number): { name: string; count: number }[];
  
  // ===== Project CRUD =====
  
  saveProject(data: ProjectData): void;
  getProject(id: string): ProjectData | null;
  listProjects(): { id: string; name: string; thumbnail?: string; updatedAt: string }[];
  
  // ===== Settings =====
  
  getSetting(key: string): string | null;
  setSetting(key: string, value: string): void;
  
  // ===== Utility =====
  
  getStats(): { motionCount: number; projectCount: number; totalStorageBytes: number };
  
  close(): void {
    this.db.close();
  }
}
```

**IPC 注册 (`electron/main.ts`):**
```typescript
const db = new DatabaseHandler();

ipcMain.handle('db:createMotion', (_, data) => db.createMotion(data));
ipcMain.handle('db:getMotion', (_, id) => db.getMotion(id));
ipcMain.handle('db:listMotions', (_, opts) => db.listMotions(opts));
ipcMain.handle('db:updateMotion', (_, id, partial) => db.updateMotion(id, partial));
ipcMain.handle('db:deleteMotion', (_, id) => db.deleteMotion(id));
ipcMain.handle('db:getPopularTags', (_, limit) => db.getPopularTags(limit));
ipcMain.handle('db:saveProject', (_, data) => db.saveProject(data));
ipcMain.handle('db:getProject', (_, id) => db.getProject(id));
ipcMain.handle('db:listProjects', () => db.listProjects());
ipcMain.handle('db:getSetting', (_, key) => db.getSetting(key));
ipcMain.handle('db:setSetting', (_, key, value) => db.setSetting(key, value));
ipcMain.handle('db:getStats', () => db.getStats());
```

### 5.4 步骤 3.4: 动作库面板 UI

**文件: `src/motion/MotionLibrary.tsx`**

布局: 左侧列表 + 右侧预览详情

```
┌──────────────────────────────────────────────────┐
│ 🔍 [搜索动作...]  🏷 [标签过滤 ▼]  📋 [+导入]    │
├────────────────────┬─────────────────────────────┤
│ 动作列表            │ 预览详情                     │
│                    │                             │
│ ┌────────────────┐ │ 名称: Thunder Snake 完整版   │
│ │ 🎬 Thunder Sn..│ │ 时长: 12.5s  FPS: 30        │
│ │   标签: sabi   │ │ 帧数: 375                   │
│ │   强度: ████░░ │ │                             │
│ │   来源: AI 提取 │ │ ┌─────────────────────────┐ │
│ └────────────────┘ │ │                         │ │
│ ┌────────────────┐ │ │    3D 预览骨骼动画       │ │
│ │ 🎬 Romance     │ │ │    (小视口中循环播放)    │ │
│ │   标签: kecha  │ │ │                         │ │
│ │   强度: ██░░░░ │ │ └─────────────────────────┘ │
│ └────────────────┘ │                             │
│ ┌────────────────┐ │ 标签: [sabi] [thunder] [+]  │
│ │ 🎬 OAD 基础    │ │ 可循环: ✓                  │
│ │   标签: oad    │ │                             │
│ │   强度: ███░░░ │ │ [拖入时间线] [导出 glTF]    │
│ └────────────────┘ │ [删除] [重命名]             │
│                    │                             │
│ 共 12 个动作        │                             │
└────────────────────┴─────────────────────────────┘
```

**核心交互:**
1. **搜索**: 实时过滤 name/description
2. **标签过滤**: 多选标签, AND 逻辑
3. **拖拽**: 从列表拖 MotionClip 到时间线轨道 (HTML5 Drag & Drop API)
4. **预览**: 选中后右侧小 Babylon.js 视口循环播放骨骼动画
5. **排序**: 按名称/日期/强度

**Zustand Store (`src/stores/motionStore.ts`):**
```typescript
interface MotionState {
  motionList: MotionMeta[];       // 列表(不含完整 poses 数据)
  selectedId: string | null;
  selectedMotion: MotionData | null; // 选中后才加载完整数据
  searchQuery: string;
  filterTags: string[];
  
  // Actions
  loadMotionList: () => Promise<void>;
  selectMotion: (id: string) => Promise<void>;
  importMotion: (data: MotionData) => Promise<void>;
  deleteMotion: (id: string) => Promise<void>;
  updateMotionMeta: (id: string, partial: Partial<MotionData>) => Promise<void>;
  setSearchQuery: (q: string) => void;
  toggleFilterTag: (tag: string) => void;
  
  // 导出
  exportAsGLTF: (id: string) => Promise<void>;
  exportAsBVH: (id: string) => Promise<void>;
}

// 轻量元数据 (列表用, 不含 poses)
interface MotionMeta {
  id: string;
  name: string;
  duration: number;
  tags: string[];
  motionIntensity: number;
  source: string;
  thumbnail?: string;
}
```

### 5.5 步骤 3.5: 骨骼动画播放器

**文件: `src/character/MotionPlayer.ts`**

```typescript
class MotionPlayer {
  private rig: SkeletonRig;
  private motionData: MotionData | null;
  private currentTime: number;    // 秒
  private isPlaying: boolean;
  private speed: number;          // 倍率
  
  constructor(rig: SkeletonRig);
  
  // 加载动作数据
  loadMotion(data: MotionData): void;
  
  // 播放控制
  play(): void;
  pause(): void;
  stop(): void;     // 回到第 0 帧
  seek(time: number): void;
  
  // 设置播放速度
  setSpeed(speed: number): void;
  
  // 每帧调用 (由 scene.registerBeforeRender 驱动)
  update(deltaTime: number): void {
    if (!this.isPlaying || !this.motionData) return;
    
    this.currentTime += deltaTime * this.speed;
    
    // 边界检查
    const duration = this.motionData.duration;
    if (this.currentTime >= duration) {
      if (this.loop) {
        this.currentTime %= duration;
      } else {
        this.currentTime = duration;
        this.pause();
        return;
      }
    }
    
    // 计算当前帧
    const frameFloat = this.currentTime * this.motionData.fps;
    const frameIndex = Math.floor(frameFloat);
    const frameFraction = frameFloat - frameIndex;
    
    // 获取前后关键帧
    const prevPose = this.motionData.poses[frameIndex];
    const nextPose = this.motionData.poses[Math.min(frameIndex + 1, this.motionData.frameCount - 1)];
    
    // 对每个关节进行四元数球面线性插值 (slerp)
    const interpolatedPose = this.interpolatePoses(prevPose, nextPose, frameFraction);
    
    // 应用到骨骼
    this.rig.applyPose(interpolatedPose);
  }
  
  // 四元数 slerp 插值
  private interpolatePoses(prev: FramePose, next: FramePose, t: number): FramePose {
    const result: FramePose = { frame: prev.frame, transforms: {} };
    
    for (const jointIndex of Object.keys(prev.transforms)) {
      const idx = Number(jointIndex);
      const prevRot = Quaternion.FromArray(prev.transforms[idx].rotation);
      const nextRot = Quaternion.FromArray(next.transforms[idx].rotation);
      
      // slerp
      const interpolatedRot = Quaternion.Slerp(prevRot, nextRot, t);
      
      result.transforms[idx] = {
        rotation: [interpolatedRot.x, interpolatedRot.y, interpolatedRot.z, interpolatedRot.w],
      };
      
      // 根骨骼位移用 lerp
      if (idx === SkeletonJoint.PELVIS) {
        const prevPos = prev.transforms[idx].position || [0, 0, 0];
        const nextPos = next.transforms[idx].position || [0, 0, 0];
        result.transforms[idx].position = [
          prevPos[0] + (nextPos[0] - prevPos[0]) * t,
          prevPos[1] + (nextPos[1] - prevPos[1]) * t,
          prevPos[2] + (nextPos[2] - prevPos[2]) * t,
        ];
      }
    }
    return result;
  }
}
```

### 5.6 步骤 3.6: 内置测试动作

在阶段 3 结尾，需要手动创建 2-3 个测试动作来验证整个播放链路:

1. **T-Pose 静止 (1 秒)**: 所有关节为 rest pose
2. **右手画圆 (3 秒)**: RIGHT_SHOULDER → RIGHT_ELBOW → RIGHT_WRIST 的关键帧手动编辑
3. **简易鞠躬 (2 秒)**: SPINE 链前倾 + 手臂随动

这些测试动作用 JSON 直接写入，不经过 AI 管线。

### 5.7 阶段 3 验证清单

- [ ] 动作库面板显示 3 个内置测试动作
- [ ] 点击动作 → 右侧显示详情 + 3D 骨骼预览动画
- [ ] 搜索框输入 "circle" → 过滤出画圆动作
- [ ] 从动作库拖拽到舞台上角色 → 角色播放该动作
- [ ] 播放/暂停/停止按钮生效
- [ ] 速度滑块调为 0.5x/2x → 动作变慢/变快
- [ ] 关闭重开应用 → 动作数据仍在 (SQLite 持久化)
- [ ] 删除动作 → 确认后从库中移除

---

## 6. 阶段 4: AI 视频动捕管线

> **目标**: 导入 Wota 艺视频 → AI 自动提取 3D 动作 → 存入动作库
> **工期**: 3-4 周
> **依赖**: 阶段 3 (动作数据格式已定义)、阶段 1 (IPC 通道已建立)

### 6.1 步骤 4.1: Python 环境与 FastAPI 服务搭建

**文件: `python/server.py`**

```python
"""
Torch Monkey AI Pipeline Server
本地 HTTP 服务，由 Electron Main Process 通过 child_process 管理生命周期
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pipeline.video_processor import VideoProcessor
from pipeline.pose_estimator_2d import MediaPipeEstimator
from pipeline.pose_estimator_3d import MotionBERTEstimator
from pipeline.wotagei_optimizer import WotageiOptimizer
from pipeline.format_exporter import FormatExporter

# ===== 全局模型实例 (启动时加载一次) =====
mediapipe_estimator: MediaPipeEstimator = None
motionbert_estimator: MotionBERTEstimator = None
optimizer: WotageiOptimizer = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时加载模型, 关闭时释放"""
    global mediapipe_estimator, motionbert_estimator, optimizer
    
    logging.info("Loading AI models...")
    mediapipe_estimator = MediaPipeEstimator()
    motionbert_estimator = MotionBERTEstimator()
    optimizer = WotageiOptimizer()
    logging.info("All models loaded successfully.")
    
    yield  # 服务运行中
    
    # 清理
    logging.info("Shutting down AI pipeline...")

app = FastAPI(
    title="Torch Monkey AI Pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

# 仅允许本地访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*", "app://.*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 健康检查 =====
@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "models": {
            "mediapipe": mediapipe_estimator is not None,
            "motionbert": motionbert_estimator is not None,
        }
    }

# ===== 视频处理接口 =====
@app.post("/api/process-video")
async def process_video(
    file: UploadFile = File(...),
    fps: float = 30.0,
    smooth: bool = True,
    detect_kime: bool = True,
):
    """
    完整视频处理管线:
    1. 保存上传的视频到临时目录
    2. 提取帧 (ffmpeg)
    3. 2D 关键点检测 (MediaPipe)
    4. 3D 姿态估计 (MotionBERT)
    5. Wota 艺优化 (平滑 + 卡点检测)
    6. 导出为内部 MotionData JSON
    """
    task_id = str(uuid.uuid4())
    
    # 保存视频
    video_path = save_uploaded_video(file)
    
    # 创建 VideoProcessor
    processor = VideoProcessor(video_path, target_fps=fps)
    
    # Step 1: 提取帧
    frames = processor.extract_frames()
    
    # Step 2: 2D 关键点
    keypoints_2d = mediapipe_estimator.process_batch(frames)
    
    # Step 3: 3D 姿态
    poses_3d = motionbert_estimator.infer(keypoints_2d)
    
    # Step 4: Wota 艺优化
    if smooth or detect_kime:
        poses_3d = optimizer.optimize(
            poses_3d,
            apply_smoothing=smooth,
            detect_kime=detect_kime,
        )
    
    # Step 5: 格式导出
    motion_data = FormatExporter.to_motion_data(
        poses_3d=poses_3d,
        fps=fps,
        source_video=file.filename,
    )
    
    return JSONResponse(content={
        "task_id": task_id,
        "status": "completed",
        "motion_data": motion_data,
        "stats": {
            "frame_count": len(frames),
            "duration_seconds": len(frames) / fps,
            "kime_count": len(motion_data.get("beatMarkers", [])),
        }
    })

# ===== 视频信息预览 (不完整处理, 快速返回) =====
@app.post("/api/preview-video")
async def preview_video(file: UploadFile = File(...)):
    """快速分析视频: 时长、帧率、分辨率, 不做 AI 推理"""
    video_path = save_uploaded_video(file)
    info = get_video_info(video_path)  # 使用 ffprobe
    return {"info": info}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=19876, log_level="info")
```

### 6.2 步骤 4.2: 视频帧提取

**文件: `python/pipeline/video_processor.py`**

```python
import subprocess
import tempfile
from pathlib import Path
import numpy as np
import cv2


class VideoProcessor:
    """视频导入与帧提取"""
    
    def __init__(self, video_path: str, target_fps: float = 30.0):
        self.video_path = Path(video_path)
        self.target_fps = target_fps
        self.temp_dir = Path(tempfile.mkdtemp(prefix="torchmonkey_"))
    
    def get_video_info(self) -> dict:
        """使用 ffprobe 获取视频元信息"""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(self.video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        import json
        info = json.loads(result.stdout)
        
        video_stream = next(
            s for s in info["streams"] if s["codec_type"] == "video"
        )
        return {
            "width": video_stream["width"],
            "height": video_stream["height"],
            "fps": eval(video_stream.get("r_frame_rate", "30/1")),
            "duration": float(info["format"]["duration"]),
            "codec": video_stream["codec_name"],
            "bitrate": int(info["format"]["bit_rate"]),
        }
    
    def extract_frames(self) -> list[np.ndarray]:
        """
        提取视频帧为 numpy 数组列表
        
        策略:
        - 如果源帧率 > 目标帧率 → 使用 ffmpeg 按目标帧率抽取
        - 如果源帧率 = 目标帧率 → 直接逐帧读取
        - 如果源帧率 < 目标帧率 → 逐帧读取 (不插值, 保留原始帧)
        
        Wota 艺建议使用 60fps 源视频以捕捉快速动作
        """
        # 使用 OpenCV 逐帧读取 (简单可靠)
        cap = cv2.VideoCapture(str(self.video_path))
        source_fps = cap.get(cv2.CAP_PROP_FPS)
        
        frames = []
        frame_interval = max(1, int(source_fps / self.target_fps))
        frame_idx = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_idx % frame_interval == 0:
                # BGR → RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(frame_rgb)
            
            frame_idx += 1
        
        cap.release()
        return frames
    
    def cleanup(self):
        """删除临时文件"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
```

### 6.3 步骤 4.3: MediaPipe 2D 关键点提取

**文件: `python/pipeline/pose_estimator_2d.py`**

```python
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from typing import Optional


class MediaPipeEstimator:
    """
    MediaPipe Pose Landmarker 封装
    使用 BlazePose 33 关键点模型 (Apache 2.0 许可)
    """
    
    # MediaPipe 33 关键点 → 我们内部 24 关节的映射
    # BlazePose 索引参考: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
    MEDIAPIPE_TO_SMPL24 = {
        # MP index → SMPL24 index
        23: 0,   # 左髋 → PELVIS
        24: 0,   # 右髋 → PELVIS (平均)
        11: 12,  # 左肩 → LEFT_COLLAR
        12: 13,  # 右肩 → RIGHT_COLLAR
        13: 16,  # 左肘 → LEFT_SHOULDER (实际是上臂)
        14: 17,  # 右肘 → RIGHT_SHOULDER
        15: 20,  # 左腕 → LEFT_WRIST
        16: 21,  # 右腕 → RIGHT_WRIST
        25: 4,   # 左膝 → LEFT_KNEE
        26: 5,   # 右膝 → RIGHT_KNEE
        27: 7,   # 左踝 → LEFT_ANKLE
        28: 8,   # 右踝 → RIGHT_ANKLE
        # ... 更多映射
    }
    
    def __init__(self):
        base_options = python.BaseOptions(
            model_asset_path="models/pose_landmarker_heavy.task"
        )
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            output_segmentations=False,
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,  # 单人动捕
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.detector = vision.PoseLandmarker.create_from_options(options)
    
    def process_frame(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        处理单帧, 返回 (33, 3) 关键点 [x, y, z, visibility]
        坐标已归一化到 [0, 1]
        """
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
        result = self.detector.detect(mp_image)
        
        if not result.pose_landmarks:
            return None
        
        landmarks = result.pose_landmarks[0]
        keypoints = np.zeros((33, 4), dtype=np.float32)
        
        for i, lm in enumerate(landmarks):
            keypoints[i] = [lm.x, lm.y, lm.z, lm.visibility or 0.0]
        
        return keypoints
    
    def process_batch(self, frames: list[np.ndarray]) -> np.ndarray:
        """
        批量处理所有帧
        返回: (T, 33, 4) numpy array
        """
        all_keypoints = []
        
        for i, frame in enumerate(frames):
            kp = self.process_frame(frame)
            if kp is not None:
                all_keypoints.append(kp)
            else:
                # 检测失败时复用上一帧 (或补零)
                if all_keypoints:
                    all_keypoints.append(all_keypoints[-1])
                else:
                    all_keypoints.append(np.zeros((33, 4), dtype=np.float32))
        
        return np.stack(all_keypoints, axis=0)
```

### 6.4 步骤 4.4: MotionBERT 3D 姿态估计

**文件: `python/pipeline/pose_estimator_3d.py`**

```python
import numpy as np
import torch
import logging


class MotionBERTEstimator:
    """
    MotionBERT 3D 姿态估计封装
    
    输入: (T, 33, 3) 2D 关键点序列
    输出: (T, 24, 3) 3D 关节坐标 (mm, 以骨盆为原点)
    
    模型: MotionBERT-Lite (Apache 2.0)
    特性:
    - 243 帧时序上下文窗口
    - 对快速/抖动舞蹈鲁棒
    - 推理速度: ~10ms/帧 (RTX 3080)
    """
    
    def __init__(self, model_path: str = "models/motionbert_lite.ckpt"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logging.info(f"MotionBERT using device: {self.device}")
        
        # 加载模型 (伪代码, 具体依 MotionBERT 官方代码)
        self.model = self._load_model(model_path)
        self.model.to(self.device)
        self.model.eval()
        
        # 上下文窗口大小 (帧)
        self.context_window = 243
    
    def _load_model(self, path: str):
        """加载 MotionBERT 模型权重"""
        # 实际实现依赖 MotionBERT 官方仓库的模型定义
        # 这里展示接口设计
        from motionbert import MotionBERTModel
        model = MotionBERTModel(
            num_joints=17,       # 输入 2D 关节数 (MediaPipe 33 → 映射到 17)
            in_channels=2,       # (x, y)
            out_channels=3,      # (x, y, z)
            depth=5,
            hidden_dim=512,
        )
        checkpoint = torch.load(path, map_location=self.device)
        model.load_state_dict(checkpoint["state_dict"])
        return model
    
    def infer(self, keypoints_2d: np.ndarray) -> np.ndarray:
        """
        主推理函数
        
        参数:
            keypoints_2d: (T, 33, 4) — [x, y, z, visibility]
        
        返回:
            poses_3d: (T, 24, 3) — 3D 关节坐标
        """
        T = keypoints_2d.shape[0]
        
        # 预处理: 提取 (x, y) 并映射到 17 关节
        kp_2d_17 = self._map_to_17_joints(keypoints_2d)  # (T, 17, 2)
        
        # 归一化
        kp_2d_norm = self._normalize(kp_2d_17)
        
        # 滑动窗口推理 (243 帧上下文)
        all_poses_3d = []
        
        with torch.no_grad():
            for i in range(0, T, self.context_window // 2):  # 50% 重叠
                start = max(0, i - self.context_window // 2)
                end = min(T, i + self.context_window // 2)
                
                clip = kp_2d_norm[start:end]  # (W, 17, 2)
                
                # Padding 到固定长度
                if clip.shape[0] < self.context_window:
                    pad_size = self.context_window - clip.shape[0]
                    clip = np.pad(clip, ((0, pad_size), (0, 0), (0, 0)))
                
                input_tensor = torch.from_numpy(clip).unsqueeze(0).to(self.device)
                # (1, 243, 17, 2)
                
                output = self.model(input_tensor)  # (1, 243, 17, 3)
                output = output.squeeze(0).cpu().numpy()  # (243, 17, 3)
                
                # 去掉 padding
                actual_len = end - start
                output = output[:actual_len]  # (actual_len, 17, 3)
                
                all_poses_3d.append(output)
        
        # 合并重叠部分 (取平均)
        poses_3d_17 = self._merge_overlapping(all_poses_3d, T)
        
        # 从 17 关节扩展到 24 关节 (SMPL)
        poses_3d_24 = self._expand_to_24_joints(poses_3d_17)
        
        return poses_3d_24
    
    def _map_to_17_joints(self, kp_33: np.ndarray) -> np.ndarray:
        """MediaPipe 33 → MotionBERT 17 关节映射"""
        # MotionBERT 标准 17 关节: 
        # 0:Hip, 1:RHip, 2:RKnee, 3:RAnkle, 4:LHip, 5:LKnee, 6:LAnkle,
        # 7:Spine, 8:Neck, 9:Head, 10:RShoulder, 11:RElbow, 12:RWrist,
        # 13:LShoulder, 14:LElbow, 15:LWrist, 16:Thorax
        mapping = [23, 24, 26, 28, 25, 27, 0, 12, 0, 11, 13, 15, 12, 14, 16, 0]
        kp_17 = kp_33[:, mapping, :2]  # (T, 17, 2)
        return kp_17
    
    def _normalize(self, kp: np.ndarray) -> np.ndarray:
        """归一化: 减去骨盆中心, 缩放到单位高度"""
        pelvis = (kp[:, 0, :] + kp[:, 0, :]) / 2  # 髋部中心
        kp_centered = kp - pelvis[:, np.newaxis, :]
        # 缩放到约 1.0 的标准身高
        scale = np.linalg.norm(kp[:, 9, :] - kp[:, 0, :], axis=-1).mean()  # 头到髋
        if scale > 0:
            kp_centered /= scale
        return kp_centered
    
    def _merge_overlapping(self, chunks: list[np.ndarray], total_frames: int) -> np.ndarray:
        """合并滑动窗口输出 (重叠区域取平均)"""
        accumulator = np.zeros((total_frames, 17, 3))
        counts = np.zeros((total_frames, 1, 1))
        
        offset = 0
        for chunk in chunks:
            length = chunk.shape[0]
            accumulator[offset:offset+length] += chunk
            counts[offset:offset+length] += 1
            offset += length // 2  # 50% 步进
        
        return accumulator / np.maximum(counts, 1)
    
    def _expand_to_24_joints(self, poses_17: np.ndarray) -> np.ndarray:
        """17 关节 → 24 关节, 通过插值或固定偏移补充缺失关节"""
        # 简化方案: 复制相邻关节
        poses_24 = np.zeros((poses_17.shape[0], 24, 3))
        # 映射 17 → 24 (0-16 直接对应, 17+ 用插值)
        poses_24[:, :17, :] = poses_17
        # 补充缺失关节...
        return poses_24
```

### 6.5 步骤 4.5: Wota 艺特化优化器

**文件: `python/pipeline/wotagei_optimizer.py`**

这是整个 AI 管线中最关键的一步。Wota 艺的动作特征与普通舞蹈完全不同，
需要针对性的后处理。

```python
import numpy as np
from scipy.signal import butter, filtfilt
from scipy.ndimage import gaussian_filter1d
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class KimePoint:
    """卡点 (キメ) 检测结果"""
    frame: int           # 帧索引
    joint: int           # 关节索引
    confidence: float    # 卡点置信度 0~1
    acceleration: float  # 加速度幅值
    
    
class WotageiOptimizer:
    """
    Wota 艺动作特化优化器
    
    核心功能:
    1. 卡点检测 (Kime Detection) — 识别瞬间刹停的关键帧
    2. 关节锁死保护 — 卡点帧附近不做平滑
    3. 速度曲线调整 — 卡点帧应用 Linear tangent
    4. Butterworth 低通滤波 — 去除高频抖动
    5. 关节限制修正 — 防止肘/膝超伸
    """
    
    def __init__(
        self,
        smoothing_cutoff: float = 3.0,     # Hz, 低通截止频率
        kime_accel_threshold: float = 5000.0, # mm/s², 卡点加速度阈值
        kime_protection_window: int = 3,   # 卡点保护窗口 ±N 帧
        sampling_fps: float = 30.0,
    ):
        self.smoothing_cutoff = smoothing_cutoff
        self.kime_accel_threshold = kime_accel_threshold
        self.kime_protection_window = kime_protection_window
        self.fps = sampling_fps
    
    def optimize(
        self,
        poses_3d: np.ndarray,      # (T, 24, 3)
        apply_smoothing: bool = True,
        detect_kime: bool = True,
    ) -> dict:
        """
        完整优化流程
        
        返回:
            {
                "poses": np.ndarray,        # 优化后的姿态
                "kime_points": List[KimePoint],
                "kime_frames": List[int],   # 卡点帧索引 (去重)
            }
        """
        T, J, _ = poses_3d.shape
        poses = poses_3d.copy()
        kime_points = []
        kime_frames = []
        
        # Step 1: 卡点检测
        if detect_kime:
            kime_points = self._detect_kime(poses)
            kime_frames = sorted(set(kp.frame for kp in kime_points))
        
        # Step 2: 带保护的平滑
        if apply_smoothing:
            poses = self._smooth_with_protection(poses, kime_frames)
        
        # Step 3: 关节限制修正
        poses = self._enforce_joint_limits(poses)
        
        # Step 4: 速度曲线调整 (卡点帧用 Linear tangent)
        if detect_kime:
            poses = self._adjust_velocity_curves(poses, kime_frames)
        
        return {
            "poses": poses,
            "kime_points": kime_points,
            "kime_frames": kime_frames,
        }
    
    def _detect_kime(self, poses: np.ndarray) -> List[KimePoint]:
        """
        卡点检测算法
        
        Wota 艺的卡点特征:
        1. 手腕/肘关节在极短时间内 (1-3 帧) 从高速运动变为静止
        2. 根据用户提供的资料: "停止时是瞬间刹车 (零过渡帧)"
        
        算法:
        - 计算每个关节的速度序列 (帧间位移差)
        - 计算加速度 (速度的一阶差分)
        - 找到加速度突变帧 (负加速度极大 → 急刹车)
        """
        T, J, _ = poses.shape
        
        # 重点关注上肢关节: WRISTS, ELBOWS, SHOULDERS
        upper_body_joints = [16, 17, 18, 19, 20, 21]  # shoulders, elbows, wrists
        
        # 计算速度 (mm/s)
        velocity = np.diff(poses, axis=0) * self.fps  # (T-1, J, 3)
        speed = np.linalg.norm(velocity, axis=-1)      # (T-1, J) — 标量速度
        
        # 计算加速度 (mm/s²)
        acceleration = np.diff(speed, axis=0) * self.fps  # (T-2, J)
        
        kime_points = []
        
        for joint_idx in upper_body_joints:
            joint_accel = acceleration[:, joint_idx]  # (T-2,)
            
            # 找到负加速度极值点 (急刹车)
            for t in range(1, len(joint_accel) - 1):
                # 条件 1: 大负加速度 (急减速)
                if joint_accel[t] < -self.kime_accel_threshold:
                    # 条件 2: 之前处于高速状态
                    prev_speed = speed[max(0, t-1), joint_idx]
                    if prev_speed > 500:  # > 500 mm/s (0.5 m/s)
                        # 条件 3: 之后速度极低 (真的停了)
                        next_speed = speed[min(len(speed)-1, t+2), joint_idx]
                        if next_speed < 200:  # < 200 mm/s
                            confidence = min(1.0, abs(joint_accel[t]) / (self.kime_accel_threshold * 3))
                            kime_points.append(KimePoint(
                                frame=t + 1,  # +1 因为 accel 偏移了 1 帧
                                joint=joint_idx,
                                confidence=confidence,
                                acceleration=float(joint_accel[t]),
                            ))
        
        return kime_points
    
    def _smooth_with_protection(
        self, 
        poses: np.ndarray, 
        kime_frames: List[int]
    ) -> np.ndarray:
        """
        带卡点保护的 Butterworth 低通滤波
        
        核心思想:
        - 对每个关节的时间序列应用低通滤波
        - 但卡点帧及其保护窗口内的帧保持原值 (不被平滑)
        - 非保护帧正常滤波
        """
        T, J, _ = poses.shape
        
        # 构建保护掩码
        protection_mask = np.zeros(T, dtype=bool)
        for kf in kime_frames:
            start = max(0, kf - self.kime_protection_window)
            end = min(T, kf + self.kime_protection_window + 1)
            protection_mask[start:end] = True
        
        # 设计 Butterworth 滤波器
        nyquist = self.fps / 2
        cutoff_normalized = self.smoothing_cutoff / nyquist
        if cutoff_normalized >= 1.0:
            cutoff_normalized = 0.99
        b, a = butter(4, cutoff_normalized, btype='low')
        
        smoothed = poses.copy()
        
        for j in range(J):
            for d in range(3):  # x, y, z
                signal = poses[:, j, d].copy()
                
                # 对非保护区域滤波
                if T > 15:  # filtfilt 需要足够长的信号
                    try:
                        filtered = filtfilt(b, a, signal, axis=0)
                        # 只在非保护区域替换
                        for t in range(T):
                            if not protection_mask[t]:
                                smoothed[t, j, d] = filtered[t]
                    except Exception:
                        pass  # 滤波失败则保持原值
        
        return smoothed
    
    def _enforce_joint_limits(self, poses: np.ndarray) -> np.ndarray:
        """
        人体关节限制修正
        
        Wota 艺中常见的关节超伸:
        - 肘关节过伸 (> 180°)
        - 膝关节过伸
        - 手腕超范围旋转
        
        简化实现: 检查父子关节距离是否超出人体比例
        """
        # 上肢骨长比例约束 (相对于身高)
        # 实际实现中需要从 SMPL 模型获取骨长, 这里用硬编码常量
        MAX_ELBOW_ANGLE = np.pi * 0.95  # 171° (略小于 180)
        MAX_KNEE_ANGLE = np.pi * 0.95
        
        # 对每个关节对检查角度...
        # (详细实现省略, 核心是对四元数做钳制)
        
        return poses
    
    def _adjust_velocity_curves(
        self, 
        poses: np.ndarray, 
        kime_frames: List[int]
    ) -> np.ndarray:
        """
        卡点帧速度曲线调整
        
        根据用户提供的资料:
        "曲线平滑度切勿过度平滑, 打艺需要大量线性或阶梯状速度转折"
        "停止时是瞬间刹车 (零过渡帧)"
        
        调整策略:
        - 卡点帧前一帧: 保持速度
        - 卡点帧: 速度归零 (关节锁死)
        - 卡点帧后一帧: 维持静止 (2-3 帧的微停顿)
        """
        adjusted = poses.copy()
        
        for kf in kime_frames:
            if kf < 2 or kf >= len(poses) - 3:
                continue
            
            # 卡点帧: 复制前一帧的姿态 (实现 "零过渡帧" 刹车)
            # 让卡点帧 = 卡点帧-1 (位置不变, 模拟瞬间锁死)
            adjusted[kf] = adjusted[kf - 1].copy()
            
            # 后 2 帧也保持 (微停顿)
            adjusted[kf + 1] = adjusted[kf].copy()
            adjusted[kf + 2] = adjusted[kf].copy()
        
        return adjusted
```

### 6.6 步骤 4.6: 格式导出器

**文件: `python/pipeline/format_exporter.py`**

```python
import json
import uuid
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any


class FormatExporter:
    """
    将 3D 姿态数据转换为内部 MotionData JSON 格式
    """
    
    @staticmethod
    def to_motion_data(
        poses_3d: np.ndarray,           # (T, 24, 3)
        fps: float,
        source_video: str = "",
        kime_frames: list = None,
        skeleton_type: str = "smpl_24",
    ) -> Dict[str, Any]:
        """
        转换为完整的 MotionData JSON 对象
        """
        T = poses_3d.shape[0]
        duration = T / fps
        
        # 将 numpy array 转换为 FramePose 列表
        poses = []
        for t in range(T):
            transforms = {}
            for j in range(poses_3d.shape[1]):
                # 位置 (仅根骨骼有位移)
                position = poses_3d[t, j, :].tolist() if j == 0 else None
                
                # 旋转 — 这里做简化: 从位置推算旋转
                # 实际实现中 MotionBERT 输出的是关节点位置,
                # 需要逆向 IK 或使用 SMPL 模型计算旋转
                # 此处留作后续优化点
                rotation = FormatExporter._estimate_rotation(
                    poses_3d, t, j
                )
                
                transforms[j] = {
                    "rotation": rotation,
                }
                if position:
                    transforms[j]["position"] = position
            
            poses.append({
                "frame": t,
                "transforms": transforms,
            })
        
        # 构建节拍标记 (从卡点帧)
        beat_markers = []
        if kime_frames:
            for kf in kime_frames:
                beat_markers.append({
                    "frame": kf,
                    "beat": "",  # 没有音乐时为空
                    "type": "kime",
                    "label": f"Kime @ frame {kf}",
                })
        
        # 计算运动强度
        velocity = np.diff(poses_3d, axis=0)
        speed = np.linalg.norm(velocity, axis=-1)
        motion_intensity = float(np.mean(speed) / 1000)  # 归一化
        
        now = datetime.now(timezone.utc).isoformat()
        
        return {
            "id": str(uuid.uuid4()),
            "name": f"Captured from {source_video}" if source_video else "Untitled Motion",
            "description": f"AI captured at {fps}fps, {T} frames",
            "tags": ["ai-capture"],
            "fps": fps,
            "duration": duration,
            "frameCount": T,
            "skeletonType": skeleton_type,
            "poses": poses,
            "beatMarkers": beat_markers,
            "keyframeFlags": kime_frames or [],
            "motionIntensity": motion_intensity,
            "primaryJoints": [],  # 统计得出
            "isLoopable": False,  # 需要分析首尾帧相似度
            "source": "ai-capture",
            "sourceVideoPath": source_video,
            "createdAt": now,
            "updatedAt": now,
        }
    
    @staticmethod
    def _estimate_rotation(
        poses: np.ndarray, frame: int, joint: int
    ) -> list:
        """
        从关节位置估算旋转 (简化版)
        
        实际项目中, 更好的做法是:
        - 使用 SMPL 模型逆向求解姿态参数 (θ, β)
        - 或使用 HybrIK 的 IK 求解器
        
        这里用相邻关节方向向量计算简化旋转
        """
        # 使用父关节方向 + 上方向构造旋转矩阵 → 四元数
        # 简化: 返回单位四元数 (后续可替换为真实 IK)
        return [0.0, 0.0, 0.0, 1.0]  # [x, y, z, w]
```

### 6.7 步骤 4.7: Python 进程管理 (Electron 侧)

**文件: `electron/services/python-manager.ts`**

```typescript
import { ChildProcess, spawn } from 'child_process';
import path from 'path';
import { app } from 'electron';
import net from 'net';

class PythonManager {
  private process: ChildProcess | null = null;
  private port: number = 19876;
  private pythonPath: string;
  
  constructor() {
    // 优先级: 打包内嵌 Python > 系统 Python > bundled venv
    this.pythonPath = this.findPython();
  }
  
  private findPython(): string {
    // 1. 检查打包的内嵌 Python
    const bundled = path.join(process.resourcesPath, 'python', 'python.exe');
    if (fs.existsSync(bundled)) return bundled;
    
    // 2. 检查系统 Python
    return 'python'; // 假设在 PATH 中
  }
  
  async start(): Promise<void> {
    if (this.process) return;
    
    const serverPath = path.join(__dirname, '../../python/server.py');
    
    this.process = spawn(this.pythonPath, [
      '-u',  // 无缓冲输出
      serverPath,
      '--port', String(this.port),
    ], {
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    
    this.process.stdout?.on('data', (data) => {
      console.log(`[Python] ${data}`);
    });
    
    this.process.stderr?.on('data', (data) => {
      console.error(`[Python Error] ${data}`);
    });
    
    this.process.on('exit', (code) => {
      console.log(`Python process exited with code ${code}`);
      this.process = null;
      // 异常退出时自动重启
      if (code !== 0) {
        setTimeout(() => this.start(), 3000);
      }
    });
    
    // 等待服务就绪
    await this.waitForReady(30000); // 30s 超时
  }
  
  private async waitForReady(timeoutMs: number): Promise<void> {
    const startTime = Date.now();
    while (Date.now() - startTime < timeoutMs) {
      try {
        const response = await fetch(`http://127.0.0.1:${this.port}/api/health`);
        if (response.ok) return;
      } catch {
        // 服务未就绪
      }
      await new Promise(r => setTimeout(r, 500));
    }
    throw new Error('Python server failed to start within timeout');
  }
  
  async stop(): Promise<void> {
    if (this.process) {
      this.process.kill('SIGTERM');
      // 给 5 秒优雅关闭
      await new Promise(r => setTimeout(r, 5000));
      if (this.process) {
        this.process.kill('SIGKILL');
      }
      this.process = null;
    }
  }
  
  get isRunning(): boolean {
    return this.process !== null && !this.process.killed;
  }
  
  getPort(): number {
    return this.port;
  }
}
```

### 6.8 阶段 4 验证清单

- [ ] 应用启动后 Python 服务自动启动, 健康检查通过
- [ ] 拖入一个 10 秒 Wota 艺短视频 (.mp4)
- [ ] 进度条显示处理进度 (帧提取 → 2D 检测 → 3D 推理 → 优化)
- [ ] 处理完成后动作库自动出现新动作
- [ ] 拖动作到角色 → 播放 → 还原度可接受
- [ ] 卡点标记在时间线上可见
- [ ] 再次导入另一个视频 → 动作库累积
- [ ] 关闭应用 → Python 进程被正确终止

---

## 7. 阶段 5: 时间线编排器

> **目标**: 多轨道拖拽编排, 音乐同步, 多角色协同, 节拍辅助
> **工期**: 3 周
> **依赖**: 阶段 3 (动作数据可播放)、阶段 2 (多角色)

### 7.1 步骤 5.1: 时间线数据模型

**Zustand Store (`src/stores/timelineStore.ts`):**

```typescript
interface TimelineTrack {
  id: string;
  type: 'character' | 'camera' | 'vfx';
  characterId?: string;   // 仅 character 类型
  label: string;
  color: string;          // 轨道颜色
  locked: boolean;
  muted: boolean;         // 静音此轨道 (播放时不渲染此角色)
  clips: TimelineClip[];
}

interface TimelineClip {
  id: string;
  motionId: string;          // 引用 MotionData.id
  motionName: string;        // 冗余存储, 方便显示
  
  // 时间线位置 (秒)
  startTime: number;         // 在时间线上的开始时间
  duration: number;          // 在时间线上的时长
  
  // 动作裁剪
  motionStartFrame: number;  // 从动作的第几帧开始
  motionEndFrame: number;    // 到动作的第几帧结束
  
  // 播放参数
  speed: number;             // 播放速度 (1.0 = 原速)
  loop: boolean;
  
  // 视觉
  color: string;
}

interface TimelineState {
  tracks: TimelineTrack[];
  duration: number;          // 项目总时长 (秒)
  
  // 音频
  audioPath: string | null;
  audioDuration: number;
  beatMarkers: BeatMarker[]; // 全局节拍标记
  
  // Actions — 轨道
  addTrack: (type: TimelineTrack['type'], characterId?: string) => string;
  removeTrack: (trackId: string) => void;
  reorderTracks: (fromIndex: number, toIndex: number) => void;
  
  // Actions — 片段
  addClip: (trackId: string, motionId: string, startTime: number) => string;
  removeClip: (clipId: string) => void;
  moveClip: (clipId: string, newStartTime: number, newTrackId?: string) => void;
  trimClip: (clipId: string, trimStart: number, trimEnd: number) => void;
  splitClip: (clipId: string, splitTime: number) => void;
  
  // Actions — 项目
  setDuration: (duration: number) => void;
  setAudio: (audioPath: string) => void;
  
  // 查询
  getClipsAtTime: (time: number) => { trackId: string; clip: TimelineClip }[];
}
```

### 7.2 步骤 5.2: 时间线 UI 组件

**文件: `src/timeline/TimelineContainer.tsx`**

整体布局:

```
┌──────────────────────────────────────────────────────────────┐
│ [⏮] [⏪] [▶/⏸] [⏩] [⏭]  │ 00:00:12.500 / 00:03:45.000     │
│                           │ [录音] [节拍检测]                 │
├──────────────────────────────────────────────────────────────┤
│ 时间标尺 │ 0s    1s    2s    3s    4s    5s    6s    7s ...  │
│          │ |     |     |     |     |     |     |     |       │
├──────────┼──────────────────────────────────────────────────┤
│ 🔒🔇 🟦 │ Player 1                                          │
│          │  ┌──────────────────┐   ┌─────────────┐          │
│          │  │ Thunder Snake    │   │  Romance    │          │
│          │  └──────────────────┘   └─────────────┘          │
├──────────┼──────────────────────────────────────────────────┤
│ 🔒🔇 🟩 │ Player 2                                          │
│          │       ┌──────────────────────────┐                │
│          │       │       OAD 基础           │                │
│          │       └──────────────────────────┘                │
├──────────┼──────────────────────────────────────────────────┤
│ 🔒🔇 🟨 │ 📷 相机轨道                                       │
│          │            ┌─┐  ┌─┐  ┌─┐                         │
│          │            └─┘  └─┘  └─┘  (关键帧)               │
├──────────┼──────────────────────────────────────────────────┤
│ 🔒🔇 🟪 │ ✨ 特效轨道                                       │
│          │  ┌──────────────────────────────────────┐        │
│          │  │  Bloom 强度变化                        │        │
│          │  └──────────────────────────────────────┘        │
├──────────┴──────────────────────────────────────────────────┤
│ 🎵 音频波形                                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▁▂▃▄▅▆▇█▇▆▅▄▃▂▁  │   │
│  │  ↓     ↓     ↓     ↓     ↓     ↓     ↓     ↓        │   │
│  │ 节拍标记                                              │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

**时间标尺实现要点:**
- Canvas 绘制或纯 DOM
- 支持鼠标滚轮缩放 (改变时间密度)
- 支持拖拽平移
- 主刻度 (秒) + 副刻度 (帧)
- 当前播放头用红色竖线标出

**片段 (ClipItem) 交互:**
- 鼠标拖拽: 左右移动 (改变 startTime)
- 边缘拖拽: 修剪头尾 (trimStart / trimEnd)
- 双击: 分割 (splitClip)
- 右键菜单: 删除 / 复制 / 循环开关 / 速度调整
- 从动作库拖入新建 clip (HTML5 Drag & Drop)

### 7.3 步骤 5.3: 音频集成

```
音频导入流程:
用户点击 "导入音频" → 文件对话框 (.mp3/.wav/.ogg)
       │
       ▼
[Main Process] 读取音频文件 → 返回文件路径 + ArrayBuffer
       │
       ▼
[Renderer]
  ├─→ Web Audio API 解码: audioContext.decodeAudioData(arrayBuffer)
  ├─→ 存储 AudioBuffer 到 playbackStore
  ├─→ 计算波形数据: 逐采样降采样到显示分辨率
  └─→ 绘制 WaveformView
```

**节拍检测:**

方案 A (纯前端): 使用 `web-audio-beat-detector` 库, 基于 Web Audio API 的 onset detection
方案 B (Python): 使用 `aubio` 或 `librosa` 做更精确的节拍跟踪

推荐先实现方案 A 做快速反馈, 方案 B 做高精度离线分析。

**节拍标记在时间线上的交互:**
- 自动检测的节拍用半透明竖线 + 小圆点标记
- 用户可手动添加/删除/移动节拍标记
- 拖拽 clip 时自动吸附到最近的节拍标记 (Snap to Beat)

### 7.4 步骤 5.4: 播放同步引擎

**文件: `src/stores/playbackStore.ts`**

```typescript
interface PlaybackState {
  status: 'stopped' | 'playing' | 'paused';
  currentTime: number;       // 秒
  speed: number;             // 播放速度倍率
  
  // 音频
  audioBuffer: AudioBuffer | null;
  audioSource: AudioBufferSourceNode | null;
  audioContext: AudioContext;
  
  // Actions
  play: () => void;
  pause: () => void;
  stop: () => void;
  seek: (time: number) => void;
  setSpeed: (speed: number) => void;
}

// 播放循环 (在 Babylon.js 的 scene.registerBeforeRender 中注册)
function playbackLoop() {
  const state = usePlaybackStore.getState();
  if (state.status !== 'playing') return;
  
  // 增量时间 (考虑播放速度)
  const deltaTime = engine.getDeltaTime() / 1000 * state.speed;
  const newTime = state.currentTime + deltaTime;
  
  // 边界检查
  const totalDuration = useTimelineStore.getState().duration;
  if (newTime >= totalDuration) {
    state.stop();
    return;
  }
  
  // 更新时间
  state.currentTime = newTime;
  
  // 查询当前时间所有轨道的活跃 clips
  const activeClips = useTimelineStore.getState().getClipsAtTime(newTime);
  
  // 驱动每个角色的 MotionPlayer
  for (const { trackId, clip } of activeClips) {
    const track = useTimelineStore.getState().tracks.find(t => t.id === trackId);
    if (!track || track.muted) continue;
    
    const player = getMotionPlayerForCharacter(track.characterId);
    const localTime = newTime - clip.startTime;
    const motionFrame = clip.motionStartFrame + localTime * clip.motionData.fps * clip.speed;
    
    player.seekToFrame(motionFrame);
  }
  
  // 同步音频 (如果音频正在播放):
  // Web Audio API 的 AudioContext.currentTime 是绝对时间,
  // 需要校准偏移量来同步
}
```

**音频同步策略:**

Web Audio API 使用硬件时钟 `AudioContext.currentTime`。
播放时记录 `startOffset = audioContext.currentTime - timelineTime`。
每帧检查 `audioContext.currentTime - startOffset` 是否等于预期的 timeline 时间。
如果偏差超过阈值 (±50ms), 微调音频播放速率 (playbackRate 0.99~1.01) 做补偿。

### 7.5 阶段 5 验证清单

- [ ] 从动作库拖拽 clip 到角色轨道 → clip 可视化出现在时间线上
- [ ] 在时间线上拖拽移动 clip → 播放时动作位置变化
- [ ] 修剪 clip 头尾 → 只播放裁剪后的部分
- [ ] 添加第二个角色轨道 → 分别拖不同动作
- [ ] 导入音乐 → 波形显示
- [ ] 节拍检测 → 自动标记出现在波形图上方
- [ ] 点击播放 → 两个角色同步跳舞 + 音乐播放
- [ ] 拖拽播放头 → 角色跳到对应帧
- [ ] 空格键 → 播放/暂停切换

---

## 8. 阶段 6: VFX 荧光棒特效

> **目标**: 角色手持荧光棒, 运动产生发光拖尾, 暗环境 Bloom, 还原打艺视觉
> **工期**: 2-3 周
> **依赖**: 阶段 2 (角色骨骼)、阶段 3 (动作播放)

### 8.1 步骤 8.1: 荧光棒模型与材质

**文件: `src/vfx/GlowstickVFX.ts`**

```typescript
class GlowstickVFX {
  private scene: Scene;
  
  // 每根荧光棒的组成:
  // - stickMesh: 圆柱体 (荧光棒本体)
  // - glowMesh: 稍大的透明圆柱 (光晕层)
  // - pointLight: 点光源 (对角色产生实时光照)
  // - trailRenderer: 拖尾渲染器
  
  struct GlowstickInstance {
    stickMesh: Mesh;
    glowMesh: Mesh;
    pointLight: PointLight;
    trailRenderer: TrailRenderer;
    // 配置
    color: Color3;
    intensity: number;      // 发光强度
    size: number;           // 长度 (默认 25cm)
    radius: number;         // 半径 (默认 1.5cm)
  }
  
  // 每个角色 2~4 根荧光棒
  private characterGlowsticks: Map<string, GlowstickInstance[]>;
  
  constructor(scene: Scene);
  
  /**
   * 为角色创建荧光棒
   * @param characterId - 角色 ID
   * @param config - 荧光棒配置
   */
  createForCharacter(characterId: string, config: GlowstickConfig): void {
    const instances: GlowstickInstance[] = [];
    
    // 右手荧光棒
    instances.push(this.createGlowstick(
      characterId, 
      SkeletonJoint.RIGHT_HAND,
      config.rightHand
    ));
    
    // 左手荧光棒
    instances.push(this.createGlowstick(
      characterId,
      SkeletonJoint.LEFT_HAND,
      config.leftHand
    ));
    
    // 可选: 每手双持 (Wota 艺常见)
    if (config.doubleWield) {
      instances.push(this.createGlowstick(
        characterId,
        SkeletonJoint.RIGHT_HAND,
        { ...config.rightHand, offsetAngle: 15 } // 偏移 15°
      ));
      // ... 左手同理
    }
    
    this.characterGlowsticks.set(characterId, instances);
  }
  
  private createGlowstick(
    characterId: string,
    bindJoint: SkeletonJoint,
    options: GlowstickOptions
  ): GlowstickInstance {
    // 1. 创建荧光棒几何体
    const stickMesh = MeshBuilder.CreateCylinder(
      `glowstick_${characterId}_${bindJoint}`,
      {
        height: options.length,   // 默认 0.25m (25cm)
        diameter: options.radius * 2, // 默认 0.03m (3cm)
      },
      this.scene
    );
    
    // 2. PBR 材质 — 自发光为主
    const material = new PBRMaterial(`glowstickMat_${characterId}`, this.scene);
    material.albedoColor = options.color;          // 基础色
    material.emissiveColor = options.color.scale(options.intensity); // 自发光 (HDR >1.0)
    material.metallic = 0.1;
    material.roughness = 0.3;
    material.alpha = 0.95;  // 微透明让光晕更柔和
    stickMesh.material = material;
    
    // 3. 光晕层 (Glow Layer)
    // Babylon.js 的 GlowLayer 会自动处理 emissive > 1 的部分
    // 无需额外创建光晕 mesh
    
    // 4. 点光源 (小范围, 照射角色身体)
    const pointLight = new PointLight(
      `glowLight_${characterId}_${bindJoint}`,
      Vector3.Zero(),
      this.scene
    );
    pointLight.diffuse = options.color;
    pointLight.intensity = options.lightIntensity;  // 默认 0.5
    pointLight.range = 1.5;  // 仅照射 1.5m 范围
    
    // 5. 绑定到骨骼
    // 在 update 循环中读取骨骼世界坐标, 更新荧光棒位置
    
    return { stickMesh, glowMesh: null as any, pointLight, trailRenderer: null as any, ... };
  }
  
  /**
   * 每帧更新: 将从骨骼的世界变换应用到荧光棒
   */
  update(character: CharacterModel): void {
    const instances = this.characterGlowsticks.get(character.id);
    if (!instances) return;
    
    for (const instance of instances) {
      const jointPos = character.getJointWorldPosition(instance.bindJoint);
      const jointRot = character.getJointWorldRotation(instance.bindJoint);
      
      instance.stickMesh.position.copyFrom(jointPos);
      instance.stickMesh.rotationQuaternion = jointRot;
      
      instance.pointLight.position.copyFrom(jointPos);
      
      // 更新拖尾
      instance.trailRenderer?.addPoint(jointPos, this.scene);
    }
  }
}
```

### 8.2 步骤 8.2: 光轨拖尾渲染器

**文件: `src/vfx/TrailRenderer.ts`**

```typescript
/**
 * 光轨拖尾渲染器 (Ribbon-based Trail)
 * 
 * Wota 艺视觉特征:
 * - 高速运动时残影长 → 形成光圈
 * - 卡点定格时残影迅速收敛
 * - 轨迹颜色从荧光色渐变到透明
 */

class TrailRenderer {
  private points: Vector3[] = [];       // 历史位置点
  private maxPoints: number = 120;      // 最大点数 (4秒 @ 30fps)
  private ribbon: Mesh | null = null;
  private material: StandardMaterial;
  
  // 动态参数
  private baseLifetime: number = 2.0;   // 基础残影时间 (秒)
  private speedScaleFactor: number = 0.05; // 速度→残影长度缩放
  
  constructor(private scene: Scene, private color: Color3) {
    this.material = new StandardMaterial("trailMat", scene);
    this.material.emissiveColor = color;
    this.material.diffuseColor = Color3.Black();
    this.material.specularColor = Color3.Black();
    this.material.alpha = 0.9;
    this.material.backFaceCulling = false;  // 双面渲染
  }
  
  /**
   * 添加新位置点 (每帧调用)
   */
  addPoint(position: Vector3): void {
    this.points.push(position.clone());
    
    // 计算当前速度, 动态调整保留点数
    const speed = this.calculateSpeed();
    const dynamicLifetime = this.baseLifetime + speed * this.speedScaleFactor;
    const maxFrames = Math.floor(dynamicLifetime * 60);  // 假设 60fps
    const actualMax = Math.min(maxFrames, 180);  // 上限 3 秒
    
    // 淘汰过期点
    while (this.points.length > actualMax) {
      this.points.shift();
    }
    
    // 重建 Ribbon
    this.rebuildRibbon();
  }
  
  private calculateSpeed(): number {
    if (this.points.length < 2) return 0;
    const last = this.points[this.points.length - 1];
    const prev = this.points[this.points.length - 2];
    return Vector3.Distance(last, prev) * 60;  // m/s (假设 60fps)
  }
  
  private rebuildRibbon(): void {
    if (this.points.length < 2) return;
    
    // 移除旧 Ribbon
    if (this.ribbon) {
      this.ribbon.dispose();
    }
    
    // Ribbon 几何体: 沿路径的带状网格
    const path = this.points;
    const ribbonWidth = 0.02;  // 2cm 宽 (荧光棒直径)
    
    // 使用 Babylon.js 的 RibbonBuilder
    // 或者自定义顶点缓冲:
    // - 每对相邻点 → 2 个顶点 (左/右偏移)
    // - 顶点颜色从 color → transparent (Alpha 渐变)
    
    const positions: number[] = [];
    const colors: number[] = [];
    const indices: number[] = [];
    
    for (let i = 0; i < path.length - 1; i++) {
      const p0 = path[i];
      const p1 = path[i + 1];
      
      // 计算垂直于运动方向的偏移向量
      const dir = p1.subtract(p0).normalize();
      const perp = Vector3.Cross(dir, Vector3.Up()).normalize().scale(ribbonWidth / 2);
      
      // Alpha 从旧(透明)到新(不透明)
      const alpha = i / (path.length - 1);  // 0 → 1
      const fadeAlpha = Math.pow(alpha, 2);  // 二次衰减, 尾部更透
      
      // 添加两个顶点
      const v0 = p0.add(perp);
      const v1 = p0.subtract(perp);
      positions.push(v0.x, v0.y, v0.z, v1.x, v1.y, v1.z);
      
      colors.push(
        this.color.r, this.color.g, this.color.b, fadeAlpha,
        this.color.r, this.color.g, this.color.b, fadeAlpha
      );
    }
    
    // 创建三角索引
    for (let i = 0; i < path.length - 2; i++) {
      const a = i * 2;
      const b = a + 1;
      const c = a + 2;
      const d = a + 3;
      indices.push(a, b, c);  // 三角 1
      indices.push(b, d, c);  // 三角 2
    }
    
    // 创建 Mesh
    const vertexData = new VertexData();
    vertexData.positions = positions;
    vertexData.colors = colors;
    vertexData.indices = indices;
    
    this.ribbon = new Mesh("trailRibbon", this.scene);
    vertexData.applyToMesh(this.ribbon);
    this.ribbon.material = this.material;
    this.ribbon.hasVertexAlpha = true;  // 启用顶点 Alpha
  }
  
  /**
   * 清除所有拖尾 (卡点时调用)
   */
  clearRapidly(): void {
    // 快速衰减: 只保留最后 3 个点
    this.points = this.points.slice(-3);
    this.rebuildRibbon();
  }
  
  dispose(): void {
    this.ribbon?.dispose();
    this.material.dispose();
  }
}
```

### 8.3 步骤 8.3: GPU 粒子拖尾 (备选/增强方案)

当场景中有多个角色 × 多根荧光棒时，每个 Ribbon 都有几百个顶点，
总计可能达到数万顶点。如果性能吃紧，可用 GPU 粒子系统替代:

```typescript
class ParticleTrail {
  private particleSystem: GPUParticleSystem;
  
  constructor(scene: Scene, color: Color3) {
    this.particleSystem = new GPUParticleSystem(
      "glowstickTrail",
      { capacity: 500 },  // 最多 500 个粒子
      scene
    );
    
    // 粒子纹理: 小圆形光点
    this.particleSystem.particleTexture = new Texture("textures/glow_dot.png", scene);
    
    // 发射器位置由手掌骨骼驱动 (每帧更新)
    this.particleSystem.emitter = Vector3.Zero();  // 将在 update 中动态设置
    
    // 粒子生命周期
    this.particleSystem.minLifeTime = 0.1;
    this.particleSystem.maxLifeTime = 1.5;  // 最长 1.5 秒残影
    
    // 颜色渐变
    this.particleSystem.addColorGradient(0.0, new Color4(color.r, color.g, color.b, 1.0));
    this.particleSystem.addColorGradient(0.5, new Color4(color.r, color.g, color.b, 0.6));
    this.particleSystem.addColorGradient(1.0, new Color4(color.r, color.g, color.b, 0.0));
    
    // 大小渐变
    this.particleSystem.addSizeGradient(0.0, 0.05);
    this.particleSystem.addSizeGradient(1.0, 0.01);
    
    // 发射率 (根据运动速度动态调整)
    this.particleSystem.emitRate = 100;
    
    // 初始速度几乎为零 (粒子遗留在空间)
    this.particleSystem.minInitialRotation = 0;
    this.particleSystem.maxInitialRotation = Math.PI * 2;
    
    this.particleSystem.start();
  }
  
  update(handPosition: Vector3, speed: number): void {
    // 更新发射器位置
    this.particleSystem.emitter = handPosition;
    
    // 动态调整发射率: 速度快 → 更多粒子
    this.particleSystem.emitRate = 30 + speed * 10;
    
    // 动态调整生命周期: 速度快 → 更长残影
    const dynamicLifetime = 0.3 + speed * 0.05;
    this.particleSystem.maxLifeTime = Math.min(dynamicLifetime, 2.0);
  }
}
```

### 8.4 步骤 8.4: 后处理管线

**文件: `src/vfx/PostProcessing.ts`**

```typescript
class PostProcessingStack {
  private pipeline: DefaultRenderingPipeline;
  
  constructor(scene: Scene, camera: Camera) {
    // Babylon.js DefaultRenderingPipeline 一键集成
    this.pipeline = new DefaultRenderingPipeline(
      "postProcess",
      true,   // hdr
      scene,
      [camera]
    );
    
    // ===== Bloom (泛光) — 最重要 =====
    this.pipeline.bloomEnabled = true;
    this.pipeline.bloomThreshold = 0.6;    // 阈值: 只有高亮区域产生 Bloom
    this.pipeline.bloomWeight = 0.8;       // Bloom 强度
    this.pipeline.bloomKernel = 64;        // 模糊核大小 (大 = 更柔光)
    this.pipeline.bloomScale = 0.5;        // Bloom 缩放
    
    // ===== 色彩分级 =====
    this.pipeline.imageProcessingEnabled = true;
    this.pipeline.imageProcessing.colorGradingEnabled = true;
    // 加载 LUT 纹理 (暗环境调色)
    // this.pipeline.imageProcessing.colorGradingTexture = ...
    
    // 手动调整:
    this.pipeline.imageProcessing.exposure = 1.2;    // 稍增曝光
    this.pipeline.imageProcessing.contrast = 1.15;    // 增强对比度
    this.pipeline.imageProcessing.vignetteEnabled = true;
    this.pipeline.imageProcessing.vignetteWeight = 0.5;  // 暗角强度
    this.pipeline.imageProcessing.vignetteColor = new Color4(0, 0, 0, 0);
    
    // ===== 景深 (浅, 用于聚焦角色) =====
    this.pipeline.depthOfFieldEnabled = false;  // 默认关闭, 可选开启
    this.pipeline.depthOfField.focusDistance = 500;  // 对焦距离
    this.pipeline.depthOfField.fStop = 1.4;
    
    // ===== 锐化 =====
    this.pipeline.sharpenEnabled = true;
    this.pipeline.sharpen.edgeAmount = 0.15;
  }
  
  /**
   * 卡点瞬间增强 Bloom (视觉冲击)
   */
  triggerKimeEffect(): void {
    // 临时增强 Bloom
    this.pipeline.bloomWeight = 1.5;
    // 0.3 秒后恢复
    setTimeout(() => {
      this.pipeline.bloomWeight = 0.8;
    }, 300);
  }
}
```

### 8.5 阶段 6 验证清单

- [ ] 角色播放动作时手上有发光荧光棒
- [ ] 荧光棒颜色可在面板中切换 (红/蓝/绿/白/橙等)
- [ ] 运动轨迹可见发光残影 (Ribbon 或粒子)
- [ ] 快速挥舞 → 长残影 (光圈感)
- [ ] 突然停顿 → 残影迅速收敛
- [ ] 暗环境场景中 Bloom 效果明显 (荧光棒"亮起来")
- [ ] 荧光棒对角色身体产生微弱彩色光照
- [ ] 调面板参数 (亮度/颜色/根数) → 实时生效
- [ ] 3 个角色同时播放 → 不卡顿 (≥30fps)

---

## 9. 阶段 7: 打磨与导出

> **目标**: 项目持久化、视频导出、动作交换、UI 打磨
> **工期**: 2 周
> **依赖**: 阶段 5 (时间线)、阶段 6 (VFX)

### 9.1 步骤 9.1: 项目文件系统

**项目文件格式 (`.tmonkey`) — 实际为 JSON + 资源引用:**

```typescript
interface ProjectFile {
  version: string;           // "1.0.0"
  metadata: {
    name: string;
    created: string;
    updated: string;
    author: string;
    description?: string;
  };
  
  // 四层数据引用
  stage: StageConfig;
  lighting: LightConfig;
  
  characters: CharacterConfig[];  // 配置, 不含 Mesh 数据
  // 模型文件通过相对路径引用
  
  timeline: {
    duration: number;
    tracks: TimelineTrack[];
  };
  
  vfx: VFXConfig;
  
  // 音频引用
  audioPath?: string;  // 相对路径
  
  // 项目包含的 MotionData (内嵌, 因为 SQLite 存储的 JSON 已完整)
  // 或者仅引用 motionId, 运行时从 SQLite 查询
  motionRefs: string[];  // motionId 列表
}
```

**保存流程:**
```
用户 Ctrl+S / 菜单 → 保存
  │
  ▼
[Renderer] 收集所有 Store 状态 → 序列化为 ProjectFile JSON
  │
  ▼ IPC: 'project:save'
[Main] 弹出文件保存对话框 → 写入 .tmonkey 文件
  │
  ▼
[Main] 同时写入 SQLite projects 表 (自动备份)
```

**自动保存:**
- 每 5 分钟自动保存到 `userData/autosave.tmonkey`
- 崩溃恢复时检测 autosave 文件

### 9.2 步骤 9.2: 视频导出

```
导出流程:
用户点击 "导出视频" → 配置分辨率/FPS/编码
  │
  ▼
方案 A (推荐): 逐帧离屏渲染 + ffmpeg 合成
  │
  ├─→ Babylon.js 切换到离屏渲染模式
  │     engine.render() → readPixels() → PNG Buffer
  │
  ├─→ 逐帧: seek 时间线 → 渲染 → 保存 PNG 到临时目录
  │     帧数 = duration × fps (例: 3分钟 × 30fps = 5400 帧)
  │
  └─→ 调用 ffmpeg 合成:
       ffmpeg -framerate 30 -i frame_%05d.png 
              -i audio.mp3 -c:v libx264 -pix_fmt yuv420p 
              -c:a aac output.mp4
```

**性能优化:**
- 渲染分辨率可低于工作分辨率 (如 1080p 导出, 工作时 720p 视口)
- 使用 Worker 线程并行合成
- 显示进度条 "渲染中... 245/5400 帧"

### 9.3 步骤 9.3: 动作数据导出

**glTF 2.0 导出 (通过 Python):**

```python
# python/pipeline/format_exporter.py 补充

@staticmethod
def export_to_gltf(motion_data: dict, output_path: str):
    """
    将内部 MotionData 导出为 glTF 2.0 动画
    
    glTF 动画结构:
    - animation.samplers: 每个关节一个 sampler (时间 + 值)
    - animation.channels: sampler → 目标节点/路径 的映射
    """
    import pygltflib
    
    gltf = pygltflib.GLTF2()
    
    # 创建骨骼节点层级
    nodes = []
    for joint_idx in range(24):
        node = pygltflib.Node()
        node.name = f"joint_{joint_idx}"
        # ... 设置层级
    
    # 创建动画
    animation = pygltflib.Animation()
    animation.name = motion_data["name"]
    
    for joint_idx in range(24):
        # 收集该关节所有帧的旋转和时间
        times = []
        rotations = []
        for pose in motion_data["poses"]:
            t = pose["frame"] / motion_data["fps"]
            rot = pose["transforms"][str(joint_idx)]["rotation"]
            times.append(t)
            rotations.extend(rot)  # [x, y, z, w]
        
        sampler = pygltflib.AnimationSampler(
            input=gltf._add_accessor(times, "SCALAR"),
            output=gltf._add_accessor(rotations, "VEC4"),
            interpolation="LINEAR",
        )
        
        channel = pygltflib.AnimationChannel(
            sampler=len(animation.samplers),
            target=pygltflib.AnimationChannelTarget(
                node=nodes[joint_idx],
                path="rotation",
            ),
        )
        
        animation.samplers.append(sampler)
        animation.channels.append(channel)
    
    gltf.animations.append(animation)
    gltf.save(output_path)
```

**BVH 导出:**
BVH 格式简单(文本), 可直接按模板生成, 无需第三方库。

### 9.4 步骤 9.4: 骨骼重定向

**文件: `src/character/Retargeter.ts`**

```typescript
/**
 * 骨骼重定向器
 * 
 * 解决问题: 用户导入的自定义模型骨架可能与标准 SMPL 24 关节不同
 * 
 * 策略:
 * 1. 用户提供映射表 (Custom Joint → Standard Joint)
 * 2. 运行时将标准动作的关节旋转转换为目标骨架的旋转
 * 3. 支持 T-Pose 差异补偿
 */

class Retargeter {
  /**
   * 将标准骨架的动作重定向到目标骨架
   * 
   * @param sourceMotion - SMPL 24 标准动作
   * @param targetSkeleton - 目标角色的骨骼
   * @param jointMap - 标准关节 → 目标关节名称映射
   * @param restPoseOffset - T-Pose 差异补偿旋转
   */
  static retarget(
    sourceMotion: MotionData,
    targetSkeleton: Skeleton,
    jointMap: Map<SkeletonJoint, string>,
    restPoseOffset: Map<SkeletonJoint, Quaternion>
  ): MotionData {
    const retargetedPoses: FramePose[] = [];
    
    for (const srcPose of sourceMotion.poses) {
      const tgtPose: FramePose = { frame: srcPose.frame, transforms: {} };
      
      for (const [srcJoint, tgtBoneName] of jointMap) {
        const srcTransform = srcPose.transforms[srcJoint];
        if (!srcTransform) continue;
        
        const srcRot = Quaternion.FromArray(srcTransform.rotation);
        
        // 补偿 T-Pose 差异
        const offset = restPoseOffset.get(srcJoint) || Quaternion.Identity();
        const tgtRot = offset.multiply(srcRot).multiply(Quaternion.Inverse(offset));
        
        // 找到目标骨骼索引
        const tgtBoneIndex = targetSkeleton.bones.findIndex(
          b => b.name === tgtBoneName
        );
        
        if (tgtBoneIndex >= 0) {
          tgtPose.transforms[tgtBoneIndex] = {
            rotation: [tgtRot.x, tgtRot.y, tgtRot.z, tgtRot.w],
          };
        }
      }
      
      retargetedPoses.push(tgtPose);
    }
    
    return {
      ...sourceMotion,
      id: uuid(),
      poses: retargetedPoses,
      name: `${sourceMotion.name} (retargeted)`,
    };
  }
}
```

### 9.5 步骤 9.5: UI 打磨

- **快捷键系统**: 全局注册键盘事件, 通过 Zustand 的 subscribe 分发
  - 空格: 播放/暂停
  - Delete: 删除选中 clip
  - Ctrl+Z / Ctrl+Y: 撤销/重做 (时间线操作)
  - Ctrl+S: 保存项目
  - Ctrl+I: 导入视频
  - 1/2/3: 切换选中角色
- **右键菜单**: 场景中右键角色 → 配置/删除/复制
- **工具提示**: 悬停按钮时显示快捷键
- **状态栏**: 显示 FPS / 当前选中对象 / Python 服务状态
- **错误边界**: React ErrorBoundary 包裹关键组件, 防止白屏
- **日志系统**: 前端用 console + 自定义 logger, 主进程用 winston

### 9.6 阶段 7 验证清单

- [ ] Ctrl+S → 保存项目 → 关闭 → 重新打开 → 加载 → 一切还原
- [ ] 导出视频 → 等待渲染 → 打开 .mp4 → 画面正确 + 音频同步
- [ ] 导出 glTF → 导入 Blender → 骨骼动画可播放
- [ ] 导入自定义 .glb 角色 → 映射骨骼 → 播放标准动作
- [ ] 快捷键全部生效
- [ ] 撤销/重做正常工作
- [ ] 连续使用 30 分钟不崩溃/不内存泄漏

---

## 10. 附录

### 10.1 Wota 艺核心招式数据模板

预置在动作库中的参考动作结构 (手动创建, 用于测试和演示):

| 招式名 | 时长 | 帧数 | 核心关节 | 特征 |
|--------|------|------|---------|------|
| Thunder Snake | 8s | 240 | 双手腕、双肘、肩 | 之字形折线 + 大回环 |
| Romance | 4s | 120 | 右腕、脊椎 | 斜向直线往复 |
| OAD | 3s | 90 | 双手腕、脊椎 | 圆弧劈砍 + 击掌定格 |

### 10.2 荧光棒物理参数参考

| 参数 | 值 | 说明 |
|------|-----|------|
| 长度 | 25cm | 标准 Cyalume 大闪长度 |
| 直径 | 3cm | 含手柄 |
| 发光色 | 高亮绿/蓝/橙/白 | Wota 艺常用色 |
| 高亮寿命 | 30~120秒 | 实际荧光棒衰减曲线 |
| 每手数量 | 1~2根 | 单持/双持 |

### 10.3 后续迭代方向 (不在本期范围)

1. **实时摄像头动捕** — WebRTC 接入摄像头 + MediaPipe 实时推理
2. **AI 自动编舞** — 给定音乐, 从动作库自动拼接编排
3. **社区动作市场** — 云端共享动作库
4. **VR 预览模式** — WebXR 在 VR 头显中观看
5. **物理模拟** — 衣物/头发动力学, 增强真实感
6. **多人实时协作** — WebSocket 同步编辑

### 10.4 关键开源协议确认

| 组件 | 协议 | 商用限制 |
|------|------|---------|
| Babylon.js | Apache 2.0 | ✅ 无限制 |
| Electron | MIT | ✅ 无限制 |
| React | MIT | ✅ 无限制 |
| MediaPipe | Apache 2.0 | ✅ 无限制 |
| MotionBERT | Apache 2.0 | ✅ 无限制 |
| better-sqlite3 | MIT | ✅ 无限制 |
| Zustand | MIT | ✅ 无限制 |
| FastAPI | MIT | ✅ 无限制 |
| scipy | BSD | ✅ 无限制 |

> ⚠️ **注意**: 如将来使用 SMPL 人体模型 (通过 4D-Humans/HybrIK), 
> SMPL 本体需从 MPI 注册获取, 且仅限研究用途, 商业使用需单独许可。
> 当前方案使用 MediaPipe BlazePose + MotionBERT 纯骨架推理, 不依赖 SMPL。