# Runs the monitor headless (no console window).
Set-Location (Split-Path $PSScriptRoot -Parent)
Start-Process -FilePath ".\venv\Scripts\pythonw.exe" -ArgumentList "-m", "src.main"
