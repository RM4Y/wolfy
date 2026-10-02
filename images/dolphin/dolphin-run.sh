#!/bin/bash
# Wii System Menu, started again when emulation stops (Back + Guide, or a game quit to
# nowhere): the session stays on the Wii Menu until Moonlight quits (Wolfy quit combo).
# Gives up after 3 quick failures in a row (broken NAND / config) instead of looping.
SYSTEM_MENU=0000000100000002
# detailed log kept on the host (the container is deleted when the session ends)
LOG="$HOME/.local/share/dolphin-emu/Logs/wolf-session-${WOLF_SESSION_ID: -4}.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
# The app runs in the host network namespace (Bluetooth): X11 abstract sockets are per
# network namespace, so ":N" could reach the PC desktop's X server ("Authorization
# required"). Use the session's Xwayland socket (DISPLAY set by sway) by its path instead.
echo "=== sway DISPLAY=$DISPLAY, X sockets: $(ls /tmp/.X11-unix 2>&1 | tr '\n' ' ')"
n="${DISPLAY#:}"
sock="/tmp/.X11-unix/X${n%%.*}"  # ":0.0" -> X0
for _ in $(seq 20); do [ -S "$sock" ] && break; sleep 0.5; done
export DISPLAY="$sock"
echo "=== $(date '+%F %T') session ${WOLF_SESSION_ID} DISPLAY=$DISPLAY"
fails=0
while [ "$fails" -lt 3 ]; do
    start=$(date +%s)
    echo "--- $(date '+%T') dolphin-emu --batch --nand_title=$SYSTEM_MENU"
    # SDL finds pads by watching /dev/input (inotify) rather than udev: the PC gamepads'
    # nodes are created by host-pads.py, not announced by Wolf's fake udev
    SDL_JOYSTICK_DISABLE_UDEV=1 /opt/dolphin/bin/dolphin-emu --batch --nand_title="$SYSTEM_MENU" \
        -C Logger.Options.WriteToConsole=True -C Logger.Options.Verbosity=3 \
        -C Logger.Logs.BOOT=True -C Logger.Logs.CORE=True -C Logger.Logs.IOS_ES=True \
        -C Logger.Logs.VIDEO=True -C Logger.Logs.HOST_GPU=True
    echo "--- dolphin-emu exited with code $?"
    if [ $(( $(date +%s) - start )) -lt 10 ]; then fails=$((fails + 1)); else fails=0; fi
    sleep 1
done
echo "[dolphin-run] Dolphin keeps failing to start the Wii Menu, giving up" >&2
