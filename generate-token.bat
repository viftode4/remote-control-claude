@echo off
echo ============================================
echo   Generate OAuth Token
echo ============================================
echo.

:: Activate virtual environment
call .venv\Scripts\activate.bat

python -m proxy.server generate-token

echo.
pause
