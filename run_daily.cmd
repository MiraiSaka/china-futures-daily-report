@echo off
rem Public generation-only entry point. No delivery integration is included.
setlocal
if "%PYTHON_EXE%"=="" (
    set "PY=python"
) else (
    set "PY=%PYTHON_EXE%"
)
set "JOB=%~dp0"
set "PYTHONIOENCODING=utf-8"
set "KMP_DUPLICATE_LIB_OK=TRUE"
set "CHROMEDL_HEADLESS=1"
cd /d "%JOB%"
"%PY%" "%JOB%daily_job.py" %*
exit /b %errorlevel%
