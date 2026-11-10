@echo off
cd /d "%~dp0"
if exist "release\COSLab-0.3.0\COSLab.exe" (
  start "" "release\COSLab-0.3.0\COSLab.exe"
  exit /b 0
)
if exist ".venv-desktop\Scripts\pythonw.exe" (
  start "" ".venv-desktop\Scripts\pythonw.exe" "desktop_app.py"
  exit /b 0
)
echo Build the release or prepare the development environments first.
pause
