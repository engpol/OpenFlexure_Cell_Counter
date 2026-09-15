@echo off
REM ---------------------------------------------------------------
REM Starts the CellPose worker. Keeps the model warm in memory.
REM Runs entirely as a normal user -- no administrator rights needed.
REM ---------------------------------------------------------------

REM Bind to loopback only. Reaching it from the Pi is handled by the
REM tunnel (see SETUP.md Part B). Change to 0.0.0.0 ONLY if you have a
REM firewall rule permitting inbound connections on this port.
set HOST=192.168.50.10
set PORT=8000

REM Shared secret. Must match the token on the OpenFlexure Raspberry Pi.
REM Generate once with:
REM   python -c "import secrets; print(secrets.token_urlsafe(32))"
if "%CELLCOUNT_TOKEN%"=="" (
    echo ERROR: CELLCOUNT_TOKEN is not set.
    echo Set it as a user environment variable, then reopen this window.
    pause
    exit /b 1
)

REM Set the model and GPU settings.

set CELLCOUNT_MODEL=cyto2
set CELLCOUNT_GPU=auto
set CELLCOUNT_DIAMETER=25

cd /d "%~dp0"
call "%USERPROFILE%\miniforge3\Scripts\activate.bat" cellcount

REM --workers 1 is deliberate: one process holds one warm model.
python -m uvicorn worker:app --host %HOST% --port %PORT% --workers 1

pause
