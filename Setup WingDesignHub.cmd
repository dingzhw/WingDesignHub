@echo off
cd /d "%~dp0"
py -3 -m venv .bootstrap
if errorlevel 1 goto error
.bootstrap\Scripts\python.exe -m pip install uv==0.13.8
if errorlevel 1 goto error
set "UV_PYTHON_INSTALL_DIR=%CD%\.runtime\python"
set "UV_CACHE_DIR=%CD%\.cache\uv"
.bootstrap\Scripts\uv.exe venv --python 3.13.18 .venv
if errorlevel 1 goto error
.bootstrap\Scripts\uv.exe pip install --python .venv\Scripts\python.exe -r requirements-lock.txt
if errorlevel 1 goto error
.bootstrap\Scripts\uv.exe pip install --python .venv\Scripts\python.exe --no-deps -e .
if errorlevel 1 goto error
echo Setup completed. Double click the WingDesignHub launcher.
pause
exit /b 0
:error
echo Setup failed. Keep this window for diagnostics. Python 3 is required for initial setup.
pause
exit /b 1
