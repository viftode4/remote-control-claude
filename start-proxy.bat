@echo off
echo ============================================
echo   OAuth Proxy Server - Starting
echo ============================================
echo.

:: Activate virtual environment
call .venv\Scripts\activate.bat

echo Starting proxy server on port 9090...
echo Health check: http://localhost:9090/health
echo.
echo Press Ctrl+C to stop.
echo.

python -m proxy.server
