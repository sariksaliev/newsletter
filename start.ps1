# TG Outreach Platform — one-click start (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "Installing dependencies..."
& $python -m pip install -q -r requirements.txt

if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example..."
    Copy-Item ".env.example" ".env"
    Write-Host "Fill TELEGRAM_API_ID, TELEGRAM_API_HASH, ANTHROPIC_API_KEY in .env"
}

Write-Host "Seeding database..."
& $python run.py seed

Write-Host ""
Write-Host "Starting server at http://localhost:8000"
Write-Host "Dashboard: http://localhost:8000"
Write-Host "API docs:  http://localhost:8000/docs"
Write-Host ""
& $python run.py serve
