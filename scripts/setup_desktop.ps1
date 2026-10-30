$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
& (Join-Path $PSScriptRoot 'setup_batch.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PIP_CACHE_DIR = Join-Path $root '.pip-cache'
& $python -m pip install --disable-pip-version-check --no-input -e '.[desktop]'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Desktop ready. Start-uCode.cmd. Requires Microsoft WebView2 Runtime; browser fallback: Start-uCode-Browser.cmd.'
