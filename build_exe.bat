@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=py -3.12"
%PY% -c "import sys" 2>nul || set "PY=py -3.11"
%PY% -c "import sys" 2>nul || set "PY=python"

echo 使用解释器: %PY%
%PY% -m pip install -r requirements.txt -q
%PY% -m pip install -r requirements-build.txt -q

%PY% -m PyInstaller --noconfirm --clean ImgAspectRatio.spec
if errorlevel 1 (
  echo 打包失败。
  exit /b 1
)
echo.
echo 已生成: %CD%\dist\ImgAspectRatio.exe
pause
