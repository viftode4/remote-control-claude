@echo off
echo ============================================
echo   OAuth Proxy - Starting
echo ============================================
echo.

where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed.
    echo Download it from https://nodejs.org
    pause
    exit /b 1
)

if exist "%USERPROFILE%\.claude\proxy\server.js" (
    echo Starting proxy from Claude Code installation...
    node "%USERPROFILE%\.claude\proxy\server.js"
) else (
    echo ERROR: Proxy not found at %USERPROFILE%\.claude\proxy\server.js
    echo.
    echo See README.md "Proxy Setup" section for installation instructions.
    pause
    exit /b 1
)
