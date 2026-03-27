@echo off
echo ============================================
echo   Remote Control Agent - Starting
echo ============================================
echo.

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Load .env if it exists
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "line=%%A"
        if not "!line:~0,1!"=="#" (
            set "%%A=%%B"
        )
    )
)

echo Starting the agent UI...
echo Open http://localhost:8501 in your browser.
echo.
echo Press Ctrl+C to stop.
echo.

python -m streamlit run computer_use_demo/streamlit.py --server.port 8501
