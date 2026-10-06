#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh

# One Wii console per running session: two Dolphins writing the same NAND (Wii saves,
# settings) or memory cards would corrupt them. Each session claims the first free console
# with a lock held for its whole life (fd 9 is inherited by sway and Dolphin); the locks
# live in the Dolphin data dir every session shares. Console 1 is the PC's own data
# (~/.local/share/dolphin-emu, mounted by Wolf); the others are set up by console-data.sh.
SHARED=$HOME/.local/share/dolphin-emu
mkdir -p "$SHARED/Wolfy"
SLOT=
for i in $(seq 0 15); do
    exec 9>"$SHARED/Wolfy/console-$((i + 1)).lock"
    if flock -n 9; then SLOT=$i; break; fi
    exec 9>&-
done
[ -n "$SLOT" ] || { gow_log "No free Wii console (16 sessions running)"; exit 1; }
echo "$SLOT" > /tmp/wolfy-console  # read by host-pads.py
export WOLFY_CONSOLE=$SLOT
[ "$SLOT" -eq 0 ] || /opt/gow/console-data.sh "$SLOT"

# session copy of the PC's Dolphin config, pads set for Wolf (/wolfy-config/dolphin.json)
python3 /opt/gow/dolphin-setup.py

# gamepad combos (Wolfy > Wii > Configurer): HOME combo = Wii HOME button (Guide).
# The app runs in the host network namespace (Bluetooth for real Wii Remotes): Wolfy is
# reached on localhost, not through the docker gateway
WOLFY_HOOK_HOST=127.0.0.1 python3 /opt/gow/home-combo.py &

gow_log "Starting Dolphin $(cat /opt/dolphin/VERSION) (Better Wii Menu DE): Wii Menu, console $((SLOT + 1))"
source /opt/gow/launch-comp.sh
# Dolphin has no native Wayland support: X11 through XWayland (DISPLAY is set by sway:
# in the host network namespace it is not :0, taken by the PC desktop)
launcher env -u WAYLAND_DISPLAY QT_QPA_PLATFORM=xcb /opt/gow/dolphin-run.sh
