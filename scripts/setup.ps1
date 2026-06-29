# Torch Monkey — one-command environment setup (Windows PowerShell).
#
# Creates python\.venv, auto-detects an NVIDIA GPU and installs the matching
# CUDA build of torch (or CPU torch otherwise), installs the rest of the
# requirements, downloads model weights, and runs the IK self-test.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 --cpu
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 --cuda 118
#
# Flags mirror setup.sh so `npm run setup` works on either OS.
# Idempotent: safe to re-run.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$PyDir     = Join-Path $RepoRoot "python"
$Venv      = Join-Path $PyDir ".venv"
$VenvPy    = Join-Path $Venv "Scripts\python.exe"

# ---- arg parse (identical flags to setup.sh) ------------------------------
$Cpu  = $false
$Cuda = $null
$idx = 0
while ($idx -lt $args.Count) {
  switch -Regex ($args[$idx]) {
    '^(--cpu|-cpu)$'        { $Cpu = $true; $idx++ }
    '^(--cuda|-cuda)$'      { $Cuda = $args[$idx + 1]; $idx += 2 }
    '^--cuda=(.+)$'         { $Cuda = $matches[1]; $idx++ }
    '^(--help|-h)$'         { Get-Content $MyInvocation.MyCommand.Path -TotalCount 16; exit 0 }
    default                 { Write-Host "[warn] 未知参数 / unknown arg: $($args[$idx])" -ForegroundColor Yellow; $idx++ }
  }
}

function Info($m) { Write-Host "[setup] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn]  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[error] $m" -ForegroundColor Red; exit 1 }

# 1) Python interpreter
$py = $null
foreach ($c in @("python", "python3", "py")) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) { Fail "未找到 Python / Python not found. 安装 / install Python >= 3.10: https://www.python.org/" }
Info "Python: $(& $py --version 2>&1)"
$verOk = & $py -c "import sys; v=tuple(int(x) for x in sys.version.split()[0].split('.')[:2]); print('ok' if v>=(3,10) else 'bad')"
if ($verOk -ne "ok") { Fail "Python 版本过低 / Python >= 3.10 required." }

# 2) Node (soft — only needed for the desktop client build)
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) { Info "Node: $(node --version)" }
else { Warn "未找到 node / node not found（前端客户端需要 / needed for the desktop client）: https://nodejs.org/" }

# 3) Virtualenv (create or reuse)
if (Test-Path $VenvPy) {
  Info "复用虚拟环境 / reusing venv: $Venv"
} else {
  Info "创建虚拟环境 / creating venv: $Venv"
  & $py -m venv $Venv
  if (-not (Test-Path $VenvPy)) { Fail "venv 创建失败 / venv creation failed." }
}
& $VenvPy -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Warn "pip 升级失败 / pip upgrade failed (continuing)." }

# 4) torch — GPU auto-detect
$wantCuda = $null
if ($Cpu) {
  Info "torch: 用户指定 --cpu，安装 CPU 版 / CPU build."
} elseif ($Cuda) {
  $wantCuda = "$Cuda"
  Info "GPU: 用户指定 --cuda $Cuda / requested cu$Cuda torch."
} else {
  $nv = Get-Command nvidia-smi -ErrorAction SilentlyContinue
  if ($nv) { Info "GPU: 检测到 nvidia-smi → 安装 CUDA 版 torch (cu121) / CUDA build (cu121)."; $wantCuda = "121" }
  else     { Info "GPU: 未检测到 nvidia-smi → CPU 版 torch / CPU build." }
}
if ($wantCuda -in @("121", "118")) {
  $url = "https://download.pytorch.org/whl/cu$wantCuda"
  Info "pip install torch==2.5.1 --index-url $url"
  & $VenvPy -m pip install "torch==2.5.1" --index-url $url
  if ($LASTEXITCODE -ne 0) { Fail "CUDA torch 安装失败 / CUDA torch install failed. 重试 --cpu 或核对 CUDA 版本 / try --cpu or verify your CUDA toolkit." }
}

# 5) requirements
Info "pip install -r requirements.txt"
Push-Location $PyDir
& $VenvPy -m pip install -r requirements.txt
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Fail "依赖安装失败 / requirements install failed." }

# 6) model weights (idempotent)
Info "下载模型权重 / downloading model weights (幂等 / idempotent)…"
Push-Location $PyDir
& $VenvPy scripts/download_models.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Warn "模型下载未完成 / model download incomplete（可稍后重试 / retry later: python scripts/download_models.py）." }

# 7) IK accuracy self-test
Info "运行 IK 准确率自检 / running IK self-test…"
Push-Location $PyDir
& $VenvPy tools/selftest_pipeline.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Warn "自检未通过 / self-test did not pass — 见上方输出 / see output above." }

# 8) environment check
Info "环境自检 / environment check:"
Push-Location $PyDir
& $VenvPy tools/check_env.py
Pop-Location

Write-Host ""
Info "Torch Monkey Python 环境就绪 / Python environment ready."
Write-Host "下一步 / Next:"
Write-Host "  起 AI 管线服务 / start the pipeline server:    cd python; python server.py"
Write-Host "  终端可视化 / terminal dashboard:               python tools/dashboard.py"
Write-Host "  桌面客户端 / desktop client:                   npm run dev"
