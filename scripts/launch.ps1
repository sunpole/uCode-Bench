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
. (Join-Path $PSScriptRoot 'runtime_probe.ps1')
$pythonPath = Find-UCodePython -Candidates $candidates
if (-not $pythonPath) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('Не найден Python с ReportLab, pypdf и Pillow. Запустите Setup-PDF.cmd или прочтите README.md. Автоматическая установка не выполнялась.', 'uCode') | Out-Null
    exit 2
}
$popplerDir = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin'
if (Test-Path -LiteralPath $popplerDir -PathType Container) { $env:PATH = $popplerDir + ';' + $env:PATH }
if ($Action -in @('gui', 'batch')) {
    if (-not (Test-UCodePythonImports -PythonPath $pythonPath -Modules 'tkinter')) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show('В выбранном Python отсутствует tkinter. Выберите Python для Windows с tkinter или запустите Setup-PDF.cmd.', 'uCode') | Out-Null
        exit 2
    }
    $pythonWindowed = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
    if (Test-Path -LiteralPath $pythonWindowed -PathType Leaf) {
        Start-Process -FilePath $pythonWindowed -ArgumentList '-m','ucode',$Action -WorkingDirectory $projectRoot -WindowStyle Normal
        exit 0
    }
}
& $pythonPath -m ucode $Action @ExtraArgs
exit $LASTEXITCODE
