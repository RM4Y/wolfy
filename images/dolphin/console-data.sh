#!/bin/bash
# Data of Wii console N+1 (N = $1 >= 1), for a session started while console 1 (the PC's
# own data) is in use: ~/.local/share/dolphin-emu/Wolfy/console-<N+1>/dolphin-emu, given to
# Dolphin as its data dir (XDG_DATA_HOME, see dolphin-run.sh).
# - Wii NAND and GameCube memory cards: the console's own. Created as a copy of console 1
#   (saves included); afterwards the NAND follows console 1 (channels, forwarders, Wii
#   settings) except its saves and Miis, which stay the console's own.
# - games settings, textures, shaders, screenshots...: console 1's (symlinks).
# - save states, logs, the rest: the console's own (created by Dolphin).
set -e
SHARED=$HOME/.local/share/dolphin-emu
OWN=$SHARED/Wolfy/console-$(($1 + 1))/dolphin-emu
mkdir -p "$OWN"
for d in Load GameSettings ResourcePacks Shaders Styles Themes ScreenShots Dump Maps; do
    [ -e "$OWN/$d" ] || [ -L "$OWN/$d" ] || ln -s "../../../$d" "$OWN/$d"
done
if [ ! -d "$OWN/Wii" ]; then
    rsync -a "$SHARED/Wii/" "$OWN/Wii.new/" && mv "$OWN/Wii.new" "$OWN/Wii"
    rsync -a "$SHARED/GC/" "$OWN/GC/"
    echo "[console-data] console $(($1 + 1)) created from console 1"
else
    rsync -a --delete --exclude='/title/*/*/data/' --exclude='/shared2/menu/FaceLib/' \
        --exclude='/tmp/' "$SHARED/Wii/" "$OWN/Wii/"
    echo "[console-data] console $(($1 + 1)): NAND updated from console 1 (saves kept)"
fi
