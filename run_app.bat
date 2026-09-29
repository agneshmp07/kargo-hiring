@echo off
REM Kargo hiring app (real data). Set up .env first; see README.md.
cd /d "%~dp0"
start "" http://localhost:8530
python -m shortlister ui
pause
