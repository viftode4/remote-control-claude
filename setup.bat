@echo off
echo ============================================
echo   Remote Control Agent - Setup
echo ============================================
echo.

:: Create virtual environment
echo [1/3] Creating virtual environment...
python -m venv .venv

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Install dependencies
echo [2/3] Installing dependencies...
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt

:: Create .env from example if it doesn't exist
echo [3/3] Checking configuration...
if not exist .env (
    copy .env.example .env >nul
    echo.
    echo   Created .env file from template.
    echo   IMPORTANT: Edit .env and add your ANTHROPIC_API_KEY
    echo.
)

echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo   Next steps:
echo     1. Edit .env and set your ANTHROPIC_API_KEY
echo     2. Run start-agent.bat to start the agent
echo     3. Open http://localhost:8501 in your browser
echo.
echo   Optional (for team use with OAuth proxy):
echo     1. Run start-proxy.bat to start the proxy server
echo     2. Run generate-token.bat to create user tokens
echo.
pause
