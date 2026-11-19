@echo off
rem Duas sessoes do e-CAC na MESMA planilha, divididas por certificado:
rem   Sessao 1 = so o Save Inteligencia
rem   Sessao 2 = todos os outros certificados
rem Uso: arraste a planilha para cima deste arquivo, ou de dois cliques e cole o caminho.
rem ANTES: feche qualquer outra execucao desta automacao NESTA maquina.
setlocal
cd /d "%~dp0"
set "PLANILHA=%~1"
if "%PLANILHA%"=="" set /p "PLANILHA=Caminho da planilha (.xlsx): "
set "PLANILHA=%PLANILHA:"=%"
if not exist "%PLANILHA%" (
    echo Planilha nao encontrada: %PLANILHA%
    pause
    exit /b 1
)
start "Sessao 1 - Save Inteligencia" cmd /k python -u run.py --planilha "%PLANILHA%" --sessao 1 --certificados "Save Inteligencia"
timeout /t 5 /nobreak >nul
start "Sessao 2 - demais certificados" cmd /k python -u run.py --planilha "%PLANILHA%" --sessao 2 --exceto-certificados "Save Inteligencia"
echo Duas sessoes abertas em janelas separadas. Para parar, feche as duas janelas.
