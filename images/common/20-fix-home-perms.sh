#!/bin/bash
# Docker creates the parents of our bind mounts (~/.config for ~/.config/eden…)
# as root, so the session user couldn't write its own config dirs.
source /opt/gow/bash-lib/utils.sh
gow_log "Fixing ownership of home parent dirs"
for d in /home/retro/.config /home/retro/.local /home/retro/.local/share; do
    [ -d "$d" ] && chown "${PUID:-1000}:${PGID:-1000}" "$d"
done
true
