#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh
gow_log "Starting Steam (Wolfy)"

# Wolfy settings (/wolfy-config/steam.json): one session at a time on the shared Steam data
# (~/.steam is config/steam/data), library folders, startup options -> exported variables
SETUP=$(python3 /opt/gow/steam-setup.py prepare) || {
    gow_log "Steam is already running in another session: refused"
    exit 1
}
eval "$SETUP"
python3 /opt/gow/steam-setup.py heartbeat &
python3 /opt/gow/home-combo.py &

exec /opt/gow/steam-startup-gow.sh
