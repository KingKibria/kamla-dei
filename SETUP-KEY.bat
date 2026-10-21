@echo off
title Kamla Dei - API Key Setup
cd /d "%~dp0"
echo.
echo  Kamla Dei - Brain Key Setup (Groq + Xkiro)
echo  ------------------------------------------
echo  Key sudhu tomar ei PC-tei save hobe - kothao jabena.
echo  Ekadhik key thakle comma diye ek line-e paste koro.
echo  Kono provider skip korte chaile faka rekhe Enter dao.
echo.
set /p GROQKEY=Groq key(s): 
set /p XKIROKEY=Xkiro key(s): 
if "%GROQKEY%"=="" if "%XKIROKEY%"=="" (
    echo Kono key dao ni - kichu save holo na.
    pause
    exit /b
)
if exist kamla.env del kamla.env
if not "%GROQKEY%"=="" >>kamla.env echo GROQ_API_KEYS=%GROQKEY%
if not "%XKIROKEY%"=="" >>kamla.env echo KAMLA_API_KEYS=%XKIROKEY%
echo.
echo  Saved! Ekhon START.bat chalao (cholte thakle age bondho koro)
pause
