# Creates venv, installs dependencies, downloads the MediaPipe pose model.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path "venv")) { python -m venv venv }
& .\venv\Scripts\python.exe -m pip install --upgrade pip
& .\venv\Scripts\python.exe -m pip install -r requirements.txt
$model = "models\pose_landmarker_lite.task"
if (-not (Test-Path $model)) {
  $url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
  Invoke-WebRequest -Uri $url -OutFile $model
}
Write-Host "Setup complete. Activate with: .\venv\Scripts\Activate.ps1"
