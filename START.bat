@echo off
title Kamla Dei App v1.3.3
cd /d "%~dp0"
echo.
echo  Kamla Dei app chalu hocche - browser nije khulbe...
echo  Na khulle jao: http://127.0.0.1:8790
echo.
if exist "python\python.exe" (
    python\python.exe server\app.py
    goto :done
)
py -3 --version >nul 2>nul
if %errorlevel%==0 (
    py -3 server\app.py
    goto :done
)
python --version >nul 2>nul
if %errorlevel%==0 (
    python server\app.py
    goto :done
)
echo  Python paoa jayni - Python 3.12 download hocche, ektu wait...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip' -OutFile 'py-embed.zip'; Expand-Archive -Path 'py-embed.zip' -DestinationPath 'python' -Force"
if exist "python\python.exe" (
    python\python.exe server\app.py
) else (
    echo  Python setup hoyni - python.org theke Python install kore abar chalao.
)
:done
pause
