@echo off
setlocal

cd /d "%~dp0"

set "HOST=%PAYPAL_WEB_HOST%"
if "%HOST%"=="" set "HOST=127.0.0.1"

set "PORT=%PAYPAL_WEB_PORT%"
if "%PORT%"=="" set "PORT=8080"

set "PYTHON_EXE=.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo [1/4] Creating local Python environment...
  py -m venv .venv
  if errorlevel 1 goto :error
)

echo [2/4] Installing dependencies...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/4] Opening browser...
start "" "http://127.0.0.1:%PORT%"

echo [4/4] Starting PayPal web UI on http://%HOST%:%PORT%
echo Press Ctrl+C to stop the server.
"%PYTHON_EXE%" web.py --host "%HOST%" --port "%PORT%"
if errorlevel 1 goto :error

goto :end

:error
echo.
echo Startup failed. Check the error above.
pause
exit /b 1

:end
pause
