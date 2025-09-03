@echo off
setlocal enableextensions

REM ====== Aller à la racine du projet ======
cd /d "%~dp0"

REM ====== Paramètres ======
set APP_NAME=MediaSolver
set ENTRY=MediaSolverTray.py
set VENV_DIR=.buildvenv

REM (Optionnel) Chemin des Modules BMD (utile à l'analyse PyInstaller)
set BMD_MODULES=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules

REM ====== Nettoyage ancien build ======
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
del /q "%APP_NAME%.spec" 2>nul

REM ====== Créer et activer un venv propre ======
where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher "py" introuvable. Installe Python 3.11+ et relance.
  exit /b 1
)

py -3 -m venv "%VENV_DIR%"
if errorlevel 1 (
  echo [ERROR] Echec creation venv.
  exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] Echec activation venv.
  exit /b 1
)

REM ====== Installer les dependances ======
python -m pip install --upgrade pip
if errorlevel 1 goto pip_fail

REM Flask + serveur + systray + Resolve binding
pip install pyinstaller flask jinja2 werkzeug click itsdangerous pybmd psutil pystray pillow
if errorlevel 1 goto pip_fail

REM ====== Build PyInstaller ======
pyinstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name "%APP_NAME%" ^
  --icon static\images\MediaSolver.ico ^
  --hidden-import pystray._win32 ^
  --hidden-import ensure_mediasolver_safe ^
  --collect-all flask ^
  --collect-all jinja2 ^
  --collect-all tkinter ^
  --collect-submodules pybmd ^
  --collect-submodules PIL ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --paths "%BMD_MODULES%" ^
  "%ENTRY%"

if errorlevel 1 (
  echo.
  echo [BUILD] Echec du build PyInstaller.
  goto end
)

echo.
echo [BUILD] OK !
echo   -> EXE : .\dist\%APP_NAME%.exe
echo.
echo Rappels:
echo  - Lancer DaVinci Resolve avant d'utiliser l'EXE.
echo  - Si Resolve n'est pas installe dans le chemin par defaut,
echo    definir RESOLVE_SCRIPT_API vers fusionscript.dll.
echo    Ex:  setx RESOLVE_SCRIPT_API "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
echo.

goto end

:pip_fail
echo [ERROR] Echec d'installation des dependances (pip). Verifie ta connexion et retente.

:end
endlocal
