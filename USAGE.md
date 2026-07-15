# Torch Monkey 使用文档

> Wota-艺（ヲタ芸 / wotagei）3D 编排与可视化软件 · 把表演视频变成 3D 动作，在舞台上编排、预览。
> 版本 0.6.0 · 2026-07-15

> **0.6.0 更新（进入实机测试）**
> - 🎚 **舞台灯光**：修复首屏全白、触碰后变黑、滑块无反应的问题——环境光 / 背光 / 聚光灯滑块现在即时生效，且不再每动一下就重建阴影。
> - 🧍 **视口拖拽**：表演者可直接在 3D 视口里左键拖动身体调整站位，右侧 X/Z 滑块同步联动。
> - 🧍 **穿模修复**：新增表演者不再叠在同一点，按最小间距自动排开。
> - 🎯 **时间线磁吸 🧲**：拖拽 / 落子时片段自动吸附到相邻片段边缘、播放头、起点，做到严丝合缝。
> - 🎬 **每角色独立轨道**：每个表演者都有可编辑的轨道（不再只能编辑 1 号）。
> - 🧍 **缓慢复位**：进度条里没有动作覆盖到的表演者会缓慢回到待机姿态（不再倒放或定在半空）。
> - 🧍 **复位站姿**：双腿张开（两脚 2 倍肩宽）、双臂平举的标准待机姿态。

关键名词的日语/英语对照统一放在[§7.2 术语表](#72-术语对照表)，正文不再逐词标注，保证步骤干净易读。

---

## 目录

0. [你是谁、该读哪一节（先看这个）](#0-你是谁该读哪一节先看这个)
1. [两台电脑怎么分工（心智模型）](#1-两台电脑怎么分工心智模型)
2. [Linux 服务器：从零环境到起服务（手把手）](#2-linux-服务器从零环境到起服务手把手)
3. [把两台电脑连起来（SSH 隧道 / 局域网 / 测试连接）](#3-把两台电脑连起来ssh-隧道--局域网--测试连接)
4. [Windows 客户端 / 浏览器：安装与运行](#4-windows-客户端--浏览器安装与运行)
5. [日常使用（舞台 / 角色 / 动作库 / 时间线 / 特效 / B 站动捕）](#5-日常使用)
6. [排错 FAQ（出问题先看这里）](#6-排错-faq出问题先看这里)
7. [进阶：架构总览 / 术语表 / AI 管线与准确率](#7-进阶架构总览--术语表--ai-管线与准确率)

---

## 0. 你是谁、该读哪一节（先看这个）

**它到底是什么？** Torch Monkey 做两件事：① 把一段 Wota-艺表演**视频**用 AI 提取出 **3D 动作**；② 让你在可自定义的 **3D 舞台**上把这些动作编排起来、配上音乐预览，像虚拟演唱会。AI 计算（动作重建）可以跑在有 GPU 的机器上加速，**查看/编排在另一台机器上**。

**我用哪种方式查看？** 两种"查看端"，任选其一，都能看到完整界面：

- **桌面 App**（Windows，功能最全，键鼠快捷键齐全）
- **浏览器**（任意系统，开网页即看，**特别适合"服务器在远端 Linux、我在 Windows 看"**）

**按你的情况选入口：**

| 你的情况 | 直接看 |
|---|---|
| 我想最快看到效果，全程就一台 Windows 电脑 | [§4](#4-windows-客户端--浏览器安装与运行)（桌面 App 或浏览器都行） |
| 我有一台 **Linux GPU 服务器**，想在它上面加速重建，在 **Windows** 上看 | [§1](#1-两台电脑怎么分工心智模型) → [§2](#2-linux-服务器从零环境到起服务手把手) → [§3](#3-把两台电脑连起来ssh-隧道--局域网--测试连接) → [§4](#4-windows-客户端--浏览器安装与运行) |
| 我用着用着**出问题了** | [§6 排错 FAQ](#6-排错-faq出问题先看这里) |
| 我想了解**原理 / 术语 / 数据格式** | [§7 进阶](#7-进阶架构总览--术语表--ai-管线与准确率) |

> 全程只要记住一句话：**"重建"（AI 算动作）归服务器；"查看/编排"归你的电脑。** 下面反复用到。

---

## 1. 两台电脑怎么分工（心智模型）

无论你用桌面 App 还是浏览器，Torch Monkey 都分成两部分：

```
        ┌─────────────────────────┐         ┌──────────────────────────┐
        │  你的电脑（查看/编排）    │  网络    │  Python AI 服务器（重建）  │
        │  · 桌面 App 或 浏览器    │ ──────▶ │  · 把视频/BV 号算成 3D 动作 │
        │  · 3D 舞台、时间线、特效  │ ◀────── │  · 有 GPU 就快（CUDA）     │
        └─────────────────────────┘  动作回传 └──────────────────────────┘
```

- **服务器（`python/server.py`）**：只干一件苦力活——把视频算成动作。它**不需要**键盘鼠标显示器，丢在有 GPU 的机器上跑就行。
- **查看端**：你操作的界面（舞台、动作库、时间线）。桌面 App 和浏览器是**同一个界面**，只是运行方式不同。

**两种典型摆法：**

- **摆法 ①：全在一台 Windows 上（本地）。** 服务器和查看端跑在同一台电脑。最简单，没 GPU 也能跑（CPU 慢些）。见 [§4](#4-windows-客户端--浏览器安装与运行)。
- **摆法 ②：Linux GPU 跑服务器 + Windows 跑查看端（推荐有远端 GPU 时）。** 这就是用户最常问的"在服务器上加速重建、在 Windows 上看"。需要 [§2](#2-linux-服务器从零环境到起服务手把手) 装服务器 + [§3](#3-把两台电脑连起来ssh-隧道--局域网--测试连接) 连起来。

**数据怎么流：** 你在查看端选一个视频（或填一个 B 站 BV 号）→ 查看端把它发给服务器 → 服务器算出动作 → 动作回到查看端的"动作库" → 你把它拖到时间线、在舞台上播放/编排。视频文件不会被服务器留存（处理完就删）。

> 一个常见误解：**"查看端"不是只能用浏览器。** 桌面 App 和浏览器都能查看/编排；浏览器版是后期新增的，专为"我不想在 Windows 上装一堆东西、只想开个网页看远端 GPU 的结果"这种场景。两种查看端连的是**同一个服务器**。

---

## 2. Linux 服务器：从零环境到起服务（手把手）

> 这一节假设你**第一次**在这台 Linux 上弄。每条命令后面都写了"它干什么"和"下一步"。服务器**长期运行只需要 Python**；Node 只在"构建网页端"那一步用一次（见 [§4.2](#42-浏览器开网页即看推荐远端场景)），构建完就不用了。
>
> 前提：你有一台 Linux 服务器（实验室/云主机都行），并知道怎么用 **SSH** 登录它（即知道它的 **IP 地址、用户名、密码或密钥**）。SSH 就是"在另一台电脑上开个终端"的工具，Windows 10/11 自带，直接在"命令提示符"或"PowerShell"里敲 `ssh` 即可。

### 2.1 从你的 Windows 登录服务器

在 Windows 上：按 **Win 键**，输入 `cmd`，回车，打开黑色命令行窗口（即"命令提示符"；用 PowerShell 也行）。然后敲：

```bash
ssh 用户名@服务器IP
# 例如：ssh ubuntu@192.168.1.50
# 第一次连会问 yes/no，输入 yes；再输入密码（输入时不显示，正常）
```

成功后，**这个窗口里就是服务器**了，后面的命令都在这里敲。

> **下一步** → 登进来了，就把代码放上去（2.2）。

### 2.2 把代码放到服务器上

任选一种：

```bash
# 方式 A（推荐）：用 git 拉取
# （如果提示 git: command not found，先装它：sudo apt install -y git）
git clone https://github.com/Nazukida/torch-monkey.git
cd torch-monkey

# 方式 B：从你的 Windows 把整个文件夹传上来（在 Windows 的另一个终端，不是 SSH 里）
#   scp -r 你本地的torch-monkey文件夹 用户名@服务器IP:~/
```

> **下一步** → 代码就位，装运行需要的软件（2.3）。

### 2.3 安装 Python 和 ffmpeg

服务器需要 **Python ≥ 3.10** 和 **ffmpeg**（处理视频要用的命令行工具）。Ubuntu/Debian 系（最常见）这样装：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg
# sudo 会要密码（你登录服务器的那个）；apt 是 Linux 的"应用商店"命令
# （CentOS/RHEL/Fedora 把 apt 换成 dnf：sudo dnf install -y python3 python3-pip ffmpeg；其他发行版用对应包管理器）
```

> 偏好 **conda** 或 **uv**？不必走 apt 这一套——见 [§2.5](#25-一键配置-python-环境推荐) 的 `--conda` / `--uv` 选项（conda 用户只需再 `conda install ffmpeg` 把 ffmpeg 装进自己的环境）。

装完用以下命令验证一下：

```bash
python3 --version     # 应显示 3.10 或更高
ffmpeg -version       # 应显示一串版本信息，不报错
```

> 没有 `sudo` 权限（比如共享服务器）？看 [§6 "没有 sudo 怎么装"](#没有-sudo-权限怎么办)。
>
> **下一步** → 有卡的话确认一下 GPU（2.4）；没卡就跳到 2.5。

### 2.4 （有 NVIDIA 显卡才看）确认 GPU 和 CUDA

```bash
nvidia-smi
# 能打出一张显卡信息表（型号、显存、驱动版本）= GPU 可用
# 报错 "command not found" = 这台机器没 N 卡或没装驱动，没关系，按 CPU 跑（慢些）
```

有卡的话，下一步的"一键配环境"会自动识别并装 CUDA 版的 PyTorch（加速用）。**不需要你自己装 CUDA 工具链**。

> **下一步** → 一键配好 Python 环境（2.5）。

### 2.5 一键配置 Python 环境（推荐）

仓库里有个脚本，会自动：准备 Python 环境 → 探测 GPU 装 CUDA 版 torch → 装其余依赖 → 下模型 → 自检。

```bash
# 在仓库目录里（你刚 cd 进 torch-monkey 的那个）
bash scripts/setup.sh
# 看到 "✅ Torch Monkey Python 环境就绪" 就是成功了
```

**选环境方式 / Pick the Python env**（决定依赖装到哪里）：

| 参数 | 装到哪 | 说明 |
|---|---|---|
| （默认）/ `--venv` | `python/.venv` | 用 `python -m venv` 新建独立环境，最干净 |
| `--conda` | **你当前已激活的 conda 环境** | 先 `conda activate 你要用的环境`，再跑 setup；是不是 base 无所谓 |
| `--uv` | `python/.venv` | 用 [uv](https://docs.astral.sh/uv/) 建+装，**快很多**（需先装 uv） |

可以和 torch 选项**自由组合**：

```bash
bash scripts/setup.sh                          # 默认：venv + 自动探测 GPU
bash scripts/setup.sh --conda                  # 装进当前 conda 环境
bash scripts/setup.sh --uv                     # 用 uv（快）
bash scripts/setup.sh --conda --cuda 118       # 组合：conda 环境 + 指定 cu118
bash scripts/setup.sh --cpu                    # 强制 CPU 版 torch
```

> Windows 上等价：`npm run setup -- --conda`（或 `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 --conda`）。
> 报错看 [§6 "setup 失败"](#setup-失败)。

**激活环境 / Activate**（以后**每次新开终端**、跑体检 2.6 或起服务器 2.7 之前都要做一次）：

```bash
# 用了默认 venv 或 --uv：
source python/.venv/bin/activate        # 激活后命令行最前面会出现 (.venv)
# 用了 --conda：
conda activate <你的环境>                # 就是 setup 前激活的那个环境
```

> **下一步** → 体检一下（2.6），确认没漏。

### 2.6 体检（确认环境齐全）

```bash
python python/tools/check_env.py
# 打出一张 ✅/⚠️/❌ 表。退出码 = 问题数（0 = 全绿）
```

重点看：`torch` 那行有没有 `CUDA · <显卡型号>`（有的话说明 GPU 加速就绪）；模型权重那两行是不是 ✅。有 ❌ 就照着提示修，或重跑 2.5。

> **下一步** → 起服务器（2.7）。

### 2.7 启动 AI 服务器

```bash
cd python
python server.py
# 看到类似 "Starting Torch Monkey AI pipeline: 127.0.0.1:19876" 就是起来了
# 这个窗口要一直开着——关了服务器就停了
# （如果报 ModuleNotFoundError，说明 venv 没激活——回到 2.5 先 source 激活）
```

默认它只监听 **127.0.0.1**（也叫 **localhost**，即"本机自己"的固定地址——无论哪台电脑，访问 127.0.0.1 都是访问它自己）。这是**故意的安全设计**：服务器不对外敞开，配 SSH 隧道用最稳（见 [§3](#3-把两台电脑连起来ssh-隧道--局域网--测试连接)）。

> **下一步** → 如果你想"关掉 SSH 窗口服务器也不停"，看 2.8；否则直接跳 [§3 连接](#3-把两台电脑连起来ssh-隧道--局域网--测试连接)。

### 2.8 （推荐）让服务器在后台持续运行

SSH 窗口一关，前台启动的服务器会被杀掉。用 `tmux` 让它"挂在后台"：

```bash
# 如果没装 tmux：sudo apt install -y tmux
tmux new -s tm                   # 开一个名叫 tm 的会话
cd torch-monkey/python           # 进入目录（tmux 是全新会话，要重新 cd）
source .venv/bin/activate        # 新会话里要重新激活 venv（--conda 用户改为 conda activate <你的环境>）
python server.py                 # 起服务器
# 退出但让服务器继续跑：先同时按下 Ctrl 和 B，松开两键，再单独按一下 D
# 以后想回来看：tmux attach -t tm
```

> 也可以用 `nohup python server.py > server.log 2>&1 &`，但 tmux 更方便随时回去看输出。

**到这里服务器侧就全部就绪了。** 接下来回你的 Windows，把它连起来（[§3](#3-把两台电脑连起来ssh-隧道--局域网--测试连接)）。

---

## 3. 把两台电脑连起来（SSH 隧道 / 局域网 / 测试连接）

> 前提：[§2](#2-linux-服务器从零环境到起服务手把手) 已经完成，服务器上 `python server.py` 正在跑。

这里给三条路，**先推荐第一条（浏览器 + SSH 隧道）**——它最贴合"开网页就能看远端 GPU 结果"，也最安全。

### 3.1 路线 A（推荐）：浏览器 + SSH 隧道

**它解决什么：** 服务器只开在它自己内部（127.0.0.1），不对外暴露；我们用 SSH 在你 Windows 上"开一条隐形管道"，把服务器的 19876 端口接到你 Windows 的 127.0.0.1:19876。

**步骤：**

1. **先停一下——这一步需要网页端已经构建好。** 如果还没构建，请先跳到 [§4.2](#42-浏览器开网页即看推荐远端场景) 跑一次 `npm run build:web`，把产物（`python/web_dist/`）放到服务器上，做完再回到这里。服务器起来时会自动把网页托管在 `/`。

2. **在 Windows 上**打开一个 cmd / PowerShell，建立隧道（这条命令要保持窗口开着）：

   ```powershell
   ssh -L 19876:127.0.0.1:19876 用户名@服务器IP
   # 例如：ssh -L 19876:127.0.0.1:19876 ubuntu@192.168.1.50
   # 登录后这个窗口就"是"隧道了，别关；可以最小化
   ```

3. **在 Windows 浏览器里**打开：

   ```
   http://127.0.0.1:19876/
   ```

   应该看到 Torch Monkey 界面。右上角状态灯**变绿**，并显示 `cuda · <显卡型号>`，就说明请求**真的到了远端 GPU**。

> **这条隧道在干什么（一句话）：** 你访问 Windows 的 `127.0.0.1:19876`，SSH 把数据悄悄转发到服务器的 `127.0.0.1:19876`，等于"远程借用"。

### 3.2 路线 B：局域网直连（仅可信内网）

服务器对外开端口（适合校园网/公司内网这种可信环境，**不要**在公网这么做）：

```bash
# 在服务器上（替换掉 3.1 的默认启动方式）：
python server.py --host 0.0.0.0
# 再放行防火墙端口：
sudo ufw allow 19876      # 没有 ufw 就跳过，或用对应防火墙命令
```

然后浏览器或桌面 App 直接填 `http://服务器IP:19876`。

### 3.3 路线 C：桌面 App 的三种模式（⚙ 设置）

> 这一节只适用于**桌面 App**。浏览器端没有 ⚙ 按钮——直接用 [§3.1](#31-路线-a推荐浏览器--ssh-隧道) 或 [§3.2](#32-路线-b局域网直连仅可信内网) 即可。

桌面 App 顶栏右上角有个 **⚙** 按钮（状态灯旁边），点开"AI 管线 / 服务器设置"，选模式 → 填地址 → 点 **🔍 测试连接** → **💾 保存并应用**：

| 模式 | 服务器怎么起 | App 里填什么 |
|---|---|---|
| 🖥 **本地** | 不用管，App 自己在本机起 `server.py` | 本地端口（默认 19876） |
| 🔗 **远程·SSH 隧道** | 服务器默认 `127.0.0.1` 即可 | `http://127.0.0.1:19876`（先在系统里开隧道） |
| 🌐 **远程·局域网** | 服务器 `--host 0.0.0.0` + 放行端口 | `http://服务器IP:19876` |

**🔍 测试连接是关键**：成功会回显 `cuda · <显卡型号> · 已用/总 GB`，失败会给原因（超时/端口没开等）。它就是用来确认"我的请求到底有没有落到 GPU 机器上"。

> ⚠️ **最常见的坑（"点开后没转发到我电脑"）：** 如果你的 Windows 上装了 Python，桌面 App 的"本地"模式会**自己起一个 server.py 抢占 19876 端口**，导致隧道建不上或连到了本机进程。**解法：** 在 ⚙ 里切到"远程·SSH 隧道"或"远程·局域网"——切过去后 App 就**不再启动本机 Python**，端口让给隧道。详见 [§6](#转发没到我电脑连不上远端)。

---

## 4. Windows 客户端 / 浏览器：安装与运行

两种查看端二选一（或都装）。

**前提一·装 Node.js**（构建/开发前端要用）：去 [nodejs.org](https://nodejs.org/) 下载 **20 LTS** 的 Windows 安装包，一路下一步，**务必勾选「Add to PATH」**。装完打开一个**新的** cmd，敲 `node -v` 和 `npm -v`，能看到版本号就成了。

**前提二·装 Python 环境**（"本地"模式才需要；只连远端 GPU 服务器可跳过）：本地模式（桌面 App 本地、或本机起服务器用浏览器看）需要 Python ≥ 3.10 和模型权重。Windows 上最省事的做法是在仓库根目录跑一遍 `npm run setup`（它会建 venv、装 torch、下模型）——和 [§2.5](#25-一键配置-python-环境推荐) 是同一个脚本、同样的效果。**不装的话状态灯会一直是红色、动捕不可用**（舞台等其它功能仍能用）。

### 4.1 桌面 App（功能最全）

```bash
# 在仓库根目录
npm install          # 装前端依赖；第一次几分钟，末尾出现 added N packages 即成功
npm run dev          # 启动；稍等会自动弹出应用窗口
# （若 npm install 报 better-sqlite3 编译错误，看 §6 对应条目）
```

启动后看**顶栏右上角的灯**：

- 🟢 **绿灯** = AI 服务器就绪（本地模式下 App 会自动拉起 `python/server.py`）
- 🔴 **红灯** = AI 服务器离线（动捕功能不可用，但舞台/角色/手动动作/时间线/特效照常能用）。排错见 [§6](#顶栏红灯--ai-服务器离线)。

> 想连远端 GPU？启动后在 ⚙ 里切"远程"模式，见 [§3.3](#33-路线-c桌面-app-的三种模式-设置)。
>
> 想要安装包（不跑开发模式）：`npm run build:win` 出 Windows 安装包到 `release/`。

### 4.2 浏览器：开网页即看（推荐远端场景）

网页端就是桌面 App 的同一个界面，跑在浏览器里。构建只需要做**一次**，在哪台有 Node 的机器上都行（通常用你的 Windows）；**服务器自身不需要装 Node**。

```bash
# 在仓库根目录（你的 Windows 上）构建一次
npm run build:web
# 产物输出到 python/web_dist/
```

**把产物放到服务器**（服务器是远端 Linux 时）：

```bash
# 在 Windows 的另一个 cmd 里，把 web_dist 传到服务器（同 §2.2 方式 B 的 scp）
scp -r python/web_dist 用户名@服务器IP:~/torch-monkey/python/
```

> 服务器就在本机？跳过传输，直接进下一步。

然后**只要 `python server.py` 在跑，网页就自动托管在服务器的 `/`**：

- **本地**：在本机起 `python server.py`，浏览器开 `http://127.0.0.1:19876/`
- **远端 GPU**：服务器在 Linux，按 [§3.1](#31-路线-a推荐浏览器--ssh-隧道) 开 SSH 隧道，浏览器同样开 `http://127.0.0.1:19876/`

**浏览器端能做什么**（和桌面 App 基本一致）：

- ✅ 看 3D 舞台、浏览/播放动作库
- ✅ 🎥 导入视频动捕、📺 B 站动捕（视频在浏览器里选，自动上传到服务器算）
- ✅ 编排时间线、加角色、调特效
- ✅ 存/开 `.tmonkey` 工程（**存 = 浏览器下载一个文件；开 = 选一个文件上传**，和桌面端的"另存为/打开"对应）

**浏览器端和桌面 App 的小差别：**

- 选文件用**浏览器自己的文件框**（不是系统对话框）。
- 存工程是**下载** `.tmonkey` 文件；开工程是**上传** `.tmonkey` 文件。
- 没有原生顶部菜单（新建/打开/保存都改用界面上的按钮，快捷键 `Ctrl+S` 等仍可用）。
- 连接地址默认就是你打开网页的那个服务器；⭐ 想临时指向别的服务器，点 ⚙ 用"测试连接"探一下。

> 改了前端代码后，重新 `npm run build:web`、刷新浏览器即可。开发时想用热重载：`npm run dev:web`（在本机 5173 端口起开发服务器，并把 `/api` 转发到 `127.0.0.1:19876` 的 Python 服务器）。

---

## 5. 日常使用

### 5.1 舞台与灯光（右侧「舞台」面板）

- 滑块调舞台**宽度/深度**（5–50 m）；地板模式：网格 / 纯色 / 反射；调地板色、背景色、参考网格。
- 灯光：环境光、背光、聚光灯强度（暗背景 + 聚光灯 = 演出场地感），滑块即时生效（0.6.0 修复）。
- **视口操作**：左键拖拽旋转视角、滚轮缩放、右键平移；左键**直接拖动表演者身体**可在地面平移调整站位（见 5.2）。

### 5.2 角色（左侧「角色」面板 + 右侧「角色」面板）

- **＋ 新增角色** 加程序化人形，新角色按最小间距自动排开（不再重叠穿模）；支持"一字排开""V 字"自动对齐。
- **直接拖拽**：在 3D 视口里左键拖动表演者身体即可在地面上平移调整站位，右侧 X/Z 滑块会同步联动。
- 选中角色后右侧调：名称、身高、颜色、不透明度、X/Z 站位、朝向、是否显示骨骼。
- 每个角色都拥有**独立的时间线轨道**（见 5.4），可分别编排动作。
- 👁 切换可见、🗑 删除、可复制。

### 5.3 动作库（左侧「动作库」面板）

- 搜索框过滤；卡片显示时长、帧数、来源、运动强度、标签。
- **🎥 视频动捕**：选视频 → 走完整 AI 管线 → 自动入动作库。
- **📺 B 站动捕**：填 BV 号或 B 站链接，自动下载并送入管线（详见 [5.7](#57-b-站动捕bilibili-bv-号)）。
- **➕ 测试动作**：生成 3 个内置演示动作（T-Pose / 左手画圆 / 鞠躬），无需模型即可体验播放链路。
- **拖拽**动作卡片到底部时间线的角色轨道即可编排。

### 5.4 时间线（底部）

- 传输栏：▶/⏸ 播放暂停、⏹ 停止、速度滑块（0.25×–2×）、时间显示、🎵 导入音频、🥁 节拍检测、🧲 **磁吸**开关。
- 轨道类型：**角色（蓝）/ 相机（黄）/ 特效（紫）**，可🔒锁定、🔇静音。**每个角色自动拥有自己的轨道**。
- 片段：拖拽移动、左右边缘拖拽修剪、选中后删除。
- **🧲 磁吸**：开启后，拖拽或落子时段会自动吸附到相邻片段的起止边、播放头、起点，便于把动作严丝合缝地排在一起（吸附容差按秒计，与缩放无关）。
- 进度条里**没有动作覆盖**到的表演者会缓慢回到标准待机姿态（双腿 2 倍肩宽、双臂平举），不会停在半空或倒放。
- 导入音频后显示波形；"节拍检测"在波形上打点；红色竖线是播放头。

### 5.5 特效 VFX（右侧「特效」面板）

- 荧光棒开关、拖尾、双持；左右手分别配颜色/亮度/光照。
- 后期：Bloom 泛光（最关键）、阈值/强度/模糊核、曝光、对比度、暗角、锐化。
- 卡点瞬间会自动触发 **Bloom 增强** + 拖尾快速收敛（演出感的核心）。

### 5.6 工程

- 顶栏：新建 / 打开 / 保存 / 另存为；「🎥 导入视频动捕」「📺 B 站动捕」。
- `Ctrl+S` 保存为 `.tmonkey`（桌面端同时镜像进数据库；浏览器端为下载文件）。

#### 键盘快捷键

| 快捷键 | 功能 |
|---|---|
| `Space` / `K` | 播放 / 暂停 |
| `Home` / `End` | 跳到开头 / 结尾 |
| `←` / `→` | 前后步进一帧 |
| `Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` | 新建 / 打开 / 保存 / 另存为 |
| `Ctrl+I` | 导入视频动捕 |

### 5.7 B 站动捕（Bilibili BV 号）

除了导入本地视频，还可以直接给一个 **BV 号**，软件自动下载该视频并送进 AI 管线，结果同样进动作库。

**入口**：顶栏「📺 B 站动捕」，或动作库面板的「📺 B 站」按钮。

**流程**：
1. 输入 BV 号或链接，如 `BV1xx411c7mD`、`https://www.bilibili.com/video/BV1xx411c7mD`、`https://b23.tv/xxxxx`（短链自动解析）。
2. （可选）「🔍 探测」预览标题/时长/UP 主，确认是你要的。
3. 选分 P、FPS（30/60）、是否平滑/卡点检测。
4. 「⬇️ 下载并动捕」：先下载到临时目录，再走完整管线（抽帧→2D→3D→IK→优化→动作）。
5. 完成后自动入库，名称取自视频标题，标签含 `bilibili` 和 `BV:<编号>`。

**配置（环境变量，设在服务器侧）：**

- `TORCHMONKEY_BILI_MAX_DURATION`：时长上限（秒，默认 900 = 15 分钟；设 `0` 关闭）。
- `TORCHMONKEY_BILI_COOKIES`：高画质/会员内容可选提供 Netscape 格式 cookies 文件路径。

**怎么设**（在服务器上，**启动 `server.py` 之前**执行一次）：

```bash
export TORCHMONKEY_BILI_MAX_DURATION=3600   # 例如放宽到 1 小时
source python/.venv/bin/activate            # 再按平时一样起服务
python server.py
# 想让它在新开终端/tmux 里也生效：把上面 export 那行加到 ~/.bashrc 末尾
```

> ⚖️ **合规**：本功能**只下载你指定的单个视频**用于本地动作分析，不做批量抓取或再分发。请确保你有权下载和使用所选视频。本质上等同于你手动用 yt-dlp 下载一个链接再喂给管线。

---

## 6. 排错 FAQ（出问题先看这里）

### 顶栏红灯 / AI 服务器离线

- 本地模式：确认本机装了 Python 且在 PATH；手动跑 `python python/server.py` 看报错。
- 确认模型已下载：`python python/scripts/download_models.py`。
- 远程模式：先按 [§3](#3-把两台电脑连起来ssh-隧道--局域网--测试连接) 确认隧道/地址对，点 ⚙「测试连接」。
- 即便离线，舞台/角色/手动动作/时间线/特效仍可正常用。

### 转发没到我电脑（连不上远端）

- **最常见**：Windows 装了 Python，桌面 App 的"本地"模式自己起了 `server.py` 抢了 19876 → 在 ⚙ 切"远程·SSH 隧道/局域网"，App 就不抢端口了。
- SSH 隧道：确认 `ssh -L 19876:127.0.0.1:19876 用户@服务器` 这个窗口还开着；服务器上 `server.py` 还在跑。
- 局域网：服务器必须 `--host 0.0.0.0` 且防火墙放行 19876。
- 浏览器打不开（空白/报错）：多半是**没构建网页端**——跑一次 `npm run build:web` 再重启服务器；或确认访问的是 `http://127.0.0.1:19876/`（带 `http://`）。

### CUDA 没生效（应该是 GPU 却显示 CPU）

- 打开 `/api/health`（浏览器开 `http://127.0.0.1:19876/api/health`），看 `runtime.device` 是 `cuda` 还是 `cpu`。
- 若是 `cpu`：多半是 torch 被装成了 CPU 版。重装 CUDA 版：`pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121`，再 `pip install -r requirements.txt`。
- 或直接重跑 `bash scripts/setup.sh`（它会探测 `nvidia-smi` 自动装 CUDA 版）。
- `nvidia-smi` 都没有 → 这台机器没 GPU，只能 CPU 跑。

### 动捕结果不准确

- 用 **60fps** 源视频捕捉快速动作；全身入镜、光线充足、背景简洁。
- 确认 MotionBERT 权重已下载（缺失会退化为几何提升器，精度下降）。
- 在 GPU 上跑以获得更稳的时序推理。
- 跑 `python python/tools/selftest_pipeline.py` 确认管线本身正确（已激活 venv 的话直接 `python tools/selftest_pipeline.py`）。

### B 站动捕失败

- 确认装了 yt-dlp：`pip install yt-dlp`（在 `requirements.txt` 里）。
- AI 服务器离线时该按钮不可用——先让状态灯变绿。
- 视频 >15 分钟被拒：调高 `TORCHMONKEY_BILI_MAX_DURATION` 或裁剪源视频。
- 高画质/会员视频下载失败：导出浏览器 cookies 为 Netscape 文件，路径设到 `TORCHMONKEY_BILI_COOKIES`。
- B 站接口变动：`pip install -U yt-dlp` 升级后重试。

### 播放时角色不动 / 抖动

- 确认动作拖到了该角色对应的**角色轨道（蓝色）**。
- 该轨道未🔇静音、角色可见👁。
- AI 动作卡点处的"微停顿"是正常的打艺刹车效果，不是卡顿。

### `better-sqlite3` 安装/编译失败（桌面端）

- Windows 需 Visual Studio Build Tools（C++ 桌面开发）。或 `npm install --legacy-peer-deps` 后用 `npm run build` 验证。

### setup 失败

- `venv 创建失败`（Debian/Ubuntu）：`sudo apt install -y python3-venv`。
- `CUDA torch 安装失败`：核对 CUDA 版本，或改 `bash scripts/setup.sh --cpu` 先跑起来。
- 模型下载未完成：网络问题，稍后重跑 `python python/scripts/download_models.py`（脚本幂等，下过的会跳过）。

### 没有 sudo 权限怎么办

- 用 [miniconda](https://docs.conda.io/en/latest/miniconda.html) 装自己的 Python；ffmpeg 可用 `conda install ffmpeg`。
- 纯用户态：在 `~/.local` 下装 Python，把 `~/.local/bin` 加到 PATH。

---

## 7. 进阶：架构总览 / 术语表 / AI 管线与准确率

> 这一节是给想了解原理、做二次开发或排疑难问题的人。**新手可以跳过。**

### 7.1 架构总览

**同一个渲染层，两个后端：**

```
        桌面 App (Electron)                 浏览器 (web build)
   preload 注入 electronAPI ─┐         运行时注入 HTTP shim ─┐
                            ▼                               ▼
              同一套 renderer (React 19 + Babylon.js 9 + Zustand)
                            │
              (IPC / HTTP shim 都走同一个 window.electronAPI 接口)
                            ▼  fetch /api/*  (同源)
        ┌───────────────────────────────────────────────────┐
        │  Python AI 服务器 (FastAPI, :19876)                │
        │   · 管线：视频 → ffmpeg → MediaPipe 2D →           │
        │            MotionBERT 3D → IK 旋转 → 打艺优化 → 导出│
        │   · 存储层：motions/projects/settings (sqlite3,     │
        │     复用 database/schema.sql)                       │
        │   · 静态托管：python/web_dist/ → 浏览器端           │
        └───────────────────────────────────────────────────┘
```

四层数据解耦（参考 MMD）：**模型 / 动作 / 相机 / 特效** 完全独立，可自由混搭，组合写入 `.tmonkey` 工程文件。

渲染层与 Electron 解耦的关键：所有 Electron 能力都通过一个 `window.electronAPI` 对象流动（preload 注入），渲染层不直接 import Electron。浏览器版只是把这个对象换成 HTTP 实现（`src/renderer/src/web/apiShim.ts`），渲染层代码原封不动。

### 7.2 术语对照表

| 中文 | 日本語 | English |
|---|---|---|
| 打艺 / Wota-艺 | ヲタ芸 | wotagei |
| 动作捕捉 | モーションキャプチャ | motion capture (mocap) |
| 动作 | モーション | motion |
| 动作库 | モーションライブラリ | motion library |
| 卡点 | キメ | kime |
| 荧光棒 | サイリウム | cyalume / glowstick |
| 骨架 / 骨骼 | スケルトン | skeleton |
| 关节 | 関節 | joint |
| 四元数 | クォータニオン | quaternion |
| 正/逆运动学 | フォワード/インバース キネマティクス | FK / IK |
| 舞台 / 灯光 / 聚光灯 | ステージ / ライティング / スポットライト | stage / lighting / spotlight |
| 时间线 / 轨道 / 片段 / 节拍 | タイムライン / トラック / クリップ / ビート | timeline / track / clip / beat |
| 角色 / 摄像机 / 模型 / 重定向 | キャラクター / カメラ / モデル / リターゲット | character / camera / model / retarget |
| 泛光 / 拖尾 / 后期处理 | ブルーム / トレイル / ポストプロセス | bloom / trail / post-processing |
| 工程文件 / B 站 / BV 号 | プロジェクトファイル / ビリビリ / BV 番号 | project file / Bilibili / BV id |

### 7.3 AI 管线与准确率

**管线流程：**

```
视频 → ffmpeg/OpenCV 抽帧 → MediaPipe BlazePose 33 关键点(2D)
     → BlazePose→Human3.6M 17 关节映射（修正版）
     → MotionBERT 3D 提升得到 17 关节 3D 位置(mm)
     → expand_joints 扩展到 SMPL-24(24 关节, 米)
     → ik_solver: 位置 → 每关节局部旋转四元数 + 根轨迹
     → WotageiOptimizer: 卡点检测 + 受保护平滑 + 关节限位 + 零过渡刹车
     → FormatExporter: 内部 MotionData JSON
```

**准确率要点（相对早期草案的改进）：**

| 问题 | 改进 |
|---|---|
| BlazePose→H36M 映射错误 | `lib/blazepose_to_h36m.py` 规范映射，17 关节全部正确 |
| MotionBERT 输出位置、内部需旋转 | `pipeline/ik_solver.py` 真正的位置→旋转求解器，闭环误差 < 2 mm |
| 骨长抖动拉伸 | IK 前强制中值骨长（球面重投影） |
| 平滑糊掉卡点 | 卡点保护窗口内不滤波，卡点帧零过渡刹车 |
| 缺模型即崩 | torch/mediapipe 延迟导入 + 守卫；权重缺失回退几何提升器 |
| 无 GPU 难验证 | `tools/selftest_pipeline.py` 闭环自检（CPU 数秒） |

**IK 求解器原理（简述）：** 对每帧每个有父关节的关节，在父局部系下算"静止骨方向→当前骨方向"的局部四元数（鲁棒向量间旋转 + 参考 up 向量解扭转）。根骨盆世界旋转由髋连线/肩连线求得，根轨迹取骨盆位置。

**GPU 说明：** `device = "cuda" if torch.cuda.is_available() else "cpu"`；243 帧滑窗、50% 重叠、`torch.no_grad()`；CPU 开发自检通过，GPU 上无需改动即加速。

**准确率自检（无需 GPU/模型）：**

```bash
cd python && python tools/selftest_pipeline.py
# 平均重建误差 < 2 mm；退出码 0 = 通过
```

### 7.4 HTTP 接口（给二次开发/对接）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 就绪状态 + 运行环境（device/CUDA/GPU/显存/torch/ffmpeg） |
| GET | `/api/tasks` | 任务列表（终端面板用） |
| GET | `/api/progress/{task_id}` | 单任务进度 |
| POST | `/api/preview-video` | ffprobe 探测视频元信息（不做推理） |
| POST | `/api/process-video` | 完整管线（multipart `file`） |
| POST | `/api/preview-bilibili` | 按 BV 号探测元信息（不下载） |
| POST | `/api/process-bilibili` | 按 BV 号下载 + 完整管线 |
| GET/POST | `/api/motions`, `GET /api/motions/{id}`, `PATCH/DELETE /api/motions/{id}` | 动作库增删改查（浏览器端用） |
| GET/POST | `/api/projects`, `GET /api/projects/{id}` | 工程库（浏览器端用） |
| GET/PUT | `/api/settings/{key}` | 键值设置 |
| GET | `/api/tags`, `/api/stats` | 热门标签 / 库统计 |

> 另外，`python/tools/dashboard.py` 是跑在终端里的**监控面板**（看 GPU 型号/显存、每个任务的实时进度），**不是查看器**。用法见 [python/README.md](./python/README.md)。

### 7.5 项目结构与数据格式

```
torch-monkey/
├─ electron.vite.config.ts   桌面端构建（main/preload/renderer）
├─ vite.config.web.ts        浏览器端构建（→ python/web_dist/）
├─ vite.shared.ts            两端共享的路径别名
├─ database/schema.sql       SQLite 表结构（桌面端与服务端共用）
├─ shared/                   前后端共享契约（TS 类型）
├─ src/
│  ├─ main/                  Electron 主进程 + IPC + 数据库 + Python 管理
│  ├─ preload/               contextBridge 桥（注入 electronAPI）
│  └─ renderer/src/          React + Babylon 渲染层
│     └─ web/apiShim.ts      浏览器版 electronAPI（HTTP 实现）
├─ python/
│  ├─ server.py              FastAPI 服务（:19876）+ 存储路由 + 网页托管
│  ├─ api/store.py           sqlite3 存储层（复用 schema.sql）
│  ├─ pipeline/ lib/ tools/ scripts/
│  └─ web_dist/              浏览器构建产物（npm run build:web 生成）
└─ USAGE.md                  本文档
```

**MotionData JSON 要点**（`shared/types/motion.ts`，与服务端输出逐字段一致）：

- `poses[t].transforms[j].rotation`：关节 j 的**局部**四元数 `[x,y,z,w]`。
- 只有根关节 PELVIS（索引 0）带世界 `position`，其余关节位移恒为零。
- 骨架类型固定 `smpl_24`，关节定义见 `shared/constants/skeleton.ts`（与 `python/lib/skeleton_def.py` 一致）。

### 7.6 环境变量一览

| 变量 | 作用 | 默认 |
|---|---|---|
| `TORCHMONKEY_HOST` | 服务器绑定地址（设 `0.0.0.0` 对局域网开放） | `127.0.0.1` |
| `TORCHMONKEY_DATA_DIR` | 服务端存储库目录（motions/projects 的 SQLite） | `python/data` |
| `TORCHMONKEY_WEB_DIST` | 浏览器构建产物目录（托管在 `/`） | `python/web_dist` |
| `TORCHMONKEY_FFPROBE` / `TORCHMONKEY_FFMPEG` | 指向 ffmpeg/ffprobe 可执行文件路径 | 从 PATH 找 |
| `TORCHMONKEY_BILI_MAX_DURATION` | B 站视频时长上限（秒，`0` 关闭） | `900` |
| `TORCHMONKEY_BILI_COOKIES` | B 站 Netscape cookies 文件路径 | （空） |

---

*Enjoy your wotagei. — Torch Monkey*
