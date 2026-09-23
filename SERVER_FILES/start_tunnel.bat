@echo off
REM ---------------------------------------------------------------
REM Reverse SSH tunnel: server -> Raspberry Pi.
REM The server makes an OUTBOUND connection, so no inbound firewall
REM rule and no administrator rights are needed on the server.
REM After this runs, the Pi can reach the worker at http://127.0.0.1:8000
REM PI_HOST is the Pi's address on the direct Ethernet link (see DIRECT_LINK.md).
REM ---------------------------------------------------------------

set PI_USER=openflexure
set PI_HOST=192.168.50.1
set KEY=%USERPROFILE%\.ssh\ofm_tunnel
set PORT=8000

:loop
echo [%date% %time%] Connecting tunnel to %PI_USER%@%PI_HOST% ...
ssh -N -T ^
    -i "%KEY%" ^
    -o ServerAliveInterval=30 ^
    -o ServerAliveCountMax=3 ^
    -o ExitOnForwardFailure=yes ^
    -o StrictHostKeyChecking=accept-new ^
    -R %PORT%:127.0.0.1:%PORT% ^
    %PI_USER%@%PI_HOST%

echo [%date% %time%] Tunnel dropped. Reconnecting in 10s...
timeout /t 10 /nobreak >nul
goto loop
