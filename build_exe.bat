@echo off
setlocal

REM Remove previous build outputs
if exist dist\play_game rmdir /S /Q dist\play_game
if exist dist\catan-tutor-windows.zip del /Q dist\catan-tutor-windows.zip
if exist build rmdir /S /Q build
if exist play_game.spec del /Q play_game.spec

pyinstaller ^
  --noconfirm ^
  --onedir ^
  --windowed ^
  --exclude-module PyQt5 ^
  --exclude-module PySide6 ^
  --exclude-module matplotlib ^
  --exclude-module tqdm ^
  --icon assets\logo.ico ^
  play_game.py

REM Copy required folders into dist\play_game
xcopy ai dist\play_game\ai /E /I /Y
xcopy assets dist\play_game\assets /E /I /Y
xcopy controllers dist\play_game\controllers /E /I /Y
xcopy game dist\play_game\game /E /I /Y
xcopy view dist\play_game\view /E /I /Y

REM Copy config into PyInstaller's internal folder
xcopy config dist\play_game\_internal\config /E /I /Y

REM Create release zip (contents only, no extra top-level folder)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -Path 'dist\play_game\*' -DestinationPath 'dist\catan-tutor-windows.zip' -Force"

REM Clean up temporary build artifacts
if exist build rmdir /S /Q build
if exist play_game.spec del /Q play_game.spec

echo.
echo Build complete.
echo Release package: dist\catan-tutor-windows.zip
pause

endlocal