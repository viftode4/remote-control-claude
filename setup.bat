@echo off
echo ============================================
echo   Remote Control Agent - Setup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed. Download from https://python.org
    pause
    exit /b 1
)
echo [OK] Python found

:: Check Node
where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed. Download from https://nodejs.org
    pause
    exit /b 1
)
echo [OK] Node.js found

:: Check Claude Code
where claude >nul 2>&1
if errorlevel 1 (
    echo WARNING: Claude Code not found. Install from https://docs.anthropic.com/en/docs/claude-code
    echo          You need Claude Code logged in for authentication.
    echo.
)
if not errorlevel 1 echo [OK] Claude Code found

:: Install Python dependencies
echo.
echo Installing Python dependencies...
pip install -r requirements.txt -q
echo [OK] Dependencies installed

:: Set up proxy
echo.
echo Setting up OAuth proxy...
mkdir "%USERPROFILE%\.claude\proxy" 2>nul
copy proxy\oauth-proxy.js "%USERPROFILE%\.claude\proxy\server.js" >nul 2>&1
echo [OK] Proxy installed

if not exist "%USERPROFILE%\.claude\proxy\config.json" (
    echo {"port": 8082, "host": "127.0.0.1", "default_model": "claude-sonnet-4-6", "max_tokens": 8192} > "%USERPROFILE%\.claude\proxy\config.json"
    echo [OK] Proxy config created
) else (
    echo [OK] Proxy config already exists
)

:: Create .env
if not exist .env (
    copy .env.example .env >nul 2>&1
)

echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo   To run the agent:
echo.
echo     1. Open Terminal 1:   start-proxy.bat
echo     2. Open Terminal 2:   start-agent.bat
echo     3. Open browser:      http://localhost:8510
echo.
pause
