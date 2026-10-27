function Test-UCodePythonImports {
    param([string]$PythonPath, [string]$Modules = 'reportlab, pypdf, PIL')
    $process = New-Object System.Diagnostics.Process
    try {
        $process.StartInfo.FileName = $PythonPath
        $process.StartInfo.Arguments = '-c "import ' + $Modules + '"'
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        $null = $process.Start()
        if (-not $process.WaitForExit(10000)) { $process.Kill(); $process.WaitForExit(); return $false }
        return $process.ExitCode -eq 0
    } catch { return $false }
    finally { $process.Dispose() }
}

function Find-UCodePython {
    param([string[]]$Candidates)
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            if (Test-UCodePythonImports -PythonPath $candidate) { return $candidate }
        }
    }
    return $null
}
