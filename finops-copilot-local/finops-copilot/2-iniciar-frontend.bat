@echo off
chcp 65001 >nul
title FinOps - Frontend (porta 3000)
cd /d "%~dp0frontend"
where node >nul 2>nul || (echo [ERRO] Node.js nao encontrado. Instale o Node 20 LTS em nodejs.org. & pause & exit /b 1)
where yarn >nul 2>nul || (echo Instalando yarn... & call npm install -g yarn)
if exist node_modules goto iniciar
echo Instalando dependencias - a primeira vez demora alguns minutos...
call yarn install
if errorlevel 1 (echo [ERRO] Falha no yarn install. & pause & exit /b 1)
:iniciar
echo.
echo Frontend em http://localhost:3000 - Ctrl+C para parar
call yarn start
pause
