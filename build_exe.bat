@echo off
setlocal

REM Remove previous build outputs
if exist dist\catan_tutor rmdir /S /Q dist\catan_tutor
if exist dist\catan-tutor-windows.zip del /Q dist\catan-tutor-windows.zip
if exist build rmdir /S /Q build
if exist catan_tutor.spec del /Q catan_tutor.spec

pyinstaller ^
  --noconfirm ^
  --onedir ^
  --windowed ^
  --exclude-module PyQt5 ^
  --exclude-module PySide6 ^
  --exclude-module matplotlib ^
  --exclude-module tqdm ^
  --icon assets\logo.ico ^
  catan_tutor.py

REM Copy required folders into dist\catan_tutor
xcopy ai dist\catan_tutor\ai /E /I /Y
xcopy assets dist\catan_tutor\assets /E /I /Y
xcopy controllers dist\catan_tutor\controllers /E /I /Y
xcopy game dist\catan_tutor\game /E /I /Y
xcopy view dist\catan_tutor\view /E /I /Y

REM Copy config into PyInstaller's internal folder
xcopy config dist\catan_tutor\_internal\config /E /I /Y

REM Create release zip (contents only, no extra top-level folder)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -Path 'dist\catan_tutor\*' -DestinationPath 'dist\catan-tutor-windows.zip' -Force"

REM Clean up temporary build artifacts
if exist build rmdir /S /Q build
if exist catan_tutor.spec del /Q catan_tutor.spec

echo.
echo Build complete.
echo Release package: dist\catan-tutor-windows.zip
pause

endlocal