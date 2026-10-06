#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh
gow_log "Starting Steam (Wolfy)"

# One Steam folder per running session: two Steam clients on the same data corrupt it.
# Each session claims the first free folder with a lock held for its whole life (fd 9 is
# inherited by Steam): folder 1 is config/steam/data, the others config/steam/data-N, each
# with its own Steam install, logged-in accounts and settings. ~/.steam (in the Moonlight
# client's persistent home) points to it. Without /wolfy-steam (app mounts not updated yet
# by Wolfy) ~/.steam is config/steam/data itself, mounted by Wolf: one session at a time.
if [ -d /wolfy-steam ]; then
    SEAT=
    for i in $(seq 1 16); do
        exec 9>"/wolfy-steam/seat-$i.lock"
        if flock -n 9; then SEAT=$i; break; fi
        exec 9>&-
    done
    [ -n "$SEAT" ] || { gow_log "No free Steam folder (16 sessions running)"; exit 1; }
    DATA=/wolfy-steam/data
    [ "$SEAT" -eq 1 ] || DATA=/wolfy-steam/data-$SEAT
    mkdir -p "$DATA/debian-installation"
    touch "$DATA/debian-installation/.cef-enable-remote-debugging"  # Decky Loader
    # a real ~/.steam: the old mount point (empty) or the first-run setup's folders
    if [ -e "$HOME/.steam" ] && [ ! -L "$HOME/.steam" ]; then
        rmdir "$HOME/.steam" 2>/dev/null || mv "$HOME/.steam" "$HOME/.steam.old-$(date +%s)"
    fi
    ln -sfn "$DATA" "$HOME/.steam"
    gow_log "Steam folder $SEAT: $DATA"
else
    exec 9>"$HOME/.steam/.wolfy-session.lock"
    flock -n 9 || { gow_log "Steam is already running in another session: refused"; exit 1; }
fi

# Wolfy settings (/wolfy-config/steam.json): library folders, startup options -> exported
# variables
eval "$(python3 /opt/gow/steam-setup.py prepare)"
python3 /opt/gow/home-combo.py &

exec /opt/gow/steam-startup-gow.sh
