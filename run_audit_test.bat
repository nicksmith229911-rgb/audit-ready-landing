@echo off
echo 🚀 Triple AI Audit Test Runner
echo ================================

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python not found. Please install Python 3.8+ and add to PATH
    echo 💡 Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo ✅ Python found

REM Check if virtual environment exists
if not exist "venv" (
    echo 📦 Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
python -m pip install -r requirements.txt

REM Run the test
echo Running Triple AI Audit Test...
python test_audit_enhanced.py

echo Test complete! Check audit_results.json for detailed results.
pause
