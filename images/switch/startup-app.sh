#!/bin/bash
# Wolf app "Switch": HOME menu of the Switch emulator (/opt/emu: Eglantine, or Lichii);
# wolfy-launcher.py runs the menu and each game (Switch 1 or 2) in processes of their own. Data:
# config/switch (cfg, data), mounted on ~/.config/eden and ~/.local/share/eden; Eglantine reads
# ~/.config/eglantine and ~/.local/share/eglantine: links to them (a real folder there would be
# empty, and with no config folder at all Eglantine opens its migration dialog).
set -e
source /opt/gow/bash-lib/utils.sh
for base in "$HOME/.config" "$HOME/.local/share"; do
    if [ -e "$base/eglantine" ] && [ ! -L "$base/eglantine" ]; then
        mv "$base/eglantine" "$base/eglantine.old.$(date +%s)"
    fi
    ln -sfn eden "$base/eglantine"
done
CFG=$HOME/.config/eden/qt-config.ini
touch "$CFG"
set_key() {  # set_key section key value
    grep -q "^\[$1\]" "$CFG" || printf '\n[%s]\n' "$1" >>"$CFG"
    sed -i "/^${2//\\/\\\\}\\\\default=/d; /^${2//\\/\\\\}=/d" "$CFG"
    sed -i "/^\[$1\]/a ${2//\\/\\\\}\\\\default=false\n${2//\\/\\\\}=$3" "$CFG"
}
set_key UI fullscreen true
# closing a game from the menu ends its process (SIGTERM): no "stop the game?" question
set_key UI confirmStop 2
set_key Audio output_engine 2
set_key Audio output_device auto
IFACE=$(awk '$2 == "00000000" {print $1; exit}' /proc/net/route)
set_key Services network_interface "${IFACE:-eth0}"
# the HOME menu asks who plays before each game only in this layout (12 GiB, as a Switch 2)
set_key Core memory_layout_mode 4
# return-to-HOME combo and quit combo (Wolfy › Émulateurs › Switch); the emulator hotkey that a
# Guide combo would also trigger is freed first
export HOME_COMBO_SETTINGS=$HOME/.config/eden/wolfy/combo.json
python3 /opt/gow/home-combo.py --patch-config "$CFG" || true
python3 /opt/gow/home-combo.py &
mkdir -p "$HOME/.local/share/eden/log"
gow_log "Starting the HOME menu of $(head -1 /opt/emu/VERSION 2>/dev/null)"
source /opt/gow/launch-comp.sh
launcher python3 /opt/wolfy-launcher.py /opt/emu/AppRun ">>$HOME/.local/share/eden/log/wolfy-launcher.log" "2>&1"
