# Explicit, project-local setup for the TXT->PDF UI (not called by normal launch).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$venv = Join-Path $root '.venv\Scripts\python.exe'
$env:PIP_CACHE_DIR = Join-Path $root '.pip-cache'
$env:PYTHONUTF8 = '1'

if (Test-Path -LiteralPath $venv -PathType Leaf) {
    & $venv -c 'import reportlab, pypdf, PIL'
    if ($LASTEXITCODE -eq 0) {
        Write-Host 'Project Python is ready. Start PDF-from-TXT.cmd'
        exit 0
    }
}
if (-not (Test-Path -LiteralPath $venv -PathType Leaf)) {
    $candidates = @()
    if ($env:UCODE_PYTHON) {
        $candidates += ,@($env:UCODE_PYTHON)
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { $candidates += ,@($py.Source, '-3') }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { $candidates += ,@($python.Source) }
    $selected = $null
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { continue }
        $extra = @()
        if ($candidate.Count -gt 1) { $extra = @($candidate[1..($candidate.Count - 1)]) }
        & $exe @extra -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $selected = $candidate
            break
        }
    }
    if (-not $selected) {
        Write-Host 'Python 3.10+ is required. Install official Python from https://www.python.org/downloads/windows/'
        exit 2
    }
    $exe = $selected[0]
    $extra = @()
    if ($selected.Count -gt 1) { $extra = @($selected[1..($selected.Count - 1)]) }
    & $exe @extra -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if (-not (Test-Path -LiteralPath $venv -PathType Leaf)) {
    Write-Host 'Failed to create project virtual environment'
    exit 2
}
Write-Host 'Installing ReportLab, pypdf and Pillow in project .venv only...'
& $venv -m pip install --disable-pip-version-check --no-input -e "$root"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $venv -c 'import reportlab, pypdf, PIL'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Success. Open PDF-from-TXT.cmd'
exit 0
