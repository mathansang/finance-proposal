@echo off
setlocal EnableExtensions
REM 금융권 공고 조사 후 GitHub Pages 배포
REM 사용: batch\publish.bat
REM       batch\publish.bat --skip-fetch

cd /d "%~dp0.."
if errorlevel 1 (
  echo [publish] proposal 루트로 이동 실패
  exit /b 1
)

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
if exist "webapp\.venv\Scripts\python.exe" if not exist ".venv\Scripts\python.exe" set "PYTHON=webapp\.venv\Scripts\python.exe"

echo [publish] %CD%
echo [publish] %PYTHON% -m batch --push %*
"%PYTHON%" -m batch --push %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [publish] 실패 exit=%ERR%
  exit /b %ERR%
)
echo [publish] 완료
exit /b 0
