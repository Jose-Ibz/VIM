
@echo off
::  Carpeta y script
set "PROY_PATH=C:\Users\Jose\OneDrive - NAUTICA VIAMAR\DATOS\Textos 25\Volvo Penta\Business Plan 2025\Business Plan 25\VPIM\VIM"
set "SCRIPT=vpim_app.py"

cd /d "%PROY_PATH%"  || exit /b

:: Instalar dependencias (salta rápido si ya están)
pip install --quiet -r requirements_vpim.txt

:: ───── ARRANCAR STREAMLIT EN SEGUNDO PLANO ─────
start "" /B streamlit run "%SCRIPT%"

::  El /B evita que aparezca otra ventana,  start lanza el proceso aparte
exit /b
