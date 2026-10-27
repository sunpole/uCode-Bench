param([Parameter(Position=0)][string]$Action = 'gui', [Parameter(ValueFromRemainingArguments=$true)][string[]]$ExtraArgs)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$candidates = @(
    $env:UCODE_PYTHON,
    (Join-Path $projectRoot '.venv\Scripts\python.exe'),
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
)
$systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
if ($systemPython) { $candidates += $systemPython.Source }
$pythonPath = $null
foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        & $candidate -c 'import reportlab, pypdf, PIL' 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonPath = $candidate; break }
    }
}
if (-not $pythonPath) {
    Write-Host 'Python with ReportLab, pypdf and Pillow not found. Nothing was installed. See README.md.'
    exit 2
}
$popplerDir = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin'
if (Test-Path -LiteralPath $popplerDir -PathType Container) { $env:PATH = $popplerDir + ';' + $env:PATH }
& $pythonPath -m ucode $Action @ExtraArgs
exit $LASTEXITCODE
