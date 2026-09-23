#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# firstboot_setup.sh -- configure a fresh or cloned analysis server.
#
#     sudo bash firstboot_setup.sh
#
# Handles everything that CANNOT be baked into a disk image because it differs
# per machine: the Ethernet interface name, the user account, the auth token,
# and the systemd unit paths.
#
# Safe to re-run.
# ---------------------------------------------------------------------------
set -euo pipefail

LINK_IP="${LINK_IP:-192.168.50.10}"
PI_IP="${PI_IP:-192.168.50.1}"
PORT="${PORT:-8000}"
CON_NAME="direct-link"

hdr()  { printf '\n=== %s ===\n' "$*"; }
ok()   { printf '  [ OK ]  %s\n' "$*"; }
bad()  { printf '  [FAIL]  %s\n' "$*"; }
info() { printf '          %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo bash firstboot_setup.sh"

RUN_USER="${SUDO_USER:-}"
[[ -n "$RUN_USER" ]] || die "Run via sudo from your normal account."

cat <<BANNER

  OpenFlexure Cell Counter -- server first-boot setup
  ==================================================
  Configuring for user: $RUN_USER
  Direct link: this machine $LINK_IP  <-->  microscope $PI_IP

BANNER

# ---------------------------------------------------------------------------
hdr "1. Choose the Ethernet port for the microscope"
# Interface names are hardware-dependent (enp3s0, eno1, enx001122...), so a
# cloned image can never have the right one baked in. Detect and ask.
DEFAULT_IF="$(ip route show default 2>/dev/null | awk '{print $5}' | head -1)"
mapfile -t IFACES < <(ls /sys/class/net | grep -vE '^(lo|docker|veth|br-|virbr|wl)' )

[[ ${#IFACES[@]} -gt 0 ]] || die "No wired network interfaces found."

echo "  Wired interfaces on this machine:"
for i in "${!IFACES[@]}"; do
    n="${IFACES[$i]}"
    carrier="$(cat "/sys/class/net/$n/carrier" 2>/dev/null || echo 0)"
    [[ "$carrier" == "1" ]] && state="cable connected" || state="no cable"
    [[ "$n" == "$DEFAULT_IF" ]] && note="  <-- currently your INTERNET connection" || note=""
    printf '    %d) %-14s %-18s%s\n' "$((i+1))" "$n" "$state" "$note"
done

# Prefer a connected interface that is NOT the default route.
SUGGEST=""
for n in "${IFACES[@]}"; do
    [[ "$n" == "$DEFAULT_IF" ]] && continue
    [[ "$(cat "/sys/class/net/$n/carrier" 2>/dev/null || echo 0)" == "1" ]] && SUGGEST="$n" && break
done
[[ -z "$SUGGEST" ]] && for n in "${IFACES[@]}"; do
    [[ "$n" != "$DEFAULT_IF" ]] && SUGGEST="$n" && break
done

echo
read -r -p "  Which interface goes to the microscope? [${SUGGEST}] " CHOICE
CHOICE="${CHOICE:-$SUGGEST}"
if [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
    CHOICE="${IFACES[$((CHOICE-1))]}"
fi
[[ -e "/sys/class/net/$CHOICE" ]] || die "No such interface: $CHOICE"
[[ "$CHOICE" != "$DEFAULT_IF" ]] || {
    read -r -p "  That is your internet connection. Really use it? [y/N] " yn
    [[ "${yn,,}" == "y" ]] || die "Aborted."
}
ok "Using $CHOICE"

# ---------------------------------------------------------------------------
hdr "2. Static address on that interface"
nmcli con delete "$CON_NAME" >/dev/null 2>&1 || true
nmcli con add type ethernet ifname "$CHOICE" con-name "$CON_NAME" \
    ipv4.method manual \
    ipv4.addresses "$LINK_IP/24" \
    ipv4.never-default yes \
    ipv4.dns-priority 200 \
    connection.autoconnect yes >/dev/null
nmcli con up "$CON_NAME" >/dev/null 2>&1 || true
ok "$LINK_IP/24 on $CHOICE, no default route, low DNS priority"
info "ipv4.never-default stops this link hijacking your internet routing."

# ---------------------------------------------------------------------------
hdr "3. Auth token"
ENV_FILE="/etc/cell_counter/worker.env"
mkdir -p /etc/cell_counter
if [[ -f "$ENV_FILE" ]] && grep -qE '^\s*CELLCOUNT_TOKEN=..' "$ENV_FILE"; then
    ok "Existing token kept"
else
    TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    printf 'CELLCOUNT_TOKEN=%s\n' "$TOKEN" > "$ENV_FILE"
    ok "New token generated"
fi
chmod 0644 "$ENV_FILE"; chown root:root "$ENV_FILE"
cat > /etc/profile.d/cellcounter.sh <<'EOF'
if [ -r /etc/cell_counter/worker.env ]; then
    set -a; . /etc/cell_counter/worker.env; set +a
fi
EOF
chmod 0644 /etc/profile.d/cellcounter.sh
ok "Readable by systemd and by every login shell"

# ---------------------------------------------------------------------------
hdr "4. Worker service"
if [[ -f install_service.sh ]]; then
    BIND_HOST="$LINK_IP" BIND_PORT="$PORT" RUN_USER="$RUN_USER" \
        bash install_service.sh
else
    bad "install_service.sh not found in $(pwd)"
    info "cd into the repo's server/ directory and re-run."
    exit 1
fi

# ---------------------------------------------------------------------------
hdr "5. Summary"
TOKEN_VALUE="$(grep -E '^\s*CELLCOUNT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
cat <<SUMMARY

  Server ready.

  On the RASPBERRY PI, put this in ~/.cell_counter/server.conf:

      url = http://$LINK_IP:$PORT
      token = $TOKEN_VALUE

  Then from the Pi:

      curl http://$LINK_IP:$PORT/health
      python3 Server_Workflow.py

  If anything misbehaves:

      sudo bash diagnose_server.sh

SUMMARY
