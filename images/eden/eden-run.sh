#!/bin/bash
# Runs inside the sway session (SWAYSOCK and DISPLAY come from sway). Starts
# Eden on the HOME menu and joins the house multiplayer room automatically:
# Direct Connect hotkey (Ctrl+C, address pre-filled by startup-app.sh), confirm,
# then answer Yes to "Game already running" (the HOME menu counts as a game).
# Sway keeps focus on the fullscreen Eden window, so each dialog gets focused
# explicitly before its keys are sent. Never types text into the fields.
has() { swaymsg -t get_tree | grep -q "\"name\": \"$1\""; }
focus() { swaymsg -q "[title=\"$1\"] focus"; sleep 0.5; }
wait_for() { for _ in $(seq "$2"); do has "$1" && return 0; sleep 1; done; return 1; }

autojoin() {
    for _ in $(seq 60); do xdotool search --class eden >/dev/null 2>&1 && break; sleep 1; done
    sleep 8
    xdotool key --clearmodifiers ctrl+c
    wait_for "Connexion directe" 10 || return
    focus "Connexion directe"; xdotool key Return
    # answer Yes: the prompt ignores keys, so click its Yes button
    # (bottom right, just left of No: 145 px from the right, 22 px from the bottom)
    for _ in 1 2 3; do
        wait_for "Game already running" 5 || break
        focus "^Game already running$"  # else the fullscreen Eden window stays above it
        W=$(xdotool search --name "^Game already running$" | head -1)
        eval "$(xdotool getwindowgeometry --shell "$W")"
        xdotool mousemove --window "$W" $((WIDTH - 145)) $((HEIGHT - 22)) click 1
        sleep 3
    done
    # a failed attempt leaves an "Error" box: dismiss it and close the dialog
    if wait_for "Error" 5; then
        focus "Error"; xdotool key Return
        has "Connexion directe" && { focus "Connexion directe"; xdotool key Escape; }
    fi
    # focusing the dialogs dropped Eden out of fullscreen: put it back
    swaymsg -q '[title="^Eden \|"] fullscreen enable, focus'
    xdotool mousemove 1920 1080
}
autojoin >/dev/null 2>&1 &
exec /opt/eden/AppRun -qlaunch
