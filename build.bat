@echo off
setlocal
cd /d "%~dp0"
echo ===== FindIt: step 1 of 3 - installing tools =====
python -m pip install -r requirements.txt || goto :fail
python make_icon.py || goto :fail

echo.
echo ===== step 2 of 3 - building FindIt (fast-start version) =====
python -m PyInstaller --noconfirm --clean --onedir --windowed --name FindIt --icon findit.ico ^
  --add-data "findit.ico;." --add-data "findit.png;." ^
  --collect-all customtkinter --collect-submodules watchdog --collect-submodules pystray ^
  --collect-submodules send2trash --collect-all pymupdf --hidden-import PIL._tkinter_finder ^
  findit.py || goto :fail

echo.
echo ===== step 3 of 3 - building the installer (optional) =====
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" installer.iss || goto :fail
    echo.
    echo DONE!
    echo   Program:   dist\FindIt\FindIt.exe
    echo   Installer: Output\FindIt-Setup.exe   ^(give this one to people^)
) else (
    echo Inno Setup not found, so no installer was made.
    echo Get it free from https://jrsoftware.org/isdl.php then run build.bat again.
    echo.
    echo DONE!  Program: dist\FindIt\FindIt.exe
)
pause
exit /b 0

:fail
echo.
echo Something went wrong - read the messages above.
pause
exit /b 1
