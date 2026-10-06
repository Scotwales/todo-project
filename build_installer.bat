@echo off
setlocal
cd /d "%~dp0"
where ISCC.exe >nul 2>nul
if not errorlevel 1 set "ISCC=ISCC.exe"
if not defined ISCC set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" if defined ProgramFiles(x86) set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 compiler ISCC.exe was not found.
  echo Install Inno Setup 6, then run this file again.
  exit /b 1
)
if not exist "dist\Daily\Daily.exe" (
  echo Build the application first with build_exe.bat.
  exit /b 1
)
"%ISCC%" "installer\Daily.iss"
if errorlevel 1 exit /b 1
echo Installer created in dist\installer\
