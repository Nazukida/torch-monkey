#!/usr/bin/env bash
# Torch Monkey — one-command environment setup (Linux / macOS).
#
# Creates python/.venv, auto-detects an NVIDIA GPU and installs the matching
# CUDA build of torch (or CPU torch otherwise), installs the rest of the
# requirements, downloads model weights, and runs the IK self-test.
#
# Usage:
#   bash scripts/setup.sh             # auto: cu121 if nvidia-smi present, else CPU
#   bash scripts/setup.sh --cpu       # force CPU torch
#   bash scripts/setup.sh --cuda 118  # force a specific CUDA build (121 | 118)
#
# Idempotent: safe to re-run. Pure shell + python (no extra dependencies).

set -u

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
PY_DIR="$REPO_ROOT/python"
VENV="$PY_DIR/.venv"

# ---- arg parse (kept identical to setup.ps1 so the Node dispatcher can pass
#      the same flags through on either OS) ---------------------------------
CUDA="auto"
while [ $# -gt 0 ]; do
  case "$1" in
    --cpu|-cpu) CUDA="cpu"; shift ;;
    --cuda|-cuda)
      [ $# -ge 2 ] || { printf '[error] --cuda 需要版本号 / needs a version (118|121)\n' >&2; exit 2; }
      CUDA="$2"; shift 2 ;;
    --cuda=*) CUDA="${1#--cuda=}"; shift ;;
    -h|--help)
      sed -n '2,16p' "$0"; exit 0 ;;
    *) printf '[warn] 未��参数 / unknown arg: %s\n' "$1"; shift ;;
  esac
done

info() { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[error]\033[0m %s\n' "$*"; exit 1; }

# 1) Python interpreter
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else fail "未找到 Python / Python not found. 安装 / install Python >= 3.10: https://www.python.org/"; fi
info "Python: $($PY --version 2>&1)"
$PY -c 'import sys; v=tuple(int(x) for x in sys.version.split()[0].split(".")[:2]); sys.exit(0 if v>=(3,10) else 1)' \
  || fail "Python 版本过低 / Python >= 3.10 required (got $($PY --version 2>&1))."

# 2) Node (soft — only needed for the desktop client build)
if command -v node >/dev/null 2>&1; then info "Node: $(node --version)";
else warn "未找到 node / node not found（前端客户端需要 / needed for the desktop client）: https://nodejs.org/"; fi

# 3) Virtualenv (create or reuse)
if [ -x "$VENV/bin/python" ]; then
  info "复用虚拟环境 / reusing venv: $VENV"
else
  info "创建虚拟环境 / creating venv: $VENV"
  $PY -m venv "$VENV" || fail "venv 创建失败 / venv creation failed.（Debian/Ubuntu 需 python3-venv / needs python3-venv）"
fi
VPY="$VENV/bin/python"
$VPY -m pip install --upgrade pip --quiet 2>/dev/null || warn "pip 升级失败 / pip upgrade failed (continuing)."

# 4) torch — GPU auto-detect
WANT_CUDA=""
if [ "$CUDA" = "cpu" ]; then
  info "torch: 用户指定 --cpu，安装 CPU 版 / CPU build."
elif [ "$CUDA" = "auto" ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    info "GPU: 检测到 nvidia-smi → 安装 CUDA 版 torch (cu121) / CUDA build (cu121)."
    WANT_CUDA="121"
  else
    info "GPU: 未检测到 nvidia-smi → CPU 版 torch / CPU build."
  fi
else
  WANT_CUDA="$CUDA"
  info "GPU: 用户指定 --cuda $CUDA / requested cu$CUDA torch."
fi
if [ "$WANT_CUDA" = "121" ] || [ "$WANT_CUDA" = "118" ]; then
  TORCH_INDEX="https://download.pytorch.org/whl/cu$WANT_CUDA"
  info "pip install torch==2.5.1 --index-url $TORCH_INDEX"
  $VPY -m pip install "torch==2.5.1" --index-url "$TORCH_INDEX" \
    || fail "CUDA torch 安装失败 / CUDA torch install failed. 重试 --cpu 或核对 CUDA 版本 / try --cpu or verify your CUDA toolkit."
fi

# 5) requirements (CPU torch line satisfied by whatever was installed above)
info "pip install -r requirements.txt"
( cd "$PY_DIR" && $VPY -m pip install -r requirements.txt ) \
  || fail "依赖安装失败 / requirements install failed."

# 6) model weights (idempotent)
info "下载模型权重 / downloading model weights (幂等 / idempotent)…"
( cd "$PY_DIR" && $VPY scripts/download_models.py ) \
  || warn "模型下载未完成 / model download incomplete（可稍后重试 / retry later: python scripts/download_models.py）."

# 7) IK accuracy self-test (CPU, seconds)
info "运行 IK 准确率自检 / running IK self-test (CPU, 秒级 / seconds)…"
( cd "$PY_DIR" && $VPY tools/selftest_pipeline.py ) \
  || warn "自检未通过 / self-test did not pass — 见上方输出 / see output above."

# 8) environment check
info "环境自检 / environment check:"
( cd "$PY_DIR" && $VPY tools/check_env.py ) || true

cat <<EOF

✅ Torch Monkey Python 环境就绪 / Python environment ready.

下一步 / Next:
  起 AI 管线服务 / start the pipeline server:
      cd python && python server.py
  终端可视化（本地或经 SSH 隧道）/ terminal dashboard (local or over an SSH tunnel):
      python tools/dashboard.py
  桌面客户端 / desktop client:
      npm run dev
EOF
