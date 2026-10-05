#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh

# Per-session copy of the shared Eden settings (mounted read-only): several
# sessions can run at once without fighting over qt-config.ini, and each gets
# its own multiplayer nickname (the room refuses duplicates) with the house
# room pre-filled in Multiplayer > Direct Connect.
CFG=$HOME/.config/eden
rm -rf "$CFG" && mkdir -p "$CFG" && cp -r /eden-config-host/. "$CFG/"
NICK="Joueur-${WOLF_SESSION_ID: -4}"
set_key() {  # set_key section key value
    sed -i "/^${2//\\/\\\\}\\\\default=/d; /^${2//\\/\\\\}=/d" "$CFG/qt-config.ini"
    sed -i "/^\[$1\]/a ${2//\\/\\\\}\\\\default=false\n${2//\\/\\\\}=$3" "$CFG/qt-config.ini"
}
set_ui() { set_key UI "$1" "$2"; }
set_ui 'Multiplayer\nickname' "$NICK"
# one Switch identity per session: two sessions with the same user profile and
# console serials are seen as the same player by local-wireless games (Mario
# Kart 8: "a communication error has occurred"), and would write the same saves.
# Each session claims a free profile (the configured one first) with a lock held
# for its whole life (fd 9 is inherited by Eden); the lock files live in the
# Eden data dir every session shares.
ini() { sed -n "s/^$1=//p" "$CFG/qt-config.ini" | head -1; }
SAVE=$(ini save_directory); SAVE=${SAVE:-$(ini nand_directory)}
NUSERS=$(python3 - "$SAVE/system/save/8000000000000010/su/avators/profiles.dat" <<'EOF' 2>/dev/null || echo 0
import sys
d = open(sys.argv[1], 'rb').read()
print(sum(d[o:o + 16] != bytes(16) for o in range(0x10, len(d) - 0xC7, 0xC8)))
EOF
)
LOCKS=$HOME/.local/share/eden/wolfy-session-users
mkdir -p "$LOCKS"
PREF=$(ini current_user)
for i in ${PREF:-0} $(seq 0 $((NUSERS - 1))); do
    [ "$i" -lt "$NUSERS" ] || continue
    exec 9>"$LOCKS/$i.lock"
    if flock -n 9; then set_key System current_user "$i"; break; fi
    exec 9>&-
done
SID=${WOLF_SESSION_ID:-$RANDOM$RANDOM}
set_key System serial_unit $((10#${SID: -9} % 4000000000 + 1))
set_key System serial_battery $((10#${SID: -10:9} % 4000000000 + 1))
set_key System device_name "$NICK"
# reach the host's room through the container's gateway (docker0 IP): the host
# answers from that address, and Eden drops replies coming from another IP than
# the one it dialled (host LAN IP -> "Unable to connect to the host")
G=$(awk '$2 == "00000000" {print $3; exit}' /proc/net/route)  # little-endian hex
[ -n "$G" ] && GW=$(printf '%d.%d.%d.%d' 0x${G:6:2} 0x${G:4:2} 0x${G:2:2} 0x${G:0:2})
set_ui 'Multiplayer\ip' "${EDEN_ROOM_HOST:-${GW:-172.17.0.1}}"
set_ui 'Multiplayer\port' "${EDEN_ROOM_PORT:-24872}"
# the host's NIC doesn't exist here: use the container's default route
# interface, else Eden reports "no network / airplane mode"
IFACE=$(awk '$2 == "00000000" {print $1; exit}' /proc/net/route)
set_key Services network_interface "${IFACE:-eth0}"
set_key Services airplane_mode false
# Wolf runs one PulseAudio server for all sessions: Eden's default (cubeb) sends
# sound to the server's default sink, i.e. another session. SDL2 honours
# $PULSE_SINK (this session's virtual sink).
set_key Audio output_engine 2
set_key Audio output_device auto
# return-to-HOME combo (Wolfy > Switch > Configurer): free the clashing Eden
# hotkey in this session's copy, then watch the session's pad
python3 /opt/gow/home-combo.py --patch-config "$CFG/qt-config.ini" || true
python3 /opt/gow/home-combo.py &
gow_log "Starting Eden (Switch HOME menu) as $NICK"

source /opt/gow/launch-comp.sh
# -qlaunch: boot the firmware HOME menu instead of Eden's game list
launcher /opt/gow/eden-run.sh
