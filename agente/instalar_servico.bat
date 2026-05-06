@echo off
color 0A
echo ==================================================
echo Instalando Monitor NFSe como Servico do Windows (NSSM)
echo ==================================================
echo.

:: Pega os caminhos
set EXE_PATH=%~dp0agente.exe
set NSSM_PATH=%~dp0nssm.exe
set SERVICE_NAME=FASPEL_NfN_MONITOR

if not exist "%NSSM_PATH%" (
    color 0C
    echo ERRO: O executavel do NSSM nao foi encontrado no caminho esperado.
    echo Caminho procurado: %NSSM_PATH%
    pause
    exit /b
)

echo 1. Limpando instalacao antiga do Agendador (se existir)...
schtasks /end /tn "%SERVICE_NAME%" 2>nul
schtasks /delete /tn "%SERVICE_NAME%" /f 2>nul

echo.
echo 2. Registrando servico oficial no Windows...
"%NSSM_PATH%" install "%SERVICE_NAME%" "%EXE_PATH%"

echo 3. Configurando parametros...
"%NSSM_PATH%" set "%SERVICE_NAME%" Description "Monitor de Erros NFE Firebird"
"%NSSM_PATH%" set "%SERVICE_NAME%" AppDirectory "%~dp0."
"%NSSM_PATH%" set "%SERVICE_NAME%" AppStdout "%~dp0agente.log"
"%NSSM_PATH%" set "%SERVICE_NAME%" AppStderr "%~dp0agente_error.log"

echo 4. Iniciando o servico...
"%NSSM_PATH%" start "%SERVICE_NAME%"

echo.
echo ==================================================
echo SUCESSO! 
echo O servico foi criado e agora VAI aparecer na sua lista de servicos (services.msc).
echo ==================================================
echo.
pause
