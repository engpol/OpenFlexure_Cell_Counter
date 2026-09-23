#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# diagnose_server.sh -- work out why the Pi cannot reach the worker.
#
# Run this ON THE SERVER:
#     bash diagnose_server.sh
#
# Read-only: it inspects and reports, it changes nothing.
# ---------------------------------------------------------------------------
set -uo pipefail

LINK_IP="${LINK_IP:-192.168.50.10}"
PI_IP="${PI_IP:-192.168.50.1}"
PORT="${PORT:-8000}"
SERVICE="${SERVICE:-cellcounter-worker}"

ok()   { printf '  [ OK ]  %s\n' "$*"; }
bad()  { printf '  [FAIL]  %s\n' "$*"; }
warn() { printf '  [WARN]  %s\n' "$*"; }
info() { printf '          %s\n' "$*"; }
hdr()  { printf '\n=== %s ===\n' "$*"; }

VERDICT=""

hdr "1. What is listening on port $PORT?"
LISTEN="$(ss -tlnp 2>/dev/null | grep ":$PORT " || true)"
if [[ -z "$LISTEN" ]]; then
    bad "Nothing is listening on port $PORT at all."
    info "This is the direct cause of 'Connection refused'."
    VERDICT="not_running"
else
    echo "$LISTEN" | sed 's/^/          /'
    if echo "$LISTEN" | grep -qE "0\.0\.0\.0:$PORT|\*:$PORT"; then
        ok "Listening on ALL interfaces."
    elif echo "$LISTEN" | grep -q "$LINK_IP:$PORT"; then
        ok "Listening on $LINK_IP -- correct for the direct link."
    elif echo "$LISTEN" | grep -qE "127\.0\.0\.1:$PORT|\[::1\]:$PORT"; then
        bad "Listening on LOOPBACK ONLY (127.0.0.1)."
        info "The server refuses connections arriving on the Ethernet link."
        VERDICT="wrong_bind"
    else
        warn "Listening on an address that is neither $LINK_IP nor loopback."
        VERDICT="wrong_bind"
    fi
fi

hdr "2. Service state"
if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}.service"; then
    STATE="$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
    ENABLED="$(systemctl is-enabled "$SERVICE" 2>/dev/null || echo 'not-enabled')"
    printf '          %s is: %s (boot: %s)\n' "$SERVICE" "$STATE" "$ENABLED"

    if [[ "$ENABLED" != "enabled" ]]; then
        bad "Service is NOT enabled -- it will not start at boot."
        info "Fix:  sudo systemctl enable --now $SERVICE"
    fi

    if [[ "$STATE" == "inactive" ]]; then
        bad "Service is 'inactive (dead)' -- it was never started (it did NOT crash)."
        info "A crash would show 'failed'. This means nothing tried to run it."
        info "Fix:  sudo systemctl enable --now $SERVICE"
        VERDICT="not_started"
    fi

    if [[ "$STATE" == "activating" ]]; then
        bad "Stuck 'activating (auto-restart)' -- it is crash-looping."
        UNIT_FILE="/etc/systemd/system/${SERVICE}.service"
        # Ignore comment lines -- the unit's own comments mention CHANGEME.
        if [[ -f "$UNIT_FILE" ]] \
           && grep -vE '^[[:space:]]*#' "$UNIT_FILE" | grep -q CHANGEME; then
            bad "The unit still contains CHANGEME placeholders:"
            grep -nE '^[[:space:]]*[^#].*CHANGEME' "$UNIT_FILE" | sed 's/^/          /'
            info "Fix:  sudo bash install_service.sh"
        fi
        if systemctl status "$SERVICE" 2>/dev/null | grep -q "203/EXEC"; then
            bad "status=203/EXEC -- systemd cannot execute the ExecStart path."
            info "That path does not exist or is not executable. Check it with:"
            info "  systemctl cat $SERVICE | grep ExecStart"
        fi
        VERDICT="crash_loop"
    fi

    if [[ "$STATE" != "active" ]]; then
        bad "Service is not running."
        info "Last 20 log lines:"
        journalctl -u "$SERVICE" -n 20 --no-pager 2>/dev/null | sed 's/^/          | /'
        [[ -z "$VERDICT" ]] && VERDICT="not_running"
    else
        ok "Service is active."
    fi
else
    warn "No systemd unit named $SERVICE (fine if you start it by hand)."
fi

hdr "2b. Is the INSTALLED unit the current one?"
UF="/etc/systemd/system/${SERVICE}.service"
if [[ -f "$UF" ]]; then
    STALE=0
    for d in ProtectSystem ProtectHome ReadWritePaths CELLPOSE_LOCAL_MODELS_PATH; do
        if grep -qE "^\s*(Environment=)?${d}=" "$UF"; then
            bad "Installed unit still has '${d}=' -- that is the OLD hardened version."
            STALE=1
        fi
    done
    if [[ $STALE -eq 1 ]]; then
        info "That sandboxing blocks CellPose from writing its model weights,"
        info "so startup fails with uvicorn exit status=3."
        info "Fix:  sudo bash install_service.sh     (reinstalls the current unit)"
        VERDICT="stale_unit"
    else
        ok "No stale sandboxing directives."
    fi
    if journalctl -u "$SERVICE" -n 100 --no-pager 2>/dev/null | grep -q "no locator available"; then
        bad "numba cannot write its compile cache ('no locator available')."
        info "cellpose uses @njit(cache=True); numba needs a writable directory."
        info "Fix:  add to the unit ->  Environment=NUMBA_CACHE_DIR=/opt/cell_counter/numba_cache"
        info "      and ensure that directory exists and is owned by the service user."
        info "Also remove ProtectHome=/ProtectSystem= if present."
        VERDICT="numba_cache"
    fi

    if systemctl status "$SERVICE" 2>/dev/null | grep -q "status=3"; then
        bad "status=3 -- uvicorn could not start the application."
        info "That means load_model() raised. The reason is in the journal:"
        info "  journalctl -u $SERVICE -n 50 --no-pager"
        [[ -z "$VERDICT" ]] && VERDICT="startup_failed"
    fi
fi

hdr "3. Network address on the direct link"
if ip -4 addr show 2>/dev/null | grep -q "$LINK_IP"; then
    ok "$LINK_IP is configured on this machine."
    ip -4 addr show 2>/dev/null | grep -B2 "$LINK_IP" | grep -E "^[0-9]+:" | sed 's/^/          /'
else
    bad "$LINK_IP is NOT configured on any interface."
    info "The worker cannot bind to an address the machine does not have."
    ip -4 addr show 2>/dev/null | grep -E "inet " | sed 's/^/          | /'
    VERDICT="no_address"
fi

if ping -c 2 -W 2 "$PI_IP" >/dev/null 2>&1; then
    ok "Pi at $PI_IP responds to ping."
else
    warn "Pi at $PI_IP does not respond to ping."
fi

hdr "4. Can the server reach its own worker?"
for target in "127.0.0.1" "$LINK_IP"; do
    if curl -fsS --max-time 5 "http://$target:$PORT/health" >/dev/null 2>&1; then
        ok "http://$target:$PORT/health responds."
    else
        bad "http://$target:$PORT/health does not respond."
    fi
done

hdr "5. CellPose model weights"
MODELS="${CELLPOSE_LOCAL_MODELS_PATH:-$HOME/.cellpose}/models"
[[ -d "$MODELS" ]] || MODELS="$HOME/.cellpose/models"
if [[ -d "$MODELS" ]] && [[ -n "$(ls -A "$MODELS" 2>/dev/null)" ]]; then
    ok "Weights present in $MODELS"
    ls -1 "$MODELS" | head -5 | sed 's/^/          /'
else
    bad "No model weights in $MODELS"
    info "CellPose downloads these on first use. If this machine has no"
    info "internet, startup fails and nothing listens -- see below."
    [[ -z "$VERDICT" ]] && VERDICT="no_models"
fi

hdr "6. Internet access (needed ONCE, to fetch weights)"
if ping -c 1 -W 3 1.1.1.1 >/dev/null 2>&1; then
    ok "Can reach the internet by IP."
    if getent hosts www.cellpose.org >/dev/null 2>&1; then
        ok "DNS resolves www.cellpose.org."
    else
        bad "DNS resolution FAILS (can ping by IP but not resolve names)."
        info "This is what causes 'Temporary failure in name resolution'."
        info "Check:  cat /etc/resolv.conf   and   nmcli dev show | grep DNS"
        [[ -z "$VERDICT" || "$VERDICT" == "no_models" ]] && VERDICT="no_dns"
    fi
else
    warn "No internet access from this machine."
    info "Fine for normal running -- but the weights must be provisioned once."
    [[ -z "$VERDICT" ]] && VERDICT="no_models"
fi

hdr "7. Token configuration"
EF="/etc/cell_counter/worker.env"
if [[ -f "$EF" ]]; then
    ok "$EF exists ($(stat -c '%U:%G %a' "$EF"))"
    if grep -qE '^\s*export\s' "$EF"; then
        bad "Contains 'export' lines -- systemd EnvironmentFile= wants plain KEY=value."
        info "Fix:  sudo sed -i -E 's/^\\s*export\\s+//' $EF"
    fi
    if ! grep -qE '^\s*CELLCOUNT_TOKEN=..' "$EF"; then
        bad "No usable CELLCOUNT_TOKEN=... line found."
    else
        ok "CELLCOUNT_TOKEN line present."
    fi
    if [[ -r "$EF" ]]; then
        ok "Readable by $(whoami) -- manual runs will pick up the token."
    else
        warn "NOT readable by $(whoami). systemd (root) can still read it, but a"
        info "manual 'python -m uvicorn ...' will generate a THROWAWAY token"
        info "and the Pi will get HTTP 401."
        info "Fix:  sudo chown root:$(id -gn) $EF && sudo chmod 640 $EF"
    fi
else
    warn "$EF does not exist -- the worker will generate an ephemeral token."
fi

hdr "8. Firewall"
if command -v ufw >/dev/null 2>&1; then
    UFW="$(sudo -n ufw status 2>/dev/null || ufw status 2>/dev/null || echo 'unknown')"
    if echo "$UFW" | grep -qi "inactive"; then
        ok "ufw is inactive -- not blocking anything."
    elif echo "$UFW" | grep -q "$PORT"; then
        ok "ufw is active and has a rule for port $PORT."
        echo "$UFW" | grep "$PORT" | sed 's/^/          /'
    else
        warn "ufw is active with no visible rule for port $PORT."
        info "NOTE: a firewall block causes a TIMEOUT, not 'Connection refused'."
    fi
else
    info "ufw not installed."
fi

hdr "VERDICT"
case "$VERDICT" in
  wrong_bind)
    cat <<EOF
  The worker is running but bound to loopback, so it only accepts
  connections from the server itself.

  Fix:
    * systemd:  sudo nano /etc/systemd/system/${SERVICE}.service
                change  --host 127.0.0.1  to  --host $LINK_IP
                sudo systemctl daemon-reload && sudo systemctl restart $SERVICE
    * script :  set HOST=$LINK_IP in run_worker.sh / run_worker.bat
EOF
    ;;
  not_running)
    cat <<EOF
  Nothing is listening, which is exactly what 'Connection refused' means.
  The worker is not running or crashed during startup.

  Most common cause: CellPose cannot write its downloaded model weights.
  Check the logs above for a permission error, then try a manual start:

      source ~/miniforge3/etc/profile.d/conda.sh && conda activate cellcount
      cd /opt/cell_counter && python -m uvicorn worker:app --host $LINK_IP --port $PORT

  If that works but the service does not, it is the service file --
  usually ExecStart paths or ReadWritePaths. See docs/TROUBLESHOOTING.md.
EOF
    ;;
  no_dns)
    cat <<EOF
  This machine can reach the internet by IP but cannot resolve hostnames, so
  CellPose cannot download its model weights and the worker dies at startup.

  Check whether the direct link broke DNS:
      cat /etc/resolv.conf
      nmcli dev show | grep -i dns
      ip route | grep default

  A common cause: the direct-link connection was configured without
  'ipv4.never-default yes', and is now the primary route. Fix with:
      sudo nmcli con mod direct-link ipv4.never-default yes ipv4.dns-priority 200
      sudo nmcli con up direct-link

  Or sidestep it entirely by provisioning the weights offline:
      python fetch_models.py --pack     (on a machine with internet)
      python fetch_models.py --unpack cellpose_models.tar.gz
EOF
    ;;
  no_models)
    cat <<EOF
  The CellPose model weights are missing and this machine cannot download
  them. The worker cannot start without them.

  On a machine WITH internet and cellpose installed:
      python fetch_models.py --pack
  Copy cellpose_models.tar.gz across, then here:
      python fetch_models.py --unpack cellpose_models.tar.gz
      python fetch_models.py --check
EOF
    ;;
  not_started)
    cat <<EOF
  The unit exists but is not running, and status says 'inactive (dead)'
  rather than 'failed' -- so it never crashed, it was simply never started.

  Fix:
      sudo systemctl enable --now $SERVICE
      systemctl status $SERVICE

  'enable' makes it start at boot; '--now' also starts it immediately.
  Installing a unit file does neither on its own.

  If it then shows 'failed', read the reason with:
      journalctl -u $SERVICE -n 30 --no-pager
EOF
    ;;
  crash_loop)
    cat <<EOF
  The service is crash-looping, so it never reaches 'active'.

  Most common cause: the ExecStart path is wrong -- often a leftover CHANGEME
  placeholder, which systemd reports as status=203/EXEC.

  See the exact command systemd is running:
      systemctl cat $SERVICE | grep ExecStart

  Fix it automatically:
      sudo bash install_service.sh

  Or by hand:
      sudo nano /etc/systemd/system/${SERVICE}.service
      sudo systemctl daemon-reload && sudo systemctl restart $SERVICE
EOF
    ;;
  numba_cache)
    cat <<EOF
  numba (used by cellpose) cannot write its compiled-function cache, so
  importing cellpose fails and the worker exits with status=3.

  It works when you run it by hand because your shell can write to
  site-packages and to \$HOME; the service cannot.

  Fix:
      sudo mkdir -p /opt/cell_counter/numba_cache
      sudo chown \$(stat -c %U /opt/cell_counter) /opt/cell_counter/numba_cache
      sudo mkdir -p /etc/systemd/system/${SERVICE}.service.d
      sudo tee /etc/systemd/system/${SERVICE}.service.d/override.conf >/dev/null <<'OVR'
[Service]
Environment=NUMBA_CACHE_DIR=/opt/cell_counter/numba_cache
ProtectHome=
ProtectSystem=
ReadWritePaths=
OVR
      sudo systemctl daemon-reload && sudo systemctl restart $SERVICE
EOF
    ;;
  stale_unit)
    cat <<EOF
  The unit installed in /etc/systemd/system/ is an older, sandboxed version.
  ProtectSystem=strict / ProtectHome=read-only stop CellPose writing its
  downloaded model weights, so startup fails (uvicorn exit status=3).

  Editing CHANGEME in place does not update the rest of the file. Reinstall:

      cd /path/to/repo/server
      sudo bash install_service.sh

  Or strip the sandboxing by hand:
      sudo sed -i '/^ProtectSystem=/d; /^ProtectHome=/d; /^ReadWritePaths=/d; \
                   /CELLPOSE_LOCAL_MODELS_PATH/d' \
          /etc/systemd/system/${SERVICE}.service
      sudo systemctl daemon-reload && sudo systemctl restart $SERVICE
EOF
    ;;
  startup_failed)
    cat <<EOF
  uvicorn exited with status=3: the application failed during startup, which
  means load_model() raised. Read the actual reason:

      journalctl -u $SERVICE -n 50 --no-pager

  Usual causes:
    * CellPose cannot download model weights (no internet)  -> fetch_models.py
    * CellPose cannot WRITE model weights (unit sandboxing) -> install_service.sh
    * CUDA/GPU error                                        -> CELLCOUNT_GPU=0
EOF
    ;;
  no_address)
    cat <<EOF
  $LINK_IP is not configured, so the worker cannot bind to it.
  Re-check the static IP step (docs/SERVER_SETUP.md step 5).
EOF
    ;;
  *)
    cat <<EOF
  No fault found on the server side. If the Pi still cannot connect, run
  this ON THE PI:

      ping -c 3 $LINK_IP
      nc -zv $LINK_IP $PORT
      curl -v http://$LINK_IP:$PORT/health

  'Connection refused'  -> server side, re-run this script
  'No route to host'    -> cabling or addressing
  Timeout / hangs       -> a firewall is dropping packets
EOF
    ;;
esac
echo
