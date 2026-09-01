#!/usr/bin/env bash
# Torch Monkey — one-command environment setup (Linux / macOS).
#
# Installs the Python deps, auto-detects an NVIDIA GPU and installs the matching
# CUDA build of torch (or CPU torch otherwise), downloads model weights, and
# runs the IK self-test.
#
# 环境方式 / Env backend（决定依赖装到哪里）:
#   --venv    用 python -m venv 建 python/.venv（默认 / default）
#   --conda   用你【当前已激活】的 conda/python 环境，不再另建 venv
#             （先 conda activate 你的环境，再跑 setup --conda；是不是 base 无所谓）
#   --uv      用 uv 建 python/.venv 并用 uv pip 安装（快 / fast）
#
# Torch 版本 / Torch build（与上面的环境方式可自由组合）:
#   (none)    自动：检测到 nvidia-smi 就装 cu121，否则 CPU
#   --cpu     强制 CPU 版
#   --cuda 118|121   指定 CUDA 版本
#
# Usage:
#   bash scripts/setup.sh                      # 默认 venv + 自动 GPU
#   bash scripts/setup.sh --conda              # 装进当前 conda 环境
#   bash scripts/setup.sh --uv                 # 用 uv
#   bash scripts/setup.sh --conda --cuda 118   # 组合：conda 环境 + cu118
#
# Idempotent: safe to re-run. Pure shell + python (uv 可选 / uv optional).

set -u

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
PY_DIR="$REPO_ROOT/python"
VENV="$PY_DIR/.venv"

# ---- arg parse (kept identical to setup.ps1 so the Node dispatcher can pass
#      the same flags through on either OS) ---------------------------------
CUDA="auto"
ENV_BACKEND="venv"
while [ $# -gt 0 ]; do
  case "$1" in
    --cpu|-cpu) CUDA="cpu"; shift ;;
    --cuda|-cuda)
      [ $# -ge 2 ] || { printf '[error] --cuda 需要版本号 / needs a version (118|121)\n' >&2; exit 2; }
      CUDA="$2"; shift 2 ;;
    --cuda=*) CUDA="${1#--cuda=}"; shift ;;
    --venv) ENV_BACKEND="venv"; shift ;;
    --conda) ENV_BACKEND="conda"; shift ;;
    --uv) ENV_BACKEND="uv"; shift ;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *) printf '[warn] 未知参数 / unknown arg: %s\n' "$1"; shift ;;
  esac
done

info() { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[error]\033[0m %s\n' "$*"; exit 1; }

# Friendly hint if a conda env looks active but --conda wasn't passed.
if [ "$ENV_BACKEND" = "venv" ] && [ -n "${CONDA_DEFAULT_ENV:-}" ]; then
  warn "检测到 conda 环境 '$CONDA_DEFAULT_ENV'。若想装进它而非 .venv，加 --conda 重跑 / re-run with --conda to use it."
fi

# 1) Python interpreter (for conda/uv this is the currently-active one)
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else fail "未找到 Python / Python not found. 安装 / install Python >= 3.10: https://www.python.org/"; fi
info "Python: $($PY --version 2>&1)  ($($PY -c 'import sys; print(sys.executable)'))"
$PY -c 'import sys; v=tuple(int(x) for x in sys.version.split()[0].split(".")[:2]); sys.exit(0 if v>=(3,10) else 1)' \
  || fail "Python 版本过低 / Python >= 3.10 required (got $($PY --version 2>&1))."

# 2) Node (soft — only needed for the desktop client build)
if command -v node >/dev/null 2>&1; then info "Node: $(node --version)";
else warn "未找到 node / node not found（前端客户端需要 / needed for the desktop client）: https://nodejs.org/"; fi

# 3) Environment backend → resolve VPY (python to install into / run with) and
#    PIP (the install command). venv/conda use `python -m pip`; uv uses `uv pip`.
case "$ENV_BACKEND" in
  venv)
    info "环境方式 / env: venv → $VENV"
    if [ -x "$VENV/bin/python" ]; then
      info "复用虚拟环境 / reusing venv: $VENV"
    else
      info "创建虚拟环境 / creating venv: $VENV"
      $PY -m venv "$VENV" || fail "venv 创建失败 / venv creation failed.（Debian/Ubuntu 需 python3-venv / needs python3-venv）"
    fi
    VPY="$VENV/bin/python"
    $VPY -m pip install --upgrade pip --quiet 2>/dev/null || warn "pip 升级失败 / pip upgrade failed (continuing)."
    PIP=( "$VPY" -m pip install )
    ;;
  conda)
    info "环境方式 / env: conda（使用当前已激活的 python / using the active python）"
    VPY="$PY"
    info "  目标 python / target: $($VPY -c 'import sys; print(sys.executable)')"
    warn "  请确认你已 conda activate 想用的环境（是 base 也行）/ activate the env you want first."
    PIP=( "$VPY" -m pip install )
    ;;
  uv)
    info "环境方式 / env: uv → $VENV"
    command -v uv >/dev/null 2>&1 \
      || fail "未找到 uv / uv not found. 安装 / install: https://docs.astral.sh/uv/  或 / or: pip install uv"
    if [ -x "$VENV/bin/python" ]; then
      info "复用虚拟环境 / reusing venv: $VENV"
    else
      uv venv "$VENV" || fail "uv venv 创建失败 / uv venv creation failed."
    fi
    VPY="$VENV/bin/python"
    PIP=( uv pip install --python "$VPY" )
    ;;
esac

# 4) torch — GPU auto-detect
WANT_CUDA=""
if [ "$CUDA" = "cpu" ]; then
  info "torch: 用户指定 --cpu，安装 CPU 版 / CPU build."
elif [ "$CUDA" = "auto" ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    # Pick the CUDA build from the card's *compute capability*, not blindly
    # cu121. Blackwell (RTX 50xx) is sm_120 and has no kernels in cu121
    # builds: torch installs fine, then dies at the first kernel launch with
    # "no kernel image is available for execution on the device".
    CAP="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d ' ')"
    CAP_MAJOR="${CAP%%.*}"
    if [ -n "$CAP_MAJOR" ] && [ "$CAP_MAJOR" -ge 12 ] 2>/dev/null; then
      info "GPU: compute capability $CAP (Blackwell+) -> cu128 build."
      WANT_CUDA="128"
    else
      info "GPU: compute capability ${CAP:-unknown} -> cu121 build."
      WANT_CUDA="121"
    fi
  else
    info "GPU: 未检测到 nvidia-smi → CPU 版 torch / CPU build."
  fi
else
  WANT_CUDA="$CUDA"
  info "GPU: 用户指定 --cuda $CUDA / requested cu$CUDA torch."
fi
if [ "$WANT_CUDA" = "121" ] || [ "$WANT_CUDA" = "118" ] || [ "$WANT_CUDA" = "128" ]; then
  # torch version must match the CUDA build: sm_120 kernels first ship in
  # cu128 wheels, which start at torch 2.7. cu118/cu121 stay on 2.5.1.
  if [ "$WANT_CUDA" = "128" ]; then TORCH_PIN="torch==2.9.1"; else TORCH_PIN="torch==2.5.1"; fi
  TORCH_INDEX="https://download.pytorch.org/whl/cu$WANT_CUDA"
  info "${PIP[*]} $TORCH_PIN --index-url $TORCH_INDEX"
  "${PIP[@]}" "$TORCH_PIN" --index-url "$TORCH_INDEX" \
    || fail "CUDA torch 安装失败 / CUDA torch install failed. 重试 --cpu 或核对 CUDA 版本 / try --cpu or verify your CUDA toolkit."
elif [ -n "$WANT_CUDA" ]; then
  fail "unsupported --cuda: $WANT_CUDA (supported: 118, 121, 128)"
fi

# 5) requirements (CPU torch line satisfied by whatever was installed above)
# -c constraints-numpy1.txt pins mediapipe's unpinned jax/jaxlib/opencv-contrib,
# which otherwise demand numpy>=2 and send pip into a backtrack loop against
# our pinned numpy==1.26.4.
info "${PIP[*]} -r requirements.txt -c constraints-numpy1.txt"
( cd "$PY_DIR" && "${PIP[@]}" -r requirements.txt -c constraints-numpy1.txt ) \
  || fail "依赖安装失败 / requirements install failed."

# 6) model weights (idempotent)
info "下载模型权重 / downloading model weights (幂等 / idempotent)…"
( cd "$PY_DIR" && "$VPY" scripts/download_models.py ) \
  || warn "模型下载未完成 / model download incomplete（可稍后重试 / retry later: python scripts/download_models.py）."

# 7) IK accuracy self-test (CPU, seconds)
info "运行 IK 准确率自检 / running IK self-test (CPU, 秒级 / seconds)…"
( cd "$PY_DIR" && "$VPY" tools/selftest_pipeline.py ) \
  || warn "自检未通过 / self-test did not pass — 见上方输出 / see output above."

# 8) environment check
info "环境自检 / environment check:"
( cd "$PY_DIR" && "$VPY" tools/check_env.py ) || true

# ---- next-step banner (activation depends on the env backend) -------------
if [ "$ENV_BACKEND" = "conda" ]; then
cat <<EOF

✅ Torch Monkey Python 环境就绪 / Python environment ready (conda).

下一步 / Next（每次新开终端都要先激活你的 conda 环境 / activate your conda env each new terminal）:
  conda activate <你的环境 / your env>
  cd python && python server.py
  终端可视化 / terminal dashboard:    python tools/dashboard.py
  桌面客户端 / desktop client:        npm run dev
EOF
else
cat <<EOF

✅ Torch Monkey Python 环境就绪 / Python environment ready.

下一步 / Next（每次新开终端都要先激活 venv / activate venv each new terminal）:
  cd python && source .venv/bin/activate && python server.py
  终端可视化（本地或经 SSH 隧道）/ terminal dashboard (local or over an SSH tunnel):
      python tools/dashboard.py
  桌面客户端 / desktop client:
      npm run dev
EOF
fi
