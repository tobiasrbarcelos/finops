@echo off
chcp 65001 >nul
title FinOps - Backend (porta 8001)
cd /d "%~dp0backend"
where python >nul 2>nul || (echo [ERRO] Python nao encontrado. Instale o Python 3.11 ou mais novo em python.org e marque "Add to PATH". & pause & exit /b 1)
if not exist .venv (
  echo Criando ambiente virtual...
  python -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
echo Instalando dependencias (a primeira vez demora alguns minutos)...
pip install -q -r requirements-local.txt || (echo [ERRO] Falha no pip install. Copie a mensagem acima. & pause & exit /b 1)
echo.
echo Backend em http://localhost:8001/docs  (Ctrl+C para parar)
uvicorn server:app --reload --port 8001
pause
