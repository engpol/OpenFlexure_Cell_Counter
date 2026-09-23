#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# check_service_env.sh -- show what the SERVICE actually gets, versus what a
# manual run gets, and find the difference that breaks the import.
#
#     sudo bash check_service_env.sh
#
# Read-only. Changes nothing.
# ---------------------------------------------------------------------------
set -uo pipefail

SERVICE="${SERVICE:-cellcounter-worker}"

hdr()  { printf '\n=== %s ===\n' "$*"; }
ok()   { printf '  [ OK ]  %s\n' "$*"; }
bad()  { printf '  [FAIL]  %s\n' "$*"; }
info() { printf '          %s\n' "$*"; }

hdr "1. Every file contributing to this unit"
systemctl cat "$SERVICE" 2>/dev/null | grep -E '^#|^\[|^[A-Za-z]+=' \
    | sed 's/^/          /' || { bad "Unit not found"; exit 1; }

hdr "2. EFFECTIVE settings (what systemd will really apply)"
# This is the authoritative view. If a drop-in did not take effect, it shows
# here -- unlike 'systemctl cat', which lists files rather than the result.
for prop in User Group WorkingDirectory ProtectHome ProtectSystem \
            ReadWritePaths PrivateTmp Environment EnvironmentFiles; do
    VAL="$(systemctl show "$SERVICE" -p "$prop" --value 2>/dev/null)"
    printf '  %-18s %s\n' "$prop" "${VAL:-<empty>}"
done

SVC_USER="$(systemctl show "$SERVICE" -p User --value 2>/dev/null)"
SVC_USER="${SVC_USER:-root}"
PROT_HOME="$(systemctl show "$SERVICE" -p ProtectHome --value 2>/dev/null)"
PROT_SYS="$(systemctl show "$SERVICE" -p ProtectSystem --value 2>/dev/null)"
ENVS="$(systemctl show "$SERVICE" -p Environment --value 2>/dev/null)"

hdr "3. Verdict on the numba cache problem"
FOUND=0

if [[ "$PROT_HOME" != "" && "$PROT_HOME" != "no" ]]; then
    bad "ProtectHome=$PROT_HOME is STILL ACTIVE."
    info "The conda env lives under /home, so numba cannot write its cache"
    info "into site-packages, and ~/.cache is read-only too."
    FOUND=1
fi
if [[ "$PROT_SYS" != "" && "$PROT_SYS" != "no" ]]; then
    bad "ProtectSystem=$PROT_SYS is STILL ACTIVE."
    FOUND=1
fi
if [[ "$ENVS" == *"NUMBA_CACHE_DIR"* ]]; then
    CACHE_DIR="$(printf '%s\n' "$ENVS" | tr ' ' '\n' | grep '^NUMBA_CACHE_DIR=' | cut -d= -f2-)"
    ok "NUMBA_CACHE_DIR is set: $CACHE_DIR"
    if [[ -d "$CACHE_DIR" ]]; then
        ok "Directory exists"
        if sudo -u "$SVC_USER" test -w "$CACHE_DIR" 2>/dev/null; then
            ok "Writable by the service user ($SVC_USER)"
        else
            bad "NOT writable by $SVC_USER -- numba will fall through and fail."
            info "Fix:  sudo chown -R $SVC_USER $CACHE_DIR"
            FOUND=1
        fi
    else
        bad "Directory does NOT exist: $CACHE_DIR"
        info "Fix:  sudo mkdir -p $CACHE_DIR && sudo chown -R $SVC_USER $CACHE_DIR"
        FOUND=1
    fi
else
    bad "NUMBA_CACHE_DIR is NOT in the effective environment."
    info "Your drop-in did not take effect. Check for typos in the path:"
    info "  /etc/systemd/system/${SERVICE}.service.d/override.conf"
    info "and that you ran:  sudo systemctl daemon-reload"
    FOUND=1
fi

hdr "4. Live import test AS THE SERVICE USER"
EXEC_BIN="$(systemctl show "$SERVICE" -p ExecStart --value 2>/dev/null \
            | tr ' ' '\n' | grep -m1 'bin/python' || true)"
if [[ -z "$EXEC_BIN" ]]; then
    EXEC_BIN="$(systemctl cat "$SERVICE" 2>/dev/null | awk -F'ExecStart=' \
        '/^ExecStart=/{print $2}' | awk '{print $1}' | head -1)"
fi
info "Interpreter: ${EXEC_BIN:-<not found>}"

if [[ -x "$EXEC_BIN" ]]; then
    printf '\n  a) plain (no NUMBA_CACHE_DIR):\n'
    sudo -u "$SVC_USER" env -u NUMBA_CACHE_DIR "$EXEC_BIN" -c \
        'import cellpose; print("     import OK")' 2>&1 | tail -3 | sed 's/^/     /'

    printf '\n  b) with NUMBA_CACHE_DIR set:\n'
    sudo -u "$SVC_USER" env NUMBA_CACHE_DIR="${CACHE_DIR:-/tmp/numba_probe}" \
        "$EXEC_BIN" -c 'import cellpose; print("     import OK")' 2>&1 \
        | tail -3 | sed 's/^/     /'

    printf '\n  If (b) prints "import OK" but the service still fails, the service\n'
    printf '  is not receiving that variable -- see section 2 above.\n'
fi

hdr "5. Writability of the candidate cache locations (as $SVC_USER)"
SITE_PKGS="$("$EXEC_BIN" -c 'import cellpose,os;print(os.path.dirname(cellpose.__file__))' 2>/dev/null || echo '')"
SVC_HOME="$(getent passwd "$SVC_USER" | cut -d: -f6)"
for d in "$SITE_PKGS" "$SVC_HOME/.cache" "${CACHE_DIR:-}"; do
    [[ -z "$d" ]] && continue
    if sudo -u "$SVC_USER" test -w "$d" 2>/dev/null; then
        ok "writable: $d"
    else
        bad "NOT writable: $d"
    fi
done

if [[ $FOUND -eq 0 ]]; then
    printf '\n  Nothing obviously wrong in the unit. Compare sections 4a and 4b:\n'
    printf '  if BOTH fail, the problem is the environment/permissions of the\n'
    printf '  user itself, not systemd.\n\n'
fi
