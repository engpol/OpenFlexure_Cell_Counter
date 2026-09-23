#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install_service.sh -- install the worker as a systemd service, correctly.
#
#     sudo bash install_service.sh
#
# Fills in the placeholders in cellcounter-worker.service, fixes permissions on
# the token file, creates the model directory, then enables, starts and VERIFIES
# the service. Safe to re-run.
# ---------------------------------------------------------------------------
set -euo pipefail

SERVICE_NAME="cellcounter-worker"
INSTALL_DIR="${INSTALL_DIR:-/opt/cell_counter}"
ENV_DIR="/etc/cell_counter"
ENV_FILE="$ENV_DIR/worker.env"
BIND_HOST="${BIND_HOST:-192.168.50.10}"
BIND_PORT="${BIND_PORT:-8000}"

die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
ok()  { printf '  [ OK ]  %s\n' "$*"; }
info(){ printf '          %s\n' "$*"; }
hdr() { printf '\n=== %s ===\n' "$*"; }

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo bash install_service.sh"

# The user the worker runs as -- the human who invoked sudo, not root.
RUN_USER="${RUN_USER:-${SUDO_USER:-}}"
[[ -n "$RUN_USER" ]] || die "Cannot determine the target user. Set RUN_USER=yourname."
id "$RUN_USER" >/dev/null 2>&1 || die "No such user: $RUN_USER"
RUN_GROUP="$(id -gn "$RUN_USER")"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"

hdr "1. Locating the Python interpreter"
PYTHON="${PYTHON:-$RUN_HOME/miniforge3/envs/cellcount/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    # Try a few other common layouts before giving up.
    for cand in "$RUN_HOME"/{miniforge3,mambaforge,miniconda3,anaconda3}/envs/cellcount/bin/python; do
        [[ -x "$cand" ]] && PYTHON="$cand" && break
    done
fi
[[ -x "$PYTHON" ]] || die "Could not find the cellcount environment's python.
       Looked for: $RUN_HOME/miniforge3/envs/cellcount/bin/python
       Set it explicitly:  sudo PYTHON=/path/to/python bash install_service.sh"
ok "$PYTHON"

"$PYTHON" -c "import cellpose, fastapi, uvicorn" 2>/dev/null \
    || die "That interpreter cannot import cellpose/fastapi/uvicorn.
       Activate the env and run: pip install -r requirements.txt"
ok "cellpose, fastapi and uvicorn all import"

hdr "2. Installing files to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/numba_cache"
for f in worker.py check_gpu.py benchmark.py fetch_models.py requirements.txt; do
    [[ -f "$f" ]] && install -m 0644 -o "$RUN_USER" -g "$RUN_GROUP" "$f" "$INSTALL_DIR/"
done
chown -R "$RUN_USER:$RUN_GROUP" "$INSTALL_DIR"
ok "Files installed, owned by $RUN_USER"
ok "numba cache dir: $INSTALL_DIR/numba_cache (writable by the service)"

hdr "3. Token file"
mkdir -p "$ENV_DIR"
if [[ -f "$ENV_FILE" ]]; then
    ok "$ENV_FILE already exists -- keeping it"
else
    TOKEN="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))')"
    printf 'CELLCOUNT_TOKEN=%s\n' "$TOKEN" > "$ENV_FILE"
    ok "Generated a new token"
fi

# Validate the format. systemd's EnvironmentFile= is NOT a shell script:
# 'export FOO=bar' lines are not parsed the way people expect.
if grep -qE '^\s*export\s' "$ENV_FILE"; then
    printf '\n'
    info "WARNING: $ENV_FILE contains 'export' lines."
    info "systemd EnvironmentFile= expects plain KEY=value, without 'export'."
    info "Removing 'export' prefixes now."
    sed -i -E 's/^\s*export\s+//' "$ENV_FILE"
fi
grep -qE '^\s*CELLCOUNT_TOKEN=..' "$ENV_FILE" \
    || die "$ENV_FILE has no usable CELLCOUNT_TOKEN=... line."

# World-readable on purpose: single-purpose instrument server, and 0600
# root:root silently breaks manual runs by any normal user.
chown root:root "$ENV_FILE"
chmod 0644 "$ENV_FILE"
ok "Permissions: $(stat -c '%U:%G %a' "$ENV_FILE") (readable by everyone)"

# Also expose it to login shells -- systemd does NOT read /etc/profile.d, and
# shells do NOT read systemd's EnvironmentFile=, so both are needed.
cat > /etc/profile.d/cellcounter.sh <<'PROFILE'
if [ -r /etc/cell_counter/worker.env ]; then
    set -a
    . /etc/cell_counter/worker.env
    set +a
fi
PROFILE
chmod 0644 /etc/profile.d/cellcounter.sh
ok "Shell hook written to /etc/profile.d/cellcounter.sh"

hdr "4. Writing the systemd unit"
[[ -f cellcounter-worker.service ]] || die "cellcounter-worker.service not found here."
UNIT="/etc/systemd/system/${SERVICE_NAME}.service"
sed -e "s|^User=.*|User=$RUN_USER|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|" \
    -e "s|^ExecStart=.*|ExecStart=$PYTHON -m uvicorn worker:app --host $BIND_HOST --port $BIND_PORT --workers 1|" \
    -e "s|^Environment=NUMBA_CACHE_DIR=.*|Environment=NUMBA_CACHE_DIR=$INSTALL_DIR/numba_cache|" \
    cellcounter-worker.service > "$UNIT"
chmod 0644 "$UNIT"

# Belt and braces: a leftover placeholder produces status=203/EXEC, which is
# an obscure way to learn that a sed expression did not match.
#
# Only ACTIVE lines count. The unit's own comments explain the CHANGEME
# placeholder, so a whole-file grep matches those comments and aborts every
# install no matter how correct the substitution was.
if grep -vE '^[[:space:]]*#' "$UNIT" | grep -q "CHANGEME"; then
    grep -nE '^[[:space:]]*[^#].*CHANGEME' "$UNIT" | sed 's/^/          /'
    die "The unit still contains CHANGEME after substitution.
       Edit $UNIT by hand, replacing CHANGEME with: $RUN_USER"
fi
EXEC_BIN="$(awk -F'ExecStart=' '/^ExecStart=/{print $2}' "$UNIT" | awk '{print $1}')"
[[ -x "$EXEC_BIN" ]] || die "ExecStart points at a non-executable path:
       $EXEC_BIN
       Set it explicitly:  sudo PYTHON=/path/to/python bash install_service.sh"
ok "ExecStart binary verified executable: $EXEC_BIN"
ok "Wrote $UNIT"
info "User=$RUN_USER"
info "ExecStart=$PYTHON -m uvicorn worker:app --host $BIND_HOST --port $BIND_PORT"

systemd-analyze verify "$UNIT" 2>&1 | grep -v "^$" | sed 's/^/          /' || true

hdr "5. Model weights"
if [[ -n "$(ls -A "$RUN_HOME/.cellpose/models" 2>/dev/null)" ]]; then
    ok "Weights present in $RUN_HOME/.cellpose/models"
else
    info "No weights found. The service will try to download them at first"
    info "start, which needs internet. If that is not available:"
    info "    python fetch_models.py --pack   (on a connected machine)"
    info "    python fetch_models.py --unpack cellpose_models.tar.gz"
fi

hdr "6. Starting the service"
systemctl daemon-reload

# 'enable' is what makes it start at boot. If the unit has no [Install]
# section this fails, and the service will run now but never after a reboot --
# so do not hide the error.
if ! systemctl enable "$SERVICE_NAME" 2>&1 | sed 's/^/          /'; then
    die "systemctl enable failed -- check the unit has a [Install] section
       with WantedBy=multi-user.target"
fi
ENABLED="$(systemctl is-enabled "$SERVICE_NAME" 2>/dev/null || echo unknown)"
[[ "$ENABLED" == "enabled" ]] || die "Service is '$ENABLED', not 'enabled'.
       It would not start after a reboot."
ok "Enabled at boot"

systemctl restart "$SERVICE_NAME"

printf '          waiting for startup (model load can take ~30 s)'
for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 "http://$BIND_HOST:$BIND_PORT/health" >/dev/null 2>&1; then
        break
    fi
    printf '.'; sleep 1
done
printf '\n'

hdr "7. Verifying"
if curl -fsS --max-time 5 "http://$BIND_HOST:$BIND_PORT/health" 2>/dev/null; then
    printf '\n'
    ok "Service is up and answering on $BIND_HOST:$BIND_PORT"
    ok "Enabled at boot: $(systemctl is-enabled "$SERVICE_NAME" 2>/dev/null)"
    TOKEN_VALUE="$(grep -E '^\s*CELLCOUNT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
    printf '\n'
    printf 'Put this in ~/.cell_counter/server.conf ON THE PI:\n\n'
    printf '    url = http://%s:%s\n' "$BIND_HOST" "$BIND_PORT"
    printf '    token = %s\n\n' "$TOKEN_VALUE"
    printf 'Then from the Pi:  curl http://%s:%s/health\n\n' "$BIND_HOST" "$BIND_PORT"
else
    printf '\n'
    printf 'Service did not come up. Last 30 log lines:\n\n'
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager | sed 's/^/  | /'
    printf '\nSee docs/TROUBLESHOOTING.md\n'
    exit 1
fi
