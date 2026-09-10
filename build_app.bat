@echo off
setlocal
cd /d "%~dp0"

echo Installing PyInstaller...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto error
call ".venv\Scripts\python.exe" -m pip install pyinstaller==6.16.0
if errorlevel 1 goto error

echo Building CheeseFactory...
call ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name CheeseFactory --collect-all customtkinter --hidden-import neural_forecast main.py
if errorlevel 1 goto error

if exist "cheese_factory.db" copy /Y "cheese_factory.db" "dist\CheeseFactory\cheese_factory.db" >nul

echo Creating desktop shortcut...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'CheeseFactory.lnk')); $s.TargetPath='%CD%\dist\CheeseFactory\CheeseFactory.exe'; $s.WorkingDirectory='%CD%\dist\CheeseFactory'; $s.Save()"

echo.
echo BUILD COMPLETED
echo Application: dist\CheeseFactory\CheeseFactory.exe
echo Desktop shortcut: CheeseFactory
pause
exit /b 0

:error
echo.
echo BUILD FAILED
echo Send a screenshot of the error shown above.
pause
exit /b 1
