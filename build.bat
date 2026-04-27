@echo off
REM korean-people-persona: parquet 다운로드 + SQLite 변환 (Windows cmd)
REM
REM 요구사항:
REM   - Python 3.10 이상 (3.11+ 권장)
REM   - 약 5GB 디스크 여유 공간 (parquet ~2GB + DB ~3GB)
REM
REM 사용법:
REM   build.bat
REM   build.bat --force-download

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if "%PYTHON_BIN%"=="" set "PYTHON_BIN=python"

where %PYTHON_BIN% >nul 2>&1
if errorlevel 1 (
  echo [ERROR] %PYTHON_BIN%^(을^)를 찾을 수 없습니다. 1>&2
  exit /b 1
)

for /f "delims=" %%V in ('%PYTHON_BIN% -c "import sys; print(\"%%d.%%d\" %% sys.version_info[:2])"') do set "PY_VER=%%V"
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
  set "PY_MAJOR=%%A"
  set "PY_MINOR=%%B"
)
if %PY_MAJOR% LSS 3 goto :badver
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 goto :badver
echo [INFO] Python %PY_VER% (%PYTHON_BIN%)

if not exist ".venv" (
  echo [INFO] 가상환경 생성: .venv
  %PYTHON_BIN% -m venv .venv || exit /b 1
)

call ".venv\Scripts\activate.bat"

echo [INFO] 의존성 설치
python -m pip install --upgrade pip --quiet || exit /b 1
python -m pip install -r requirements.txt --quiet || exit /b 1

echo [INFO] 변환 시작
set "PYTHONPATH=src"
python -m convert --download %* || exit /b 1

echo [DONE] persona.db 생성 완료
exit /b 0

:badver
echo [ERROR] Python 3.10 이상이 필요합니다 ^(현재: %PY_VER%^) 1>&2
exit /b 1
