@echo off
echo Starting OAuth proxy...
echo.

where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed. Download from https://nodejs.org
    pause
    exit /b 1
)

if exist "%USERPROFILE%\.claude\proxy\server.js" (
    node "%USERPROFILE%\.claude\proxy\server.js"
) else (
    echo Proxy not installed yet. Setting it up now...
    mkdir "%USERPROFILE%\.claude\proxy" 2>nul
    copy "proxy\oauth-proxy.js" "%USERPROFILE%\.claude\proxy\server.js" >nul

    if not exist "%USERPROFILE%\.claude\proxy\config.json" (
        echo {"port": 8082, "host": "127.0.0.1", "default_model": "claude-sonnet-4-6", "max_tokens": 8192} > "%USERPROFILE%\.claude\proxy\config.json"
    )

    echo Proxy installed. Starting...
    node "%USERPROFILE%\.claude\proxy\server.js"
)
