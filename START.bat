@echo off
title Kamla Dei App v1.3.1
cd /d "%~dp0"
echo.
echo  Kamla Dei app chalu hocche - browser nije khulbe...
echo  Na khulle jao: http://127.0.0.1:8790
echo.
if exist "python\python.exe" (
    python\python.exe server\app.py
) else (
    python server\app.py
)
pause
