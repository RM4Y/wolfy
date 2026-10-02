#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh
gow_log "Starting RetroArch (PlayStation)"

# The host's flatpak RetroArch dir is mounted at the same "~/.var/app/..." path the
# config uses. Each session runs on its own copy of retroarch.cfg so concurrent sessions
# don't overwrite each other's config on exit; saves, states, BIOS, core options and
# thumbnails stay shared. Cores come from the image (/opt/wolfy), not from the PC.
RA=$HOME/.var/app/org.libretro.RetroArch/config/retroarch
CFG=$HOME/.config/retroarch/retroarch.cfg
mkdir -p "$HOME/.config/retroarch"
cp "$RA/retroarch.cfg" "$CFG"
set_cfg() {  # set_cfg key value (in this session's copy only)
    if grep -q "^$1 = " "$CFG"; then sed -i "s|^$1 = .*|$1 = \"$2\"|" "$CFG"; else echo "$1 = \"$2\"" >> "$CFG"; fi
}
PL=$HOME/.config/retroarch/playlists
set_cfg libretro_directory /opt/wolfy/cores
set_cfg libretro_info_path /opt/wolfy/info
set_cfg playlist_directory "$PL"
set_cfg content_history_path "$PL/builtin/content_history.lpl"
set_cfg content_favorites_path "$PL/builtin/content_favorites.lpl"
set_cfg content_image_history_path "$PL/builtin/content_image_history.lpl"
set_cfg content_music_history_path "$PL/builtin/content_music_history.lpl"
set_cfg content_video_history_path "$PL/builtin/content_video_history.lpl"
# pad: the shared config still has manual player bindings made for the Sunshine pad (other
# button numbers); drop them here so the Wolf pad profile (autoconfig) applies
sed -i -E 's/^(input_player[0-9]+_[a-z0-9_]+_(btn|axis)) = .*/\1 = "nul"/' "$CFG"
# no threaded video: only useful for software-rendered cores, and RetroArch crashed when
# going from the (threaded) menu to a GPU-rendered game (LRPS2, PPSSPP)
set_cfg video_threaded false
# playlists: session copy with the image's core paths, changes written back to the PC's
python3 /opt/gow/playlist-sync.py in
# PS3 / PS Vita: emulator settings for the session, playlists of the installed games
python3 /opt/wolfy/bin/ps-session-setup.py || true
python3 /opt/wolfy/bin/ps-playlists.py "$PL" || true
python3 /opt/gow/playlist-sync.py watch &

# gamepad combos (Wolfy > PlayStation > Configurer): Guide = RetroArch menu, or quits the
# running PS3 / PS Vita game (back to the XMB)
python3 /opt/gow/home-combo.py &

source /opt/gow/launch-comp.sh
# detailed log kept on the host (the container is deleted when the session ends)
LOG="$RA/logs/wolf-session-${WOLF_SESSION_ID: -4}.log"
mkdir -p "$RA/logs"
# X11 (XWayland) rather than native Wayland, as on the PC: in Wayland mode RetroArch
# died when switching from the menu to a game (video restart for the core)
launcher env -u WAYLAND_DISPLAY DISPLAY=:0 /usr/bin/retroarch --verbose --log-file "$LOG" --config "$HOME/.config/retroarch/retroarch.cfg"
