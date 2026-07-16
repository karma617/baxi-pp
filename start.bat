@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "HOST=%PAYPAL_WEB_HOST%"
if "%HOST%"=="" set "HOST=127.0.0.1"

set "PORT=%PAYPAL_WEB_PORT%"
if "%PORT%"=="" set "PORT=18765"

set "PYTHON_EXE=.venv\Scripts\python.exe"
set "PY_LAUNCHER="

where py >nul 2>nul && set "PY_LAUNCHER=py -3"
if not defined PY_LAUNCHER (
  where python >nul 2>nul && set "PY_LAUNCHER=python"
)
if not defined PY_LAUNCHER (
  echo [ERROR] Python not found. Install Python 3.10+ and add py/python to PATH.
  goto :error
)

if not exist "%PYTHON_EXE%" (
  echo [1/5] Creating local Python environment...
  %PY_LAUNCHER% -m venv .venv
  if errorlevel 1 goto :error
) else (
  echo [1/5] Reusing local Python environment...
)

echo [2/5] Installing dependencies...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/5] Checking port %PORT%...
call :free_port "%PORT%"
if errorlevel 1 goto :error

echo [4/5] Opening browser after short delay...
start "" cmd /c "ping -n 3 127.0.0.1 >nul & start http://127.0.0.1:%PORT%"

echo [5/5] Starting PayPal web UI on http://%HOST%:%PORT%
echo Press Ctrl+C to stop the server.
"%PYTHON_EXE%" web.py --host "%HOST%" --port "%PORT%"
if errorlevel 1 goto :error

goto :end

:free_port
set "TARGET_PORT=%~1"
set "PORT_PIDS="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort %TARGET_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"`) do (
  set "PORT_PIDS=1"
  echo Port %TARGET_PORT% is occupied by PID %%P. Stopping it...
  taskkill /F /PID %%P >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Failed to stop PID %%P on port %TARGET_PORT%.
    exit /b 1
  )
)
if not defined PORT_PIDS echo Port %TARGET_PORT% is available.
exit /b 0

:error
echo.
echo Startup failed. Check the error above.
pause
exit /b 1

:end
pause
