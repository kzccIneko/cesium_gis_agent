$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$pythonExe = (Get-Command py -ErrorAction Stop).Source
$venvDir = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
  & $pythonExe -3 -m venv $venvDir
}

if (-not (Test-Path $venvPython)) {
  throw "未能创建 Python 虚拟环境：$venvPython"
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
& $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
