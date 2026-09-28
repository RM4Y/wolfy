#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh
gow_log "Starting RetroArch (PlayStation)"

# Everything lives in the host's flatpak RetroArch dir, mounted at the same
# "~/.var/app/..." path the config uses (+ /home/remy/... for playlist core
# paths). Each session runs on its own copy of retroarch.cfg so concurrent
# sessions don't overwrite each other's config on exit; saves, states, cores,
# BIOS, playlists and thumbnails stay shared.
RA=$HOME/.var/app/org.libretro.RetroArch/config/retroarch
mkdir -p "$HOME/.config/retroarch"
cp "$RA/retroarch.cfg" "$HOME/.config/retroarch/retroarch.cfg"

# gamepad combos (Wolfy > PlayStation > Configurer): Guide = RetroArch menu
python3 /opt/gow/home-combo.py &

source /opt/gow/launch-comp.sh
# detailed log kept on the host (the container is deleted when the session ends)
LOG="$RA/logs/wolf-session-${WOLF_SESSION_ID: -4}.log"
mkdir -p "$RA/logs"
# X11 (XWayland) rather than native Wayland, as on the PC: in Wayland mode RetroArch
# died when switching from the menu to a game (video restart for the core)
launcher env -u WAYLAND_DISPLAY DISPLAY=:0 /usr/bin/retroarch --verbose --log-file "$LOG" --config "$HOME/.config/retroarch/retroarch.cfg"
