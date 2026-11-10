@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-COSLab.ps1"
if errorlevel 1 (
  echo Installation failed. Please read the message above.
  pause
  exit /b 1
)
pause
