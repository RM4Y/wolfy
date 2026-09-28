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

source /opt/gow/launch-comp.sh
launcher /usr/bin/retroarch --config "$HOME/.config/retroarch/retroarch.cfg"
