#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh
gow_log "Starting Dolphin $(cat /opt/dolphin/VERSION) (Better Wii Menu DE): Wii Menu"

# session copy of the PC's Dolphin config, pads set for Wolf (/wolfy-config/dolphin.json);
# NAND, saves and memory cards (~/.local/share/dolphin-emu) are the PC's, mounted by Wolf
python3 /opt/gow/dolphin-setup.py

# gamepad combos (Wolfy > Wii > Configurer): HOME combo = Wii HOME button (Guide).
# The app runs in the host network namespace (Bluetooth for real Wii Remotes): Wolfy is
# reached on localhost, not through the docker gateway
WOLFY_HOOK_HOST=127.0.0.1 python3 /opt/gow/home-combo.py &

source /opt/gow/launch-comp.sh
# Dolphin has no native Wayland support: X11 through XWayland (DISPLAY is set by sway:
# in the host network namespace it is not :0, taken by the PC desktop)
launcher env -u WAYLAND_DISPLAY QT_QPA_PLATFORM=xcb /opt/gow/dolphin-run.sh
