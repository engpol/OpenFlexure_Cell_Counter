#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup_token.sh -- make CELLCOUNT_TOKEN visible to systemd AND to every user.
#
#     sudo bash setup_token.sh              # generate one
#     sudo bash setup_token.sh mytoken123   # or set a specific value
#
# Why two mechanisms are needed
# -----------------------------
# systemd services do NOT read /etc/environment or /etc/profile.d -- a service
# starts with a nearly empty environment by design. Login shells, conversely,
# do not read systemd's EnvironmentFile=. So a single "system environment
# variable" cannot cover both.
#
# The fix is one file, read two ways:
#   * systemd  -> EnvironmentFile=/etc/cell_counter/worker.env
#   * shells   -> /etc/profile.d/cellcounter.sh sources that same file
#
# One source of truth, world-readable, no usernames anywhere.
# ---------------------------------------------------------------------------
set -euo pipefail

ENV_DIR="/etc/cell_counter"
ENV_FILE="$ENV_DIR/worker.env"
PROFILE_FILE="/etc/profile.d/cellcounter.sh"

[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo bash setup_token.sh" >&2; exit 1; }

TOKEN="${1:-}"
if [[ -z "$TOKEN" ]]; then
    TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))' 2>/dev/null \
             || head -c 32 /dev/urandom | base64 | tr -d '/+=' | cut -c1-43)"
fi

mkdir -p "$ENV_DIR"

# Plain KEY=value, no 'export' -- systemd's EnvironmentFile= is not a shell
# script and will not strip it.
printf 'CELLCOUNT_TOKEN=%s\n' "$TOKEN" > "$ENV_FILE"

# World-readable on purpose: this is a single-purpose instrument server, and
# 0600 root:root silently breaks every manual run by a normal user.
chmod 0644 "$ENV_FILE"
chown root:root "$ENV_FILE"

# Make it available in every login shell, for every user.
cat > "$PROFILE_FILE" <<'EOF'
# Cell counter: expose CELLCOUNT_TOKEN to interactive shells.
# systemd reads the same file via EnvironmentFile=, so there is one source
# of truth. Do not put the token directly in here.
if [ -r /etc/cell_counter/worker.env ]; then
    set -a
    . /etc/cell_counter/worker.env
    set +a
fi
EOF
chmod 0644 "$PROFILE_FILE"

echo "Token written to $ENV_FILE (world-readable)"
echo "Shell hook written to $PROFILE_FILE"
echo
echo "Active in NEW shells immediately. For this shell:"
echo "    source $PROFILE_FILE"
echo
echo "If the service is already installed:"
echo "    sudo systemctl restart cellcounter-worker"
echo
echo "Put this on the Pi, in ~/.cell_counter/server.conf:"
echo
echo "    token = $TOKEN"
echo
