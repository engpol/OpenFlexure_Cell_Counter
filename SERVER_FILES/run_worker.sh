#!/usr/bin/env bash
# ---------------------------------------------------------------
# Starts the CellPose worker on Linux. Keeps the model warm in memory.
# For unattended operation use the systemd unit instead -- this script
# is for testing and for running the worker interactively.
# ---------------------------------------------------------------
set -euo pipefail

# Bind to the direct-link address only, so the worker is NOT reachable
# from your institutional network. Use 127.0.0.1 if tunnelling instead.
HOST="${CELLCOUNT_HOST:-192.168.50.10}"
PORT="${CELLCOUNT_PORT:-8000}"

CONDA_ROOT="${CONDA_ROOT:-$HOME/miniforge3}"
ENV_NAME="${ENV_NAME:-cellcount}"

# Load the token from the protected env file if not already set.
#
# Note: systemd reads EnvironmentFile= as root, so the service works with a
# root-owned 0600 file. A MANUAL run as a normal user does not -- which is a
# silent trap, because the worker then generates a throwaway token and the Pi
# gets 401. So report unreadable files loudly rather than skipping them.
ENV_FILE="${ENV_FILE:-/etc/cell_counter/worker.env}"
if [[ -z "${CELLCOUNT_TOKEN:-}" ]]; then
    if [[ -r "$ENV_FILE" ]]; then
        # shellcheck disable=SC1091
        set -a; source "$ENV_FILE"; set +a
    elif [[ -e "$ENV_FILE" ]]; then
        echo "ERROR: $ENV_FILE exists but is not readable by $(whoami)." >&2
        echo "       $(ls -l "$ENV_FILE" 2>/dev/null)" >&2
        echo "  Fix:  sudo chown root:$(id -gn) $ENV_FILE" >&2
        echo "        sudo chmod 640 $ENV_FILE" >&2
        exit 1
    fi
fi

if [[ -z "${CELLCOUNT_TOKEN:-}" ]]; then
    echo "ERROR: CELLCOUNT_TOKEN is not set and $ENV_FILE does not exist." >&2
    echo "Generate one with:" >&2
    echo "  python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"" >&2
    echo "then put it in $ENV_FILE as:  CELLCOUNT_TOKEN=..." >&2
    exit 1
fi

echo "Token loaded (${#CELLCOUNT_TOKEN} chars, ends ...${CELLCOUNT_TOKEN: -6})"

export CELLCOUNT_MODEL="${CELLCOUNT_MODEL:-cyto2}"
export CELLCOUNT_GPU="${CELLCOUNT_GPU:-auto}"
export CELLCOUNT_DIAMETER="${CELLCOUNT_DIAMETER:-25}"

cd "$(dirname "$0")"

# shellcheck disable=SC1091
source "$CONDA_ROOT/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# Report GPU status before starting, so a CPU-only wheel on a GPU machine is
# visible immediately rather than showing up as unexplained slowness.
python check_gpu.py || true

echo "Starting worker on ${HOST}:${PORT} (model ${CELLCOUNT_MODEL})"
# --workers 1 is deliberate: one process holds one warm model.
exec python -m uvicorn worker:app --host "$HOST" --port "$PORT" --workers 1
