@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Gerar o .exe do app de recorte

echo.
echo 1/3  Instalando dependencias...
python -m pip install -U -r requirements.txt || goto :erro

echo.
echo 2/3  Gerando o icone...
python gerar_icone.py || goto :erro

echo.
echo 3/3  Gerando o executavel (pode levar alguns minutos)...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "Recortar Videos" ^
  --icon "assets\icone.ico" ^
  --version-file "assets\versao_win.txt" ^
  --collect-all yt_dlp ^
  --hidden-import yt_dlp ^
  recortar_videos.py || goto :erro

echo.
echo Pronto: dist\Recortar Videos.exe
pause
exit /b 0

:erro
echo.
echo Falhou. Veja a mensagem acima.
pause
exit /b 1
