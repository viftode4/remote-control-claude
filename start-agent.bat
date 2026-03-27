@echo off
echo ============================================
echo   Remote Control Agent - Starting
echo ============================================
echo.

echo Starting the agent UI...
echo Open http://localhost:8510 in your browser.
echo.
echo Press Ctrl+C to stop.
echo.

python -m streamlit run app.py --server.port 8510 --server.headless true
