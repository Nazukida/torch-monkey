# Torch Monkey — one-command environment setup (Windows PowerShell).
#
# Installs the Python deps, auto-detects an NVIDIA GPU and installs the matching
# CUDA build of torch (or CPU torch otherwise), downloads model weights, and
# runs the IK self-test.
#
# 环境方式 / Env backend（决定依赖装到哪里）:
#   --venv    用 python -m venv 建 python\.venv（默认 / default）
#   --conda   用你【当前已激活】的 conda/python 环境，不再另建 venv
#             （先 conda activate 你的环境，再跑 setup --conda；是不是 base 无所谓）
#   --uv      用 uv 建 python\.venv 并用 uv pip 安装（快 / fast）
#
# Torch 版本 / Torch build（与上面的环境方式可自���组合）:
#   (none)    自动：检测到 nvidia-smi 就装 cu121，否则 CPU
#   --cpu     强制 CPU 版
#   --cuda 118|121   指定 CUDA 版本
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 --conda
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 --uv --cuda 118
#
# Flags mirror setup.sh so `npm run setup` works on either OS.
# Idempotent: safe to re-run.

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptDir
$PyDir      = Join-Path $RepoRoot "python"
$Venv       = Join-Path $PyDir ".venv"
$VenvPy     = Join-Path $Venv "Scripts\python.exe"

# ---- arg parse (identical flags to setup.sh) ------------------------------
$Cpu        = $false
$Cuda       = $null
$EnvBackend = "venv"
$idx = 0
while ($idx -lt $args.Count) {
  switch -Regex ($args[$idx]) {
    '^(--cpu|-cpu)$'    { $Cpu = $true; $idx++ }
    '^(--cuda|-cuda)$'  { $Cuda = $args[$idx + 1]; $idx += 2 }
    '^--cuda=(.+)$'     { $Cuda = $matches[1]; $idx++ }
    '^--venv$'          { $EnvBackend = "venv"; $idx++ }
    '^--conda$'         { $EnvBackend = "conda"; $idx++ }
    '^--uv$'            { $EnvBackend = "uv"; $idx++ }
    '^(--help|-h)$'     { Get-Content $MyInvocation.MyCommand.Path -TotalCount 30; exit 0 }
    default             { Write-Host "[warn] 未知参数 / unknown arg: $($args[$idx])" -ForegroundColor Yellow; $idx++ }
  }
}

function Info($m) { Write-Host "[setup] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn]  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[error] $m" -ForegroundColor Red; exit 1 }

# Friendly hint if a conda env looks active but --conda wasn't passed.
if (($EnvBackend -eq "venv") -and $env:CONDA_DEFAULT_ENV) {
  Warn "检测到 conda 环境 '$env:CONDA_DEFAULT_ENV'。若想装进它而非 .venv，加 --conda 重跑 / re-run with --conda to use it."
}

# 1) Python interpreter (for conda/uv this is the currently-active one)
$py = $null
foreach ($c in @("python", "python3", "py")) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) { Fail "未找到 Python / Python not found. 安装 / install Python >= 3.10: https://www.python.org/" }
$pyPath = & $py -c "import sys; print(sys.executable)"
Info "Python: $(& $py --version 2>&1)  ($pyPath)"
$verOk = & $py -c "import sys; v=tuple(int(x) for x in sys.version.split()[0].split('.')[:2]); print('ok' if v>=(3,10) else 'bad')"
if ($verOk -ne "ok") { Fail "Python 版本过低 / Python >= 3.10 required." }

# 2) Node (soft — only needed for the desktop client build)
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) { Info "Node: $(node --version)" } else { Warn "未找到 node / node not found（前端客户端需要 / needed for the desktop client）: https://nodejs.org/" }

# 3) Environment backend → resolve $py (python to install into / run with).
#    venv/conda → python -m pip；uv → uv pip
if ($EnvBackend -eq "conda") {
  Info "环境方式 / env: conda（使用当前已激活的 python / using the active python）"
  Info "  目标 python / target: $pyPath"
  Warn "  请确认你已 conda activate 想用的环境（是 base 也行）/ activate the env you want first."
} elseif ($EnvBackend -eq "uv") {
  Info "环境方式 / env: uv → $Venv"
  $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
  if (-not $uvCmd) { Fail "未找到 uv / uv not found. 安装 / install: https://docs.astral.sh/uv/  或 / or: pip install uv" }
  if (Test-Path $VenvPy) { Info "复用虚拟环境 / reusing venv: $Venv" } else {
    Info "创建虚拟环境 (uv) / creating venv: $Venv"
    uv venv $Venv
    if (-not (Test-Path $VenvPy)) { Fail "uv venv 创建失败 / uv venv creation failed." }
  }
  $py = $VenvPy
} else {
  Info "环境方式 / env: venv → $Venv"
  if (Test-Path $VenvPy) { Info "复用虚拟环境 / reusing venv: $Venv" } else {
    Info "创建虚拟环境 / creating venv: $Venv"
    & $py -m venv $Venv
    if (-not (Test-Path $VenvPy)) { Fail "venv 创建失败 / venv creation failed." }
  }
  $py = $VenvPy
  & $py -m pip install --upgrade pip --quiet
  if ($LASTEXITCODE -ne 0) { Warn "pip 升级失败 / pip upgrade failed (continuing)." }
}

# 4) torch — GPU auto-detect
$wantCuda = $null
if ($Cpu) {
  Info "torch: 用户指定 --cpu，安装 CPU 版 / CPU build."
} elseif ($Cuda) {
  $wantCuda = "$Cuda"
  Info "GPU: 用户指定 --cuda $Cuda / requested cu$Cuda torch."
} else {
  $nv = Get-Command nvidia-smi -ErrorAction SilentlyContinue
  if ($nv) { Info "GPU: 检测到 nvidia-smi → 安装 CUDA 版 torch (cu121) / CUDA build (cu121)."; $wantCuda = "121" } else { Info "GPU: 未检测到 nvidia-smi → CPU 版 torch / CPU build." }
}
if ($wantCuda -in @("121", "118")) {
  $url = "https://download.pytorch.org/whl/cu$wantCuda"
  if ($EnvBackend -eq "uv") {
    Info "uv pip install --python $py torch==2.5.1 --index-url $url"
    uv pip install --python $py "torch==2.5.1" --index-url $url
  } else {
    Info "pip install torch==2.5.1 --index-url $url"
    & $py -m pip install "torch==2.5.1" --index-url $url
  }
  if ($LASTEXITCODE -ne 0) { Fail "CUDA torch 安装失败 / CUDA torch install failed. 重试 --cpu 或核对 CUDA 版本 / try --cpu or verify your CUDA toolkit." }
}

# 5) requirements
if ($EnvBackend -eq "uv") {
  Info "uv pip install -r requirements.txt"
  Push-Location $PyDir
  uv pip install --python $py -r requirements.txt
  $rc = $LASTEXITCODE
  Pop-Location
} else {
  Info "pip install -r requirements.txt"
  Push-Location $PyDir
  & $py -m pip install -r requirements.txt
  $rc = $LASTEXITCODE
  Pop-Location
}
if ($rc -ne 0) { Fail "依赖安装失败 / requirements install failed." }

# 6) model weights (idempotent)
Info "下载模型权重 / downloading model weights (幂等 / idempotent)…"
Push-Location $PyDir
& $py scripts/download_models.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Warn "模型下载未完成 / model download incomplete（可稍后重试 / retry later: python scripts/download_models.py）." }

# 7) IK accuracy self-test
Info "运行 IK 准确率自检 / running IK self-test…"
Push-Location $PyDir
& $py tools/selftest_pipeline.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Warn "自检未通过 / self-test did not pass — 见上方输出 / see output above." }

# 8) environment check
Info "环境自检 / environment check:"
Push-Location $PyDir
& $py tools/check_env.py
Pop-Location

Write-Host ""
if ($EnvBackend -eq "conda") {
  Info "Torch Monkey Python 环境就绪 / Python environment ready (conda)."
  Write-Host "下一步 / Next（每次新开终端都要先激活你的 conda 环境 / activate your conda env each new terminal）:"
  Write-Host "  conda activate <你的环境 / your env>"
  Write-Host "  起 AI 管线服务 / start the pipeline server:    cd python; python server.py"
} else {
  Info "Torch Monkey Python 环境就绪 / Python environment ready."
  Write-Host "下一步 / Next（每次新开终端都要先用 venv 的 python / use the venv python each new terminal）:"
  Write-Host "  起 AI 管线服务 / start the pipeline server:    cd python; .\.venv\Scripts\python.exe server.py"
}
Write-Host "  终端可视化 / terminal dashboard:               python tools/dashboard.py"
Write-Host "  桌面客户端 / desktop client:                   npm run dev"
