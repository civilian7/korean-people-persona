#!/usr/bin/env bash
# korean-people-persona: parquet 다운로드 + SQLite 변환 (Linux / macOS)
#
# 요구사항:
#   - Python 3.10 이상 (3.11+ 권장)
#   - 약 5GB 디스크 여유 공간 (parquet ~2GB + DB ~3GB)
#
# 사용법:
#   ./build.sh                # 기본 빌드 (parquet 누락 시 자동 다운로드)
#   ./build.sh --force-download   # parquet 재다운로드

set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR=".venv"

# --- 파이썬 버전 확인 ---
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[ERROR] python3가 설치되지 않았습니다." >&2
  exit 1
fi

PY_VER=$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "[ERROR] Python 3.10 이상이 필요합니다 (현재: $PY_VER)" >&2
  exit 1
fi
echo "[INFO] Python $PY_VER ($PYTHON_BIN)"

# --- venv 준비 ---
if [ ! -d "$VENV_DIR" ]; then
  echo "[INFO] 가상환경 생성: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo "[INFO] 의존성 설치"
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

# --- 변환 실행 ---
echo "[INFO] 변환 시작"
PYTHONPATH=src python -m convert --download "$@"

echo "[DONE] persona.db 생성 완료"
