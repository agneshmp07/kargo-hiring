@echo off
REM Kargo hiring demo: fictional candidates, never sends anything.
cd /d "%~dp0"
python -m pip install -q -r requirements-local.txt
start "" http://localhost:8531
python -m shortlister demo %*
pause
