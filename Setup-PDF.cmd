@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_batch.ps1"
if errorlevel 1 (
  echo Setup incomplete. Review the message above.
  pause
) else (
  echo Setup complete. You can now open PDF-from-TXT.cmd.
  pause
)
