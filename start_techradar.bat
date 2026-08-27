@echo off
title TechRadar Server
cd /d C:\msys64\home\aksha\projects\TechRadar
echo Starting TechRadar on 0.0.0.0:8766 ...
echo Open http://127.0.0.1:8766 to verify, then use http://<YOUR_IP>:8766
echo.
:loop
".venv\Scripts\python.exe" -m techradar.cli web --host 0.0.0.0 --port 8766
echo.
echo ############################################################
echo  Server exited with code %errorlevel%.
echo  If it closed right away, the error is above. Press Ctrl+C
echo  to close, or any key to restart it.
echo ############################################################
pause
goto loop
