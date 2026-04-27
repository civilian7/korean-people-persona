# korean-people-persona: parquet 다운로드 + SQLite 변환 (Windows PowerShell)
#
# 요구사항:
#   - Python 3.10 이상 (3.11+ 권장)
#   - 약 5GB 디스크 여유 공간 (parquet ~2GB + DB ~3GB)
#
# 사용법:
#   .\build.ps1
#   .\build.ps1 --force-download
#
# 실행 정책 오류 시:
#   PowerShell -ExecutionPolicy Bypass -File .\build.ps1

[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { 'python' }

if (-not (Get-Command $PythonBin -ErrorAction SilentlyContinue)) {
  Write-Error "$PythonBin(을)를 찾을 수 없습니다."
  exit 1
}

$pyVer = & $PythonBin -c "import sys; print('%d.%d' % sys.version_info[:2])"
$parts = $pyVer.Split('.')
$major = [int]$parts[0]; $minor = [int]$parts[1]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
  Write-Error "Python 3.10 이상이 필요합니다 (현재: $pyVer)"
  exit 1
}
Write-Host "[INFO] Python $pyVer ($PythonBin)"

if (-not (Test-Path '.venv')) {
  Write-Host "[INFO] 가상환경 생성: .venv"
  & $PythonBin -m venv .venv
}

& '.\.venv\Scripts\Activate.ps1'

Write-Host "[INFO] 의존성 설치"
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

Write-Host "[INFO] 변환 시작"
$env:PYTHONPATH = 'src'
if ($Args) {
  python -m convert --download @Args
} else {
  python -m convert --download
}

Write-Host "[DONE] persona.db 생성 완료"
