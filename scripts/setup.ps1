# Creates venv, installs dependencies, downloads the MediaPipe pose model.
# Needs Python 3.11 or 3.12 (MediaPipe has no wheels for newer versions yet). It tries,
# in order: the py launcher (3.12, then 3.11), uv (downloads 3.12 if needed), and a
# plain `python` on PATH if that is 3.11/3.12.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Checked([string]$what, [scriptblock]$cmd) {
  & $cmd
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

function Test-Python([string[]]$cmd) {
  try {
    # Keep $rest an array: `$exe, $rest = $cmd` makes it a plain string when there is
    # one extra argument, and Windows PowerShell 5.1 then drops it when splatting, so
    # `py -3.12` silently ran the default Python instead.
    $exe = $cmd[0]
    $rest = @($cmd | Select-Object -Skip 1)
    $v = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    return ($LASTEXITCODE -eq 0) -and ($v -in @("3.11", "3.12"))
  } catch { return $false }
}

function New-Venv {
  foreach ($ver in @("3.12", "3.11")) {
    if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-Python @("py", "-$ver"))) {
      Write-Host "Creating venv with py -$ver"
      Invoke-Checked "py -$ver -m venv" { py "-$ver" -m venv venv }
      return
    }
  }
  if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Creating venv with uv (Python 3.12)"
    Invoke-Checked "uv venv" { uv venv venv --python 3.12 --seed }
    return
  }
  if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-Python @("python"))) {
    Write-Host "Creating venv with python on PATH"
    Invoke-Checked "python -m venv" { python -m venv venv }
    return
  }
  throw @"
No Python 3.11 or 3.12 found. Install one of:
  - Python 3.12 from https://www.python.org/downloads/ (tick 'py launcher'), or
  - uv: powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
then run this script again.
"@
}

if (-not (Test-Path "venv\Scripts\python.exe")) { New-Venv }
elseif (-not (Test-Python @(".\venv\Scripts\python.exe"))) {
  throw "venv\ exists but isn't Python 3.11/3.12. Delete the venv folder and run this script again."
}

Invoke-Checked "pip upgrade" { & .\venv\Scripts\python.exe -m pip install --upgrade pip }
Invoke-Checked "pip install" { & .\venv\Scripts\python.exe -m pip install -r requirements.txt }

$model = "models\pose_landmarker_lite.task"
if (-not (Test-Path $model)) {
  $url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
  Write-Host "Downloading pose model"
  Invoke-WebRequest -Uri $url -OutFile $model
}
Write-Host "Setup complete. Activate with: .\venv\Scripts\Activate.ps1"
