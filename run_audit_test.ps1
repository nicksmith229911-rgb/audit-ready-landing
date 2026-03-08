# Triple AI Audit Test Runner (PowerShell)
Write-Host "🚀 Triple AI Audit Test Runner" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found. Please install Python 3.8+ and add to PATH" -ForegroundColor Red
    Write-Host "💡 Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if virtual environment exists
if (-not (Test-Path "venv")) {
    Write-Host "📦 Creating virtual environment..." -ForegroundColor Blue
    python -m venv venv
}

# Activate virtual environment
Write-Host "🔧 Activating virtual environment..." -ForegroundColor Blue
& .\venv\Scripts\Activate.ps1

# Install dependencies
Write-Host "📥 Installing dependencies..." -ForegroundColor Blue
pip install -r requirements.txt

# Run the test
Write-Host "🧪 Running Triple AI Audit Test..." -ForegroundColor Magenta
python test_audit_enhanced.py

Write-Host "✅ Test complete! Check audit_results.json for detailed results." -ForegroundColor Green
Read-Host "Press Enter to exit"
