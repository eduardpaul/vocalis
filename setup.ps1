# Vocalis Service Installation and Setup Script for Windows PowerShell
$ErrorActionPreference = "Stop"

Write-Host "===============================================" -ForegroundColor Green
Write-Host "  VOCALIS ASSISTANT SERVICE SETUP (WINDOWS)     " -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green

# 1. Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Found Python: $pythonVersion"
} catch {
    Write-Host "Error: Python was not found. Please install Python 3.11+ first." -ForegroundColor Red
    exit 1
}

# 2. Setup virtual environment
Write-Host "`nStep 1: Setting up Python Virtual Environment (.venv)..." -ForegroundColor Green
if (-not (Test-Path -Path ".venv")) {
    python -m venv .venv
    Write-Host "Virtual environment created."
} else {
    Write-Host "Virtual environment already exists."
}

# 3. Upgrade pip & Install requirements
Write-Host "`nStep 2: Installing Python dependencies..." -ForegroundColor Green
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\pip.exe install -r requirements.txt

# 4. Download ML Models
Write-Host "`nStep 3: Downloading required ML models..." -ForegroundColor Green
& .venv\Scripts\python.exe scripts\download_models.py

# 5. Create background startup commands
Write-Host "`nStep 4: Creating Windows background startup helper..." -ForegroundColor Green
$currentDir = Get-Location
$scriptPath = Join-Path $currentDir "vocalis_start.bat"
$scriptContent = @"
@echo off
cd /d "$currentDir"
start "Vocalis Assistant" /min "%CD%\.venv\Scripts\python.exe" -m vocalis.main
"@

Set-Content -Path $scriptPath -Value $scriptContent
Write-Host "Generated startup batch helper: $scriptPath"

Write-Host "`n===============================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE!                              " -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green
Write-Host "To run Vocalis in the background manually:"
Write-Host "  Double-click '$scriptPath' (it will run minimized)."
Write-Host ""
Write-Host "To configure Vocalis to start automatically on login:"
Write-Host "  1. Press Win + R, type 'shell:startup', and press Enter."
Write-Host "  2. Create a shortcut to '$scriptPath' in that folder."
Write-Host ""
Write-Host "Alternatively, to register as a system task to run on boot:"
Write-Host "  Open PowerShell as Administrator and run:"
Write-Host "  schtasks /create /tn `"VocalisService`" /tr `"$scriptPath`" /sc onstart /ru SYSTEM" -ForegroundColor Yellow
Write-Host "==============================================="
