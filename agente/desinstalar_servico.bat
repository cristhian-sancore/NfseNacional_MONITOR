@echo off
color 0E
echo ==================================================
echo Desinstalando Monitor NFSe (Servico NSSM)
echo ==================================================
echo.

set NSSM_PATH=%~dp0nssm.exe
set SERVICE_NAME=FASPEL_NfN_MONITOR

echo 1. Parando o servico...
"%NSSM_PATH%" stop "%SERVICE_NAME%"

echo 2. Removendo do Windows...
"%NSSM_PATH%" remove "%SERVICE_NAME%" confirm

echo.
echo ==================================================
echo SUCESSO! 
echo O servico foi removido da sua maquina.
echo ==================================================
echo.
pause
